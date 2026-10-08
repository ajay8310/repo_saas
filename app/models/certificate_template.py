"""ORM model for issuer-designed certificate templates (U5).

``CertificateTemplate`` is a tenant-scoped, versioned, saved certificate layout
produced by the visual designer. The ``layout`` JSONB holds page settings and a
list of positioned blocks (text / recipient_photo / badge_image / logo / qr /
signature / line / rect); ``logo_s3_key`` and ``background_s3_key`` point at
uploaded assets in S3 (SSE-KMS, malware-scanned).

A badge class references a template via ``BadgeClass.custom_template_id`` (added
in migration 007). When that FK is set it takes precedence over the built-in
``certificate_template`` string; when null, the built-in path renders.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class CertificateTemplate(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Tenant-scoped, versioned certificate layout designed by an issuer."""

    __tablename__ = "certificate_templates"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # portrait | landscape (CHECK enforced in the migration).
    orientation: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="portrait"
    )
    # {"page": {...}, "blocks": [...]} — see CertificateLayout validation.
    layout: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="'{}'")
    logo_s3_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    background_s3_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    # Bumped on every layout/name update; recorded for audit (FR-U5-13).
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    # active | archived (CHECK enforced in the migration).
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="active"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
