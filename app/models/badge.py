"""ORM models for the Credly-style badge feature.

- ``BadgeClass``      — tenant-scoped badge template (standard UUID PK).
- ``BadgeAssertion``  — issued instance; partitioned by ``issued_at`` (composite PK
  ``(id, issued_at)``) with a UNIQUE index on ``id`` alone so the assertion id equals
  the linked ``documents.id`` / credential_id and stays a single public identifier.
- ``BadgeEvent``      — append-only analytics event stream; partitioned by ``created_at``.

Partitioned tables intentionally do NOT use ``UUIDPrimaryKeyMixin`` (which would make
``id`` the sole PK); they mirror the ``audit_logs`` composite-PK pattern instead.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class BadgeClass(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Tenant-scoped badge template (Open Badges BadgeClass)."""

    __tablename__ = "badge_classes"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    criteria_narrative: Mapped[str | None] = mapped_column(Text, nullable=True)
    criteria_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    # list[str] of tags/skills
    tags: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="'[]'")
    # list[{"name": str, "url": str}] alignment to external frameworks
    alignment: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="'[]'")
    image_s3_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    # null => non-expiring; else assertion.expires_at = issued_at + validity_days
    validity_days: Mapped[int | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="active")
    directory_visible: Mapped[bool] = mapped_column(nullable=False, server_default="false")
    # Certificate template used when rendering this class's certificates (U4):
    # one of classic | modern | elegant | minimal.
    certificate_template: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="classic"
    )
    # Optional reference to an issuer-designed custom template (U5). When set,
    # it takes precedence over ``certificate_template``; when null, the built-in
    # path renders. ON DELETE SET NULL so archiving/removing a template cleanly
    # reverts affected classes to their built-in template.
    custom_template_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("certificate_templates.id", ondelete="SET NULL"),
        nullable=True,
    )


class BadgeAssertion(Base):
    """Issued badge instance (Open Badges Assertion), partitioned by issued_at.

    ``id`` equals the linked ``documents.id`` (credential_id) — a single public
    identifier used in hosted assertion URLs.
    """

    __tablename__ = "badge_assertions"

    # Composite PK (id, issued_at) required for RANGE partitioning by issued_at.
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, server_default=func.now(), nullable=False
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    badge_class_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("badge_classes.id"), nullable=False
    )
    beneficiary_id: Mapped[str] = mapped_column(String(512), nullable=False)
    # Hybrid link: assertion.id == documents.id (credential_id).
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="active")
    accepted: Mapped[bool] = mapped_column(nullable=False, server_default="true")
    hidden: Mapped[bool] = mapped_column(nullable=False, server_default="false")
    public: Mapped[bool] = mapped_column(nullable=False, server_default="false")
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revocation_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Recipient (student) photo for certificate rendering + public verification
    # (U4). S3 key; served via presigned URL. Shown publicly only when public.
    recipient_photo_s3_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class BadgeEvent(Base):
    """Append-only analytics event, partitioned by created_at.

    event_type: issued | accepted | published | shared | verified | viewed | revoked
    """

    __tablename__ = "badge_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, server_default=func.now(), nullable=False
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    badge_class_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    assertion_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    channel: Mapped[str | None] = mapped_column(String(32), nullable=True)


class BadgeAnalyticsDaily(Base, UUIDPrimaryKeyMixin):
    """Daily analytics rollup over ``badge_events`` (U3).

    One row per (tenant, day, badge_class_id). A row with ``badge_class_id IS
    NULL`` is the tenant-wide total for that day and equals the sum of the
    per-class rows for each metric (BR-A3). Upserted idempotently on the UNIQUE
    key, so re-running aggregation never double-counts (BR-A2).
    """

    __tablename__ = "badge_analytics_daily"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    day: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # null => tenant-wide aggregate row for the day.
    badge_class_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    issued_count: Mapped[int] = mapped_column(nullable=False, server_default="0")
    accepted_count: Mapped[int] = mapped_column(nullable=False, server_default="0")
    published_count: Mapped[int] = mapped_column(nullable=False, server_default="0")
    shared_count: Mapped[int] = mapped_column(nullable=False, server_default="0")
    verified_count: Mapped[int] = mapped_column(nullable=False, server_default="0")
    viewed_count: Mapped[int] = mapped_column(nullable=False, server_default="0")
    # {channel: count} accumulated for 'shared' events.
    channel_breakdown: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="'{}'")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
