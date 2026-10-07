"""Badge class management service (FR-1, FR-2, FR-3).

Owns everything about badge *templates* (``BadgeClass``) and the tenant issuer
profile — creation, editing, deactivation, image upload, and directory
visibility. Issuance of individual badges lives in
:class:`app.services.issuance_service.IssuanceService`; this service is the
"design time" half of the feature.

Conventions mirror :class:`app.services.document_service.DocumentService`:
single-table queries under RLS (``set_tenant_context``), a boto3 S3 client built
the same way, malware scanning of uploaded images, and audit entries written
inside the caller's transaction.
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
from app.models.badge import BadgeClass
from app.models.tenant import Tenant
from app.services.audit_service import AuditService
from app.services.malware_scanner import (
    MalwareScanner,
    ScanUnavailableError,
    get_malware_scanner,
)

logger = logging.getLogger(__name__)

# Allowed badge image content types (Open Badges image is PNG or SVG).
_ALLOWED_IMAGE_TYPES: frozenset[str] = frozenset({"image/png", "image/svg+xml"})
_MAX_IMAGE_BYTES = 2 * 1024 * 1024  # 2 MB


@dataclass(frozen=True, slots=True)
class IssuerProfileData:
    """Tenant-level Open Badges issuer profile."""

    issuer_name: str | None
    issuer_url: str | None
    issuer_email: str | None


class BadgeService:
    """Manage badge classes and the tenant issuer profile."""

    def __init__(self, db: AsyncSession, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self._audit = AuditService(db)
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
    # BadgeClass CRUD (FR-1)
    # ------------------------------------------------------------------

    async def create_badge_class(
        self,
        tenant_id: UUID,
        name: str,
        description: str | None = None,
        criteria_narrative: str | None = None,
        criteria_url: str | None = None,
        tags: list[str] | None = None,
        alignment: list[dict] | None = None,
        validity_days: int | None = None,
        actor_id: str = "system",
        actor_role: str = "tenant_admin",
    ) -> BadgeClass:
        """Create a new badge class (FR-1.1)."""
        if not name or not name.strip():
            raise BadgeValidationError("name must be non-empty")
        if validity_days is not None and validity_days <= 0:
            raise BadgeValidationError("validity_days must be positive or null")

        await set_tenant_context(self.db, str(tenant_id))
        badge = BadgeClass(
            tenant_id=tenant_id,
            name=name.strip(),
            description=description,
            criteria_narrative=criteria_narrative,
            criteria_url=criteria_url,
            tags=tags or [],
            alignment=alignment or [],
            validity_days=validity_days,
            status="active",
        )
        self.db.add(badge)
        await self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor_id,
            actor_role=actor_role,
            operation="badge:create",
            resource_type="badge_class",
            resource_id="pending",
            outcome="success",
            metadata={"name": name},
        )
        await self.db.commit()
        await self.db.refresh(badge)
        return badge

    async def update_badge_class(
        self,
        tenant_id: UUID,
        badge_class_id: UUID,
        actor_id: str = "system",
        actor_role: str = "tenant_admin",
        **fields,
    ) -> BadgeClass:
        """Update mutable fields of a badge class (FR-1.2).

        Only known, whitelisted fields are applied; anything else is ignored so
        callers cannot mutate ``tenant_id`` or timestamps.
        """
        await set_tenant_context(self.db, str(tenant_id))
        badge = await self._get(badge_class_id)
        if badge is None:
            raise BadgeNotFoundError(badge_class_id)

        mutable = {
            "name",
            "description",
            "criteria_narrative",
            "criteria_url",
            "tags",
            "alignment",
            "validity_days",
            "certificate_template",
        }
        for key, value in fields.items():
            if key in mutable and value is not None:
                setattr(badge, key, value)

        await self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor_id,
            actor_role=actor_role,
            operation="badge:update",
            resource_type="badge_class",
            resource_id=str(badge_class_id),
            outcome="success",
        )
        await self.db.commit()
        await self.db.refresh(badge)
        return badge

    async def deactivate_badge_class(
        self,
        tenant_id: UUID,
        badge_class_id: UUID,
        actor_id: str = "system",
        actor_role: str = "tenant_admin",
    ) -> BadgeClass:
        """Deactivate a badge class (FR-1.3).

        Existing assertions remain valid — deactivation only prevents new
        issuance, mirroring how schema deactivation works for documents.
        """
        await set_tenant_context(self.db, str(tenant_id))
        badge = await self._get(badge_class_id)
        if badge is None:
            raise BadgeNotFoundError(badge_class_id)
        badge.status = "inactive"
        badge.directory_visible = False
        await self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor_id,
            actor_role=actor_role,
            operation="badge:deactivate",
            resource_type="badge_class",
            resource_id=str(badge_class_id),
            outcome="success",
        )
        await self.db.commit()
        await self.db.refresh(badge)
        return badge

    async def get_badge_class(
        self, tenant_id: UUID, badge_class_id: UUID
    ) -> BadgeClass | None:
        """Fetch a single badge class by id (FR-1.4)."""
        await set_tenant_context(self.db, str(tenant_id))
        return await self._get(badge_class_id)

    async def list_badge_classes(
        self,
        tenant_id: UUID,
        limit: int = 20,
        offset: int = 0,
        include_inactive: bool = True,
    ) -> list[BadgeClass]:
        """List badge classes for a tenant, newest first (FR-1.4)."""
        await set_tenant_context(self.db, str(tenant_id))
        stmt = select(BadgeClass)
        if not include_inactive:
            stmt = stmt.where(BadgeClass.status == "active")
        stmt = stmt.order_by(BadgeClass.created_at.desc()).limit(limit).offset(offset)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # Image upload (FR-2)
    # ------------------------------------------------------------------

    async def attach_image(
        self,
        tenant_id: UUID,
        badge_class_id: UUID,
        content: bytes,
        content_type: str,
        actor_id: str = "system",
        actor_role: str = "tenant_admin",
    ) -> BadgeClass:
        """Upload and attach a badge image to S3 (FR-2.1, FR-2.2).

        The image is malware-scanned before storage (never bypassed) and written
        under the ``badges/{tenant}/{class}`` prefix in the existing bucket.
        """
        if content_type not in _ALLOWED_IMAGE_TYPES:
            raise BadgeValidationError(
                f"image content_type must be one of: {sorted(_ALLOWED_IMAGE_TYPES)}"
            )
        if not content:
            raise BadgeValidationError("image content must be non-empty")
        if len(content) > _MAX_IMAGE_BYTES:
            raise BadgeValidationError("image exceeds 2 MB limit")

        await set_tenant_context(self.db, str(tenant_id))
        badge = await self._get(badge_class_id)
        if badge is None:
            raise BadgeNotFoundError(badge_class_id)

        # Malware scan — never bypass (mirrors document upload).
        try:
            scan = self.scanner.scan(content)
            if not scan.clean:
                raise BadgeValidationError(f"image rejected: malware ({scan.reason})")
        except ScanUnavailableError:
            raise BadgeServiceUnavailableError("Malware scan service unavailable")

        ext = "png" if content_type == "image/png" else "svg"
        s3_key = f"badges/{tenant_id}/{badge_class_id}/{uuid_mod.uuid4()}.{ext}"
        try:
            self._s3.put_object(
                Bucket=self.settings.s3_bucket_name,
                Key=s3_key,
                Body=content,
                ContentType=content_type,
                ServerSideEncryption="aws:kms",
            )
        except Exception as exc:
            logger.error("Badge image S3 upload failed: %s", exc)
            raise BadgeServiceUnavailableError("Storage service unavailable") from exc

        badge.image_s3_key = s3_key
        await self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor_id,
            actor_role=actor_role,
            operation="badge:image_upload",
            resource_type="badge_class",
            resource_id=str(badge_class_id),
            outcome="success",
        )
        await self.db.commit()
        await self.db.refresh(badge)
        return badge

    def presigned_image_url(self, s3_key: str) -> str:
        """Return a short-lived presigned GET URL for a badge image (Q4=A)."""
        return self._s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.settings.s3_bucket_name, "Key": s3_key},
            ExpiresIn=self.settings.presigned_url_ttl_seconds,
        )

    # ------------------------------------------------------------------
    # Directory visibility (FR-3 / public directory prerequisite)
    # ------------------------------------------------------------------

    async def set_directory_visibility(
        self,
        tenant_id: UUID,
        badge_class_id: UUID,
        visible: bool,
        actor_id: str = "system",
        actor_role: str = "tenant_admin",
    ) -> BadgeClass:
        """Toggle whether a badge class appears in the public directory."""
        await set_tenant_context(self.db, str(tenant_id))
        badge = await self._get(badge_class_id)
        if badge is None:
            raise BadgeNotFoundError(badge_class_id)
        if visible and badge.status != "active":
            raise BadgeValidationError("cannot publish an inactive badge class")
        badge.directory_visible = visible
        await self.db.commit()
        await self.db.refresh(badge)
        return badge

    # ------------------------------------------------------------------
    # Issuer profile (FR-3)
    # ------------------------------------------------------------------

    async def get_issuer_profile(self, tenant_id: UUID) -> IssuerProfileData:
        """Read the tenant's Open Badges issuer profile."""
        await set_tenant_context(self.db, str(tenant_id))
        result = await self.db.execute(
            select(
                Tenant.issuer_name, Tenant.issuer_url, Tenant.issuer_email
            ).where(Tenant.id == tenant_id)
        )
        row = result.one_or_none()
        if row is None:
            raise BadgeNotFoundError(tenant_id)
        return IssuerProfileData(
            issuer_name=row[0], issuer_url=row[1], issuer_email=row[2]
        )

    async def set_issuer_profile(
        self,
        tenant_id: UUID,
        issuer_name: str | None,
        issuer_url: str | None,
        issuer_email: str | None,
        actor_id: str = "system",
        actor_role: str = "tenant_admin",
    ) -> IssuerProfileData:
        """Update the tenant's Open Badges issuer profile (FR-3.1)."""
        await set_tenant_context(self.db, str(tenant_id))
        result = await self.db.execute(select(Tenant).where(Tenant.id == tenant_id))
        tenant = result.scalar_one_or_none()
        if tenant is None:
            raise BadgeNotFoundError(tenant_id)
        tenant.issuer_name = issuer_name
        tenant.issuer_url = issuer_url
        tenant.issuer_email = issuer_email
        await self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor_id,
            actor_role=actor_role,
            operation="badge:issuer_profile_update",
            resource_type="tenant",
            resource_id=str(tenant_id),
            outcome="success",
        )
        await self.db.commit()
        return IssuerProfileData(
            issuer_name=tenant.issuer_name,
            issuer_url=tenant.issuer_url,
            issuer_email=tenant.issuer_email,
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _get(self, badge_class_id: UUID) -> BadgeClass | None:
        result = await self.db.execute(
            select(BadgeClass).where(BadgeClass.id == badge_class_id)
        )
        return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class BadgeNotFoundError(Exception):
    def __init__(self, badge_id: UUID) -> None:
        self.badge_id = badge_id
        super().__init__(f"Badge class not found: {badge_id}")


class BadgeValidationError(Exception):
    pass


class BadgeServiceUnavailableError(Exception):
    pass


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------


async def get_badge_service(db: AsyncSession = Depends(get_db)) -> BadgeService:
    return BadgeService(db=db, settings=get_settings())
