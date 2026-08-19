"""ORM models for blockchain/ledger anchoring."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin


class AnchorBatch(Base, UUIDPrimaryKeyMixin):
    """A set of credential digests published under one Merkle root.

    Tenant-scoped: roots are never mixed across tenants, so one tenant's batch
    cannot be used to infer another's issuance volume.
    """

    __tablename__ = "anchor_batches"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    root_hex: Mapped[str] = mapped_column(String(64), nullable=False)
    leaf_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    # pending -> anchored, or failed after exhausting retries.
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="pending"
    )
    provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ledger_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    anchored_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    receipt: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class DocumentAnchor(Base, UUIDPrimaryKeyMixin):
    """Links one document to its batch, with the proof needed to verify it.

    The leaf digest and inclusion proof are stored rather than recomputed so a
    credential stays verifiable even after retention removes its sibling
    documents from the batch.
    """

    __tablename__ = "document_anchors"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("anchor_batches.id", ondelete="SET NULL"),
        nullable=True,
    )
    leaf_hex: Mapped[str] = mapped_column(String(64), nullable=False)
    leaf_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    proof: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
