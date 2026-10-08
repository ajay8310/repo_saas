"""Issuer-designed certificate templates (U5).

CRUD + asset upload + server-side preview + badge-class assignment for the
visual certificate designer. Mirrors the established service conventions:

* RLS via ``set_tenant_context`` before every query,
* an inline boto3 S3 client (like ``BadgeService``/``CertificateService``),
* malware scanning on every asset upload (fails closed → 503, never bypassed),
* audit entries written inside the transaction, and
* a ``get_certificate_template_service`` factory for DI.

Rendering reuses the data-driven custom renderer in ``certificate_renderer`` so
there is a single rendering engine; the verification QR + issuer signature are
always present (the renderer injects a default panel if a layout omits them).
"""

from __future__ import annotations

import logging
import uuid as uuid_mod
from dataclasses import dataclass
from uuid import UUID

import boto3
from fastapi import Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.session import get_db
from app.middleware.tenant_context import set_tenant_context
from app.models.badge import BadgeClass
from app.models.certificate_template import CertificateTemplate
from app.services.audit_service import AuditService
from app.services.certificate_layout import validate_layout
from app.services.certificate_renderer import (
    CertificateContext,
    CustomAssets,
    render_custom_certificate,
)
from app.services.malware_scanner import (
    MalwareScanner,
    ScanUnavailableError,
    get_malware_scanner,
)

logger = logging.getLogger(__name__)

_ALLOWED_ASSET_TYPES: frozenset[str] = frozenset(
    {"image/png", "image/jpeg", "image/jpg"}
)
_ASSET_KINDS: frozenset[str] = frozenset({"logo", "background"})


@dataclass(frozen=True, slots=True)
class RenderedPreview:
    content: bytes
    media_type: str
    filename: str


