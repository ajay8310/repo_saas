"""Certificate orchestration (U4).

Ties together the pieces needed to produce a downloadable, issuer-signed
certificate PDF for a badge assertion, and to attach a recipient photo:

1. resolve the assertion + its badge class (ownership-checked for earners),
2. fetch the badge image and recipient photo from S3 (best effort),
3. ensure the tenant's issuer signing keypair and sign the credential payload,
4. render the PDF with the class's chosen template, and
5. audit + record a ``viewed`` analytics event.

Follows the established service conventions: RLS via ``set_tenant_context``, a
boto3 S3 client built like ``DocumentService``, malware scanning on upload, and
audit entries inside the transaction.
"""

from __future__ import annotations

import logging
import uuid as uuid_mod
from dataclasses import dataclass
from uuid import UUID

import boto3
from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.session import get_db
from app.middleware.tenant_context import set_tenant_context
from app.models.badge import BadgeAssertion, BadgeClass
from app.models.tenant import Tenant
from app.services.audit_service import AuditService
from app.services.badge_event_service import BadgeEventService
from app.services.certificate_renderer import CertificateContext, render_certificate
from app.services.issuer_signing_service import IssuerSigningService
from app.services.malware_scanner import (
    MalwareScanner,
    ScanUnavailableError,
    get_malware_scanner,
)

logger = logging.getLogger(__name__)

_ALLOWED_PHOTO_TYPES: frozenset[str] = frozenset(
    {"image/png", "image/jpeg", "image/jpg"}
)


@dataclass(frozen=True, slots=True)
class RenderedCertificate:
    content: bytes
    media_type: str
    filename: str


