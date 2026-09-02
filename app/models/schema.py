"""ORM models for DocumentSchema and SchemaVersion."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPrimaryKeyMixin


class DocumentSchema(Base, UUIDPrimaryKeyMixin):
    """Tenant-scoped document schema definition."""

    __tablename__ = "document_schemas"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="active")
    field_definitions: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="'[]'")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    versions: Mapped[list[SchemaVersion]] = relationship(back_populates="schema")


class SchemaVersion(Base, UUIDPrimaryKeyMixin):
    """Immutable snapshot of a schema at a given version."""

    __tablename__ = "schema_versions"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    schema_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_schemas.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    field_definitions: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="'[]'")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    schema: Mapped[DocumentSchema] = relationship(back_populates="versions")