class CertificateTemplateService:
    """Manage issuer-designed certificate templates and their assets."""

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
    # CRUD
    # ------------------------------------------------------------------

    async def create(
        self,
        tenant_id: UUID,
        name: str,
        orientation: str,
        layout: dict,
        actor_id: str = "system",
        actor_role: str = "issuer",
    ) -> CertificateTemplate:
        """Create a template after validating its layout."""
        self._validate(name, orientation, layout)
        await set_tenant_context(self.db, str(tenant_id))
        tpl = CertificateTemplate(
            tenant_id=tenant_id,
            name=name.strip(),
            orientation=orientation,
            layout=layout,
            version=1,
            status="active",
        )
        self.db.add(tpl)
        # Flush so the server-default UUID PK is populated before we write the
        # audit row (audit_logs.resource_id is NOT NULL).
        await self.db.flush()
        await self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor_id,
            actor_role=actor_role,
            operation="badge:template_create",
            resource_type="certificate_template",
            resource_id=str(tpl.id),
            outcome="success",
        )
        await self.db.commit()
        await self.db.refresh(tpl)
        return tpl

    async def list(self, tenant_id: UUID) -> list[CertificateTemplate]:
        await set_tenant_context(self.db, str(tenant_id))
        result = await self.db.execute(
            select(CertificateTemplate)
            .where(CertificateTemplate.status != "archived")
            .order_by(CertificateTemplate.created_at.desc())
        )
        return list(result.scalars().all())

    async def get(self, tenant_id: UUID, template_id: UUID) -> CertificateTemplate | None:
        await set_tenant_context(self.db, str(tenant_id))
        return await self._get(template_id)

    async def update(
        self,
        tenant_id: UUID,
        template_id: UUID,
        name: str | None = None,
        orientation: str | None = None,
        layout: dict | None = None,
        actor_id: str = "system",
        actor_role: str = "issuer",
    ) -> CertificateTemplate:
        """Update name/orientation/layout and bump the version (FR-U5-13)."""
        await set_tenant_context(self.db, str(tenant_id))
        tpl = await self._get(template_id)
        if tpl is None:
            raise TemplateNotFoundError(template_id)

        new_name = name if name is not None else tpl.name
        new_orientation = orientation if orientation is not None else tpl.orientation
        new_layout = layout if layout is not None else tpl.layout
        self._validate(new_name, new_orientation, new_layout)

        tpl.name = new_name.strip()
        tpl.orientation = new_orientation
        tpl.layout = new_layout
        tpl.version = (tpl.version or 1) + 1
        await self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor_id,
            actor_role=actor_role,
            operation="badge:template_update",
            resource_type="certificate_template",
            resource_id=str(template_id),
            outcome="success",
            metadata={"version": tpl.version},
        )
        await self.db.commit()
        await self.db.refresh(tpl)
        return tpl

    async def delete(
        self,
        tenant_id: UUID,
        template_id: UUID,
        actor_id: str = "system",
        actor_role: str = "issuer",
    ) -> None:
        """Archive a template. Blocked (409) if any badge class still uses it."""
        await set_tenant_context(self.db, str(tenant_id))
        tpl = await self._get(template_id)
        if tpl is None:
            raise TemplateNotFoundError(template_id)

        in_use = await self.db.execute(
            select(func.count())
            .select_from(BadgeClass)
            .where(BadgeClass.custom_template_id == template_id)
        )
        if (in_use.scalar() or 0) > 0:
            raise TemplateInUseError(template_id)

        tpl.status = "archived"
        await self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor_id,
            actor_role=actor_role,
            operation="badge:template_delete",
            resource_type="certificate_template",
            resource_id=str(template_id),
            outcome="success",
        )
        await self.db.commit()

    # ------------------------------------------------------------------
    # Assets (logo / background)
    # ------------------------------------------------------------------

    async def upload_asset(
        self,
        tenant_id: UUID,
        template_id: UUID,
        kind: str,
        content: bytes,
        content_type: str,
        actor_id: str = "system",
        actor_role: str = "issuer",
    ) -> str:
        """Scan + store a logo/background asset. Returns the S3 key."""
        if kind not in _ASSET_KINDS:
            raise TemplateValidationError(f"kind must be one of {sorted(_ASSET_KINDS)}")
        if content_type not in _ALLOWED_ASSET_TYPES:
            raise TemplateValidationError(
                f"content_type must be one of {sorted(_ALLOWED_ASSET_TYPES)}"
            )
        if not content:
            raise TemplateValidationError("asset content must be non-empty")
        if len(content) > self.settings.certificate_template_asset_max_bytes:
            raise TemplateValidationError("asset exceeds the maximum allowed size")

        await set_tenant_context(self.db, str(tenant_id))
        tpl = await self._get(template_id)
        if tpl is None:
            raise TemplateNotFoundError(template_id)

        # Malware scan — never bypass (fails closed → 503).
        try:
            scan = self.scanner.scan(content)
            if not scan.clean:
                raise TemplateValidationError(f"asset rejected: malware ({scan.reason})")
        except ScanUnavailableError:
            raise TemplateServiceUnavailableError("Malware scan service unavailable")

        ext = "png" if content_type == "image/png" else "jpg"
        s3_key = (
            f"{self.settings.badge_image_prefix}/{tenant_id}/templates/"
            f"{template_id}/{kind}-{uuid_mod.uuid4()}.{ext}"
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
            logger.error("Template asset S3 upload failed: %s", exc)
            raise TemplateServiceUnavailableError("Storage service unavailable") from exc

        if kind == "logo":
            tpl.logo_s3_key = s3_key
        else:
            tpl.background_s3_key = s3_key
        await self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor_id,
            actor_role=actor_role,
            operation="badge:template_asset_upload",
            resource_type="certificate_template",
            resource_id=str(template_id),
            outcome="success",
            metadata={"kind": kind},
        )
        await self.db.commit()
        return s3_key

    # ------------------------------------------------------------------
    # Preview (no persistence)
    # ------------------------------------------------------------------

    async def render_preview(
        self,
        tenant_id: UUID,
        layout: dict,
        logo_s3_key: str | None = None,
        background_s3_key: str | None = None,
    ) -> RenderedPreview:
        """Render *layout* with representative sample data (no persistence).

        Used by the designer's live preview. Assets, when provided, are fetched
        from S3; a bad layout still returns a PDF (renderer falls back).
        """
        ctx = _sample_context(self.settings)
        assets = CustomAssets(
            logo=self._fetch_s3(logo_s3_key) if logo_s3_key else None,
            background=self._fetch_s3(background_s3_key) if background_s3_key else None,
        )
        pdf = render_custom_certificate(ctx, layout or {}, assets)
        return RenderedPreview(
            content=pdf, media_type="application/pdf", filename="preview.pdf"
        )

    async def render_preview_of(
        self, tenant_id: UUID, template_id: UUID
    ) -> RenderedPreview:
        """Preview a saved template (resolves its own stored assets)."""
        await set_tenant_context(self.db, str(tenant_id))
        tpl = await self._get(template_id)
        if tpl is None:
            raise TemplateNotFoundError(template_id)
        return await self.render_preview(
            tenant_id, tpl.layout, tpl.logo_s3_key, tpl.background_s3_key
        )

    # ------------------------------------------------------------------
    # Assignment
    # ------------------------------------------------------------------

    async def assign_to_class(
        self,
        tenant_id: UUID,
        badge_class_id: UUID,
        template_id: UUID | None,
        actor_id: str = "system",
        actor_role: str = "issuer",
    ) -> BadgeClass:
        """Set or clear a badge class's custom template.

        ``template_id=None`` clears it (reverts to the built-in template). A
        provided id must exist for this tenant.
        """
        await set_tenant_context(self.db, str(tenant_id))
        badge = (
            await self.db.execute(
                select(BadgeClass).where(BadgeClass.id == badge_class_id)
            )
        ).scalar_one_or_none()
        if badge is None:
            raise TemplateNotFoundError(badge_class_id)

        if template_id is not None:
            tpl = await self._get(template_id)
            if tpl is None or tpl.status != "active":
                raise TemplateNotFoundError(template_id)

        badge.custom_template_id = template_id
        await self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor_id,
            actor_role=actor_role,
            operation="badge:template_assign",
            resource_type="badge_class",
            resource_id=str(badge_class_id),
            outcome="success",
            metadata={"custom_template_id": str(template_id) if template_id else None},
        )
        await self.db.commit()
        await self.db.refresh(badge)
        return badge

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _validate(self, name: str, orientation: str, layout: dict) -> None:
        if not name or not name.strip():
            raise TemplateValidationError("name is required")
        if orientation not in ("portrait", "landscape"):
            raise TemplateValidationError("orientation must be portrait or landscape")
        issues = validate_layout(
            layout or {}, max_blocks=self.settings.certificate_template_max_blocks
        )
        if issues:
            raise TemplateValidationError("; ".join(issues))

    async def _get(self, template_id: UUID) -> CertificateTemplate | None:
        result = await self.db.execute(
            select(CertificateTemplate).where(CertificateTemplate.id == template_id)
        )
        return result.scalar_one_or_none()

    def _fetch_s3(self, key: str) -> bytes | None:
        try:
            resp = self._s3.get_object(Bucket=self.settings.s3_bucket_name, Key=key)
            return resp["Body"].read()
        except Exception:
            logger.debug("Could not fetch template asset %s", key, exc_info=True)
            return None