class CertificateService:
    """Build badge certificates and manage recipient photos."""

    def __init__(self, db: AsyncSession, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self._audit = AuditService(db)
        self._events = BadgeEventService(db)
        self._signing = IssuerSigningService(db, settings)
        self._s3 = self._create_s3_client()
        self._scanner: MalwareScanner | None = None

    @property
    def scanner(self) -> MalwareScanner:
        if self._scanner is None:
            self._scanner = get_malware_scanner()
        return self._scanner

    def _create_s3_client(self):
        kwargs: dict = {"region_name": self.settings.aws_region}
        if self.settings.s3_endpoint_url:
            kwargs["endpoint_url"] = self.settings.s3_endpoint_url
        if self.settings.aws_access_key_id:
            kwargs["aws_access_key_id"] = self.settings.aws_access_key_id
            kwargs["aws_secret_access_key"] = self.settings.aws_secret_access_key
        return boto3.client("s3", **kwargs)

    # ------------------------------------------------------------------
    # Recipient photo upload (Q6)
    # ------------------------------------------------------------------

    async def upload_recipient_photo(
        self,
        tenant_id: UUID,
        assertion_id: UUID,
        content: bytes,
        content_type: str,
        actor_id: str = "system",
        actor_role: str = "issuer",
    ) -> str:
        """Scan, store, and attach a recipient photo. Returns the S3 key."""
        if content_type not in _ALLOWED_PHOTO_TYPES:
            raise CertificateValidationError(
                f"photo content_type must be one of {sorted(_ALLOWED_PHOTO_TYPES)}"
            )
        if not content:
            raise CertificateValidationError("photo content must be non-empty")
        if len(content) > self.settings.certificate_photo_max_bytes:
            raise CertificateValidationError("photo exceeds the maximum allowed size")

        await set_tenant_context(self.db, str(tenant_id))
        assertion = await self._get_assertion(assertion_id)
        if assertion is None:
            raise CertificateNotFoundError(assertion_id)

        try:
            scan = self.scanner.scan(content)
            if not scan.clean:
                raise CertificateValidationError(f"photo rejected: malware ({scan.reason})")
        except ScanUnavailableError:
            raise CertificateServiceUnavailableError("Malware scan service unavailable")

        ext = "png" if content_type == "image/png" else "jpg"
        s3_key = (
            f"{self.settings.badge_image_prefix}/{tenant_id}/"
            f"{assertion.badge_class_id}/photos/{assertion_id}-{uuid_mod.uuid4()}.{ext}"
        )
        try:
            self._s3.put_object(
                Bucket=self.settings.s3_bucket_name,
                Key=s3_key,
                Body=content,
                ContentType=content_type,
                ServerSideEncryption="aws:kms",
            )
        except Exception as exc:
            logger.error("Recipient photo S3 upload failed: %s", exc)
            raise CertificateServiceUnavailableError("Storage service unavailable") from exc

        assertion.recipient_photo_s3_key = s3_key
        await self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor_id,
            actor_role=actor_role,
            operation="badge:photo_upload",
            resource_type="badge_assertion",
            resource_id=str(assertion_id),
            outcome="success",
        )
        await self.db.commit()
        return s3_key

    # ------------------------------------------------------------------
    # Certificate build (Q3/Q4/Q5/Q7)
    # ------------------------------------------------------------------

    async def build_certificate(
        self,
        tenant_id: UUID,
        assertion_id: UUID,
        actor_id: str = "system",
        actor_role: str = "issuer",
        require_owner: str | None = None,
    ) -> RenderedCertificate:
        """Render an issuer-signed certificate PDF for an assertion.

        ``require_owner`` (the earner's identity) restricts the download to the
        owning beneficiary; None means an issuer/admin download. Returns 404-like
        errors when the assertion is missing or not owned.
        """
        await set_tenant_context(self.db, str(tenant_id))
        assertion = await self._get_assertion(assertion_id)
        if assertion is None:
            raise CertificateNotFoundError(assertion_id)
        if require_owner is not None and assertion.beneficiary_id != require_owner:
            raise CertificateNotFoundError(assertion_id)

        badge_class = await self._get_class(assertion.badge_class_id)
        tenant = await self._get_tenant(tenant_id)

        # Images (best effort — a missing image just renders without it).
        badge_image = (
            self._fetch_s3(badge_class.image_s3_key) if badge_class and badge_class.image_s3_key else None
        )
        recipient_photo = (
            self._fetch_s3(assertion.recipient_photo_s3_key)
            if assertion.recipient_photo_s3_key
            else None
        )

        verify_url = (
            f"{self.settings.public_base_url}"
            f"/api/v1/public/badges/assertions/{assertion_id}"
        )

        # Sign the credential payload with the issuer's own key (Q7).
        payload = {
            "assertion_id": str(assertion_id),
            "badge": badge_class.name if badge_class else "",
            "recipient": _mask_identity(assertion.beneficiary_id),
            "issuer": tenant.issuer_name if tenant and tenant.issuer_name else (tenant.name if tenant else ""),
            "issued_at": assertion.issued_at.isoformat() if assertion.issued_at else "",
            "status": assertion.status,
        }
        signature = await self._signing.sign(tenant_id, payload)

        ctx = CertificateContext(
            assertion_id=str(assertion_id),
            badge_name=badge_class.name if badge_class else "Badge",
            recipient_display=_mask_identity(assertion.beneficiary_id),
            issuer_name=(tenant.issuer_name if tenant and tenant.issuer_name else (tenant.name if tenant else "Issuer")),
            issued_at=assertion.issued_at.isoformat() if assertion.issued_at else "",
            expires_at=assertion.expires_at.isoformat() if assertion.expires_at else None,
            criteria=badge_class.criteria_narrative if badge_class else None,
            verify_url=verify_url,
            signature_jws=signature,
            status=assertion.status,
            revoked_at=assertion.revoked_at.isoformat() if assertion.revoked_at else None,
            revocation_reason=assertion.revocation_reason,
            badge_image=badge_image,
            recipient_photo=recipient_photo,
        )

        template = badge_class.certificate_template if badge_class else self.settings.certificate_default_template
        pdf = render_certificate(ctx, template)

        self._events.record(
            tenant_id=tenant_id,
            event_type="viewed",
            badge_class_id=assertion.badge_class_id,
            assertion_id=assertion_id,
            channel="certificate",
        )
        await self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor_id,
            actor_role=actor_role,
            operation="badge:certificate_download",
            resource_type="badge_assertion",
            resource_id=str(assertion_id),
            outcome="success",
            metadata={"template": template},
        )
        await self.db.commit()

        return RenderedCertificate(
            content=pdf,
            media_type="application/pdf",
            filename=f"certificate-{assertion_id}.pdf",
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _get_assertion(self, assertion_id: UUID) -> BadgeAssertion | None:
        result = await self.db.execute(
            select(BadgeAssertion).where(BadgeAssertion.id == assertion_id)
        )
        return result.scalar_one_or_none()

    async def _get_class(self, badge_class_id: UUID) -> BadgeClass | None:
        result = await self.db.execute(
            select(BadgeClass).where(BadgeClass.id == badge_class_id)
        )
        return result.scalar_one_or_none()

    async def _get_tenant(self, tenant_id: UUID) -> Tenant | None:
        result = await self.db.execute(select(Tenant).where(Tenant.id == tenant_id))
        return result.scalar_one_or_none()

    def _fetch_s3(self, key: str) -> bytes | None:
        try:
            resp = self._s3.get_object(Bucket=self.settings.s3_bucket_name, Key=key)
            return resp["Body"].read()
        except Exception:
            logger.debug("Could not fetch S3 object %s for certificate", key, exc_info=True)
            return None


def _mask_identity(identity: str) -> str:
    """Render a display name from an identity without exposing a raw email.

    ``alice@example.com`` → ``alice`` (local part), other identifiers pass
    through. Mirrors the "never show raw email" posture used elsewhere.
    """
    if "@" in identity:
        return identity.split("@", 1)[0]
    return identity


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class CertificateNotFoundError(Exception):
    def __init__(self, assertion_id: UUID) -> None:
        self.assertion_id = assertion_id
        super().__init__(f"Assertion not found: {assertion_id}")


class CertificateValidationError(Exception):
    pass


class CertificateServiceUnavailableError(Exception):
    pass


async def get_certificate_service(
    db: AsyncSession = Depends(get_db),
) -> CertificateService:
    return CertificateService(db=db, settings=get_settings())
