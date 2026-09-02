"""ORM model for NotificationPreference."""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin


class NotificationPreference(Base, UUIDPrimaryKeyMixin):
    """Beneficiary notification preference per tenant."""

    __tablename__ = "notification_preferences"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    beneficiary_id: Mapped[str] = mapped_column(String(512), nullable=False)
    notify_on_issuance: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    notify_on_revocation: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    notify_on_verification: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    preferred_channel: Mapped[str] = mapped_column(String(16), nullable=False, server_default="email")
    contact_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