def _sample_context(settings: Settings) -> CertificateContext:
    """Representative data for a designer preview (no real assertion)."""
    verify_url = f"{settings.public_base_url}/api/v1/public/badges/assertions/sample"
    return CertificateContext(
        assertion_id="sample-0000",
        badge_name="Advanced Python",
        recipient_display="Jane Learner",
        issuer_name="Demo University",
        issued_at="2026-10-08",
        expires_at="2027-10-08",
        criteria="Pass the proctored assessment with 80% or higher.",
        verify_url=verify_url,
        signature_jws="sample.header.sample_signature_preview_only",
        status="active",
    )


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class TemplateNotFoundError(Exception):
    def __init__(self, template_id: UUID) -> None:
        self.template_id = template_id
        super().__init__(f"Certificate template not found: {template_id}")


class TemplateValidationError(Exception):
    pass


class TemplateInUseError(Exception):
    def __init__(self, template_id: UUID) -> None:
        self.template_id = template_id
        super().__init__(f"Template is assigned to one or more badge classes: {template_id}")


class TemplateServiceUnavailableError(Exception):
    pass


async def get_certificate_template_service(
    db: AsyncSession = Depends(get_db),
) -> CertificateTemplateService:
    return CertificateTemplateService(db=db, settings=get_settings())
