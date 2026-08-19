"""
ORM models for consent and data-principal rights (DPDP Act).

``ConsentRecord`` is append-only by convention: granting, withdrawing, or
changing scope writes a new row rather than mutating an existing one, so the
history of what was consented to *at the time of each processing activity*
remains reconstructable. A mutable consent row cannot answer "was this
disclosure authorised when it happened?", which is the question that matters in
a dispute.

The DPDP Act requires notice and purpose specification, so ``purpose`` and
``notice_version`` are not nullable — a consent record that cannot say what it
was for is not evidence of consent.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin


class ConsentRecord(Base, UUIDPrimaryKeyMixin):
    """One consent event for one data principal."""

    __tablename__ = "consent_records"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    # Not an FK: the data principal may exist only as a beneficiary identifier
    # on documents, without a user_accounts row.
    data_principal_id: Mapped[str] = mapped_column(String(512), nullable=False)
    # Optional narrowing to a single credential; NULL means tenant-wide.
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=True
    )

    purpose: Mapped[str] = mapped_column(String(128), nullable=False)
    # 'consent' or a lawful basis such as 'legitimate_use'. Recorded explicitly
    # because the obligations differ: consent can be withdrawn, statutory
    # processing cannot.
    legal_basis: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default="consent"
    )
    # granted | withdrawn | expired
    state: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="granted"
    )
    # Fields the principal agreed to disclose for this purpose.
    scope: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="'[]'")
    # Version of the notice shown, so we can prove what they were told.
    notice_version: Mapped[str] = mapped_column(String(32), nullable=False)

    granted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    withdrawn_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Evidence of how consent was collected.
    collected_via: Mapped[str | None] = mapped_column(String(64), nullable=True)
    evidence: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ErasureRequest(Base, UUIDPrimaryKeyMixin):
    """A data principal's request for erasure or correction.

    Tracked as a durable record rather than executed inline because erasure
    touches object storage, ledger-adjacent metadata, and backups, and because
    the platform must be able to show *when* a request arrived and how it was
    handled.
    """

    __tablename__ = "erasure_requests"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    data_principal_id: Mapped[str] = mapped_column(String(512), nullable=False)
    # erasure | correction | access
    request_type: Mapped[str] = mapped_column(String(32), nullable=False)
    # received | in_progress | completed | rejected
    state: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="received"
    )
    # Set when a statutory retention obligation blocks erasure; the principal is
    # entitled to know why rather than receiving a silent refusal.
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    outcome: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
