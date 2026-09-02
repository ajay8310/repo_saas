"""ORM models for Tenant, TenantEncryptionKey, and ApiClient."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPrimaryKeyMixin


class Tenant(Base, UUIDPrimaryKeyMixin):
    """Multi-tenant root entity — not tenant-scoped itself."""

    __tablename__ = "tenants"

    namespace: Mapped[str] = mapped_column(String(63), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    domain: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    contact_email: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="pending")
    storage_quota_bytes: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default="10737418240"
    )
    rate_limit_per_hour: Mapped[int] = mapped_column(Integer, nullable=False, server_default="10000")
    retention_years: Mapped[int] = mapped_column(Integer, nullable=False, server_default="7")
    dedicated_db: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    encryption_keys: Mapped[list[TenantEncryptionKey]] = relationship(back_populates="tenant")
    api_clients: Mapped[list[ApiClient]] = relationship(back_populates="tenant")


class TenantEncryptionKey(Base, UUIDPrimaryKeyMixin):
    """Per-tenant KMS key record."""

    __tablename__ = "tenant_encryption_keys"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    kms_key_arn: Mapped[str] = mapped_column(String(2048), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    tenant: Mapped[Tenant] = relationship(back_populates="encryption_keys")


class ApiClient(Base, UUIDPrimaryKeyMixin):
    """OAuth client credentials for tenant API access."""

    __tablename__ = "api_clients"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    client_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    client_secret_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="active")
    rotation_interval_days: Mapped[int] = mapped_column(Integer, nullable=False, server_default="90")
    key_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    grace_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    tenant: Mapped[Tenant] = relationship(back_populates="api_clients")
