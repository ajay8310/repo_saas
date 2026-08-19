"""ORM model for DigiLockerPush."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin


class DigiLockerPush(Base, UUIDPrimaryKeyMixin):
    """Tracks async push of a document to DigiLocker."""

    __tablename__ = "digilocker_pushes"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="pending")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # DigiLocker document type declared at publication. Stored per push rather
    # than derived at send time so a later config change cannot retroactively
    # alter what an authority published.
    doctype: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # The locker reference DigiLocker returns. Without it a "success" is not
    # provable, so the connector treats a missing URI as a failure.
    digilocker_uri: Mapped[str | None] = mapped_column(String(512), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # 'sandbox' or 'live'. Recorded so a simulated publication can never be
    # mistaken for a real one when auditing what reached citizens.
    delivery_mode: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
