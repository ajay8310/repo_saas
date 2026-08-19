"""ORM models for Webhook and WebhookEvent."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPrimaryKeyMixin


class Webhook(Base, UUIDPrimaryKeyMixin):
    """Tenant-scoped webhook registration."""

    __tablename__ = "webhooks"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    # Non-reversible fingerprint, kept for audit and equality checks only.
    secret_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    # Vault envelope holding the actual signing secret.  HMAC signatures must be
    # computed over the secret the receiver holds, which a hash cannot provide.
    secret_sealed: Mapped[str | None] = mapped_column(String, nullable=True)
    event_types: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="'[]'")
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    events: Mapped[list["WebhookEvent"]] = relationship(back_populates="webhook")


class WebhookEvent(Base, UUIDPrimaryKeyMixin):
    """Delivery record for a webhook event."""

    __tablename__ = "webhook_events"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    webhook_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("webhooks.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="'{}'")
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="pending")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    webhook: Mapped["Webhook"] = relationship(back_populates="events")
