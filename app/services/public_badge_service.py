"""Public (unauthenticated) badge read service (S13, FR-13).

Resolves and serializes the hosted Open Badges 2.0 artifacts for the public
router. Because these requests carry no JWT, tenant context is established from
the row resolved by primary key, and only rows whose ``public`` flag is set (or,
for classes, ``directory_visible``) are ever exposed — anything else surfaces as
``None`` so the router returns a uniform 404 (Q7=A).

A revoked-but-public assertion still resolves (Q3=A): the serializer emits
``revoked: true`` rather than the row being hidden.

Hosted JSON is cached in Redis with a short TTL to absorb verification spikes;
the cache is keyed by resource id and fails open when Redis is unavailable.
"""

from __future__ import annotations

import json
import logging
from uuid import UUID

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.session import get_db
from app.middleware.tenant_context import set_tenant_context
from app.models.badge import BadgeAssertion, BadgeClass
from app.models.tenant import Tenant
from app.services.badge_event_service import BadgeEventService
from app.services.issuance_service import new_recipient_salt
from app.services.openbadges import (
    AssertionData,
    BadgeClassData,
    IssuerProfile,
    OpenBadgesSerializer,
)

logger = logging.getLogger(__name__)

_CACHE_PREFIX = "obadge:"


class PublicBadgeService:
    """Serve hosted OB 2.0 artifacts for publicly visible badges."""

    def __init__(self, db: AsyncSession, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self._serializer = OpenBadgesSerializer()
        self._events = BadgeEventService(db)

    # ------------------------------------------------------------------
    # Public URL builders
    # ------------------------------------------------------------------

    def _assertion_url(self, assertion_id: UUID) -> str:
        return f"{self.settings.public_base_url}/api/v1/public/badges/assertions/{assertion_id}"

    def _class_url(self, badge_class_id: UUID) -> str:
        return f"{self.settings.public_base_url}/api/v1/public/badges/classes/{badge_class_id}"

    def _issuer_url(self, tenant_id: UUID) -> str:
        return f"{self.settings.public_base_url}/api/v1/public/badges/issuers/{tenant_id}"

    # ------------------------------------------------------------------
    # Hosted assertion (S13)
    # ------------------------------------------------------------------

    async def get_hosted_assertion(self, assertion_id: UUID) -> dict | None:
        """Return the OB Assertion JSON for a public assertion, else None."""
        cached = await self._cache_get("assertion", assertion_id)
        if cached is not None:
            return cached

        # Resolve without tenant scope first (single UNIQUE index on id), then
        # set the tenant context to the row's own tenant and re-read under RLS.
        assertion = await self._resolve_assertion(assertion_id)
        if assertion is None or not assertion.public:
            return None

        badge_class = await self._get_class(assertion.badge_class_id)
        if badge_class is None or badge_class.status != "active":
            return None
        tenant = await self._get_tenant(assertion.tenant_id)

        issuer = self._issuer_profile(tenant, assertion.tenant_id)
        badge_data = self._badge_class_data(badge_class, issuer)
        assertion_data = AssertionData(
            id_url=self._assertion_url(assertion_id),
            recipient_identity=assertion.beneficiary_id,
            # A stable per-assertion salt is not persisted in U1; generate one so
            # the hashed identity is non-trivially reversible. Deterministic
            # salting is a future refinement.
            recipient_salt=new_recipient_salt(),
            issued_on=assertion.issued_at,
            verify_url=self._assertion_url(assertion_id),
            badge_class=badge_data,
            expires=assertion.expires_at,
            revoked=assertion.status == "revoked",
            revocation_reason=assertion.revocation_reason,
        )
        doc = self._serializer.assertion(assertion_data)
        # Recipient photo is exposed on the public page only when the assertion
        # is public (Q8) — enables visual authenticity checks against the cert.
        if assertion.recipient_photo_s3_key:
            try:
                from app.services.badge_service import BadgeService

                doc["recipientPhoto"] = BadgeService(
                    db=self.db, settings=self.settings
                ).presigned_image_url(assertion.recipient_photo_s3_key)
            except Exception:
                logger.debug("Could not presign recipient photo", exc_info=True)
        # Reference the issuer key so a verifier can locate the signing public key.
        doc["issuerKeyUrl"] = (
            f"{self.settings.public_base_url}"
            f"/api/v1/public/badges/issuers/{assertion.tenant_id}/key"
        )
        await self._cache_set("assertion", assertion_id, doc)
        return doc

    async def get_issuer_public_key(self, tenant_id: UUID) -> dict | None:
        """Return the issuer's published signing public key (Q7).

        Generates the keypair lazily if the tenant has none, so the endpoint is
        always usable for a tenant that has issued certificates.
        """
        tenant = await self._get_tenant(tenant_id)
        if tenant is None:
            return None
        from app.services.issuer_signing_service import IssuerSigningService

        signing = IssuerSigningService(db=self.db, settings=self.settings)
        return await signing.public_jwk_reference(tenant_id)

    # ------------------------------------------------------------------
    # Hosted badge class
    # ------------------------------------------------------------------

    async def get_hosted_badge_class(self, badge_class_id: UUID) -> dict | None:
        """Return the OB BadgeClass JSON when publicly visible, else None."""
        cached = await self._cache_get("class", badge_class_id)
        if cached is not None:
            return cached

        badge_class = await self._resolve_class(badge_class_id)
        if (
            badge_class is None
            or badge_class.status != "active"
            or not badge_class.directory_visible
        ):
            return None
        tenant = await self._get_tenant(badge_class.tenant_id)
        issuer = self._issuer_profile(tenant, badge_class.tenant_id)
        doc = self._serializer.badge_class(self._badge_class_data(badge_class, issuer))
        await self._cache_set("class", badge_class_id, doc)
        return doc

    # ------------------------------------------------------------------
    # Hosted issuer
    # ------------------------------------------------------------------

    async def get_hosted_issuer(self, tenant_id: UUID) -> dict | None:
        """Return the OB Issuer JSON for a tenant that has published a profile."""
        cached = await self._cache_get("issuer", tenant_id)
        if cached is not None:
            return cached
        tenant = await self._get_tenant(tenant_id)
        if tenant is None or not tenant.issuer_name:
            return None
        doc = self._serializer.issuer(self._issuer_profile(tenant, tenant_id))
        await self._cache_set("issuer", tenant_id, doc)
        return doc

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    async def record_verification(self, assertion_id: UUID) -> None:
        """Record a best-effort 'verified' analytics event."""
        try:
            assertion = await self._resolve_assertion(assertion_id)
            if assertion is None:
                return
            await set_tenant_context(self.db, str(assertion.tenant_id))
            self._events.record(
                tenant_id=assertion.tenant_id,
                event_type="verified",
                badge_class_id=assertion.badge_class_id,
                assertion_id=assertion_id,
                channel="public",
            )
            await self.db.commit()
        except Exception:
            logger.debug("Could not record verification event", exc_info=True)

    # ------------------------------------------------------------------
    # Resolution helpers
    # ------------------------------------------------------------------

    async def _resolve_assertion(self, assertion_id: UUID) -> BadgeAssertion | None:
        """Resolve an assertion by id, then re-scope RLS to its tenant.

        The first read runs without a tenant GUC (unauth request). Public rows
        are readable because the ``public`` filter is applied in Python; we then
        set the tenant context so subsequent related reads are RLS-scoped.
        """
        result = await self.db.execute(
            select(BadgeAssertion).where(BadgeAssertion.id == assertion_id)
        )
        assertion = result.scalar_one_or_none()
        if assertion is not None:
            await set_tenant_context(self.db, str(assertion.tenant_id))
        return assertion

    async def _resolve_class(self, badge_class_id: UUID) -> BadgeClass | None:
        result = await self.db.execute(
            select(BadgeClass).where(BadgeClass.id == badge_class_id)
        )
        badge_class = result.scalar_one_or_none()
        if badge_class is not None:
            await set_tenant_context(self.db, str(badge_class.tenant_id))
        return badge_class

    async def _get_class(self, badge_class_id: UUID) -> BadgeClass | None:
        result = await self.db.execute(
            select(BadgeClass).where(BadgeClass.id == badge_class_id)
        )
        return result.scalar_one_or_none()

    async def _get_tenant(self, tenant_id: UUID) -> Tenant | None:
        result = await self.db.execute(select(Tenant).where(Tenant.id == tenant_id))
        return result.scalar_one_or_none()

    def _issuer_profile(self, tenant: Tenant | None, tenant_id: UUID) -> IssuerProfile:
        name = (tenant.issuer_name if tenant else None) or (
            tenant.name if tenant else "Unknown Issuer"
        )
        return IssuerProfile(
            id_url=self._issuer_url(tenant_id),
            name=name,
            url=tenant.issuer_url if tenant else None,
            email=tenant.issuer_email if tenant else None,
        )

    def _badge_class_data(
        self, badge_class: BadgeClass, issuer: IssuerProfile
    ) -> BadgeClassData:
        image_url = None
        if badge_class.image_s3_key:
            try:
                from app.services.badge_service import BadgeService

                image_url = BadgeService(
                    db=self.db, settings=self.settings
                ).presigned_image_url(badge_class.image_s3_key)
            except Exception:
                logger.debug("Could not presign badge image", exc_info=True)
        return BadgeClassData(
            id_url=self._class_url(badge_class.id),
            name=badge_class.name,
            description=badge_class.description,
            image_url=image_url,
            criteria_narrative=badge_class.criteria_narrative,
            criteria_url=badge_class.criteria_url,
            issuer=issuer,
            tags=list(badge_class.tags or []),
            alignment=list(badge_class.alignment or []),
        )

    # ------------------------------------------------------------------
    # Redis short-TTL cache (fails open)
    # ------------------------------------------------------------------

    async def _cache_get(self, kind: str, ident: UUID) -> dict | None:
        try:
            from app.db.redis import get_redis_client

            redis = get_redis_client()
            raw = await redis.get(f"{_CACHE_PREFIX}{kind}:{ident}")
            return json.loads(raw) if raw else None
        except Exception:
            return None

    async def _cache_set(self, kind: str, ident: UUID, doc: dict) -> None:
        try:
            from app.db.redis import get_redis_client

            redis = get_redis_client()
            await redis.set(
                f"{_CACHE_PREFIX}{kind}:{ident}",
                json.dumps(doc),
                ex=self.settings.obadge_cache_ttl_seconds,
            )
        except Exception:
            logger.debug("Could not cache hosted badge doc", exc_info=True)


async def get_public_badge_service(
    db: AsyncSession = Depends(get_db),
) -> PublicBadgeService:
    return PublicBadgeService(db=db, settings=get_settings())
