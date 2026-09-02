"""
Tenant lifecycle service — onboarding, approval, suspension, deactivation.

Manages the full tenant lifecycle including:
- Creation with unique namespace/domain validation
- KMS key provisioning
- API client credential generation
- Status transitions with Redis cache invalidation

Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 13.4, 13.9
"""

from __future__ import annotations

import logging
import secrets
import string
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

import redis.asyncio as aioredis
from fastapi import Depends
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.redis import get_redis
from app.db.session import get_db
from app.middleware.tenant_context import cache_tenant_status
from app.models.tenant import ApiClient, Tenant, TenantEncryptionKey

logger = logging.getLogger(__name__)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Valid lifecycle transitions
_VALID_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"active"},
    "active": {"suspended", "deactivated"},
    "suspended": {"active", "deactivated"},
    "deactivated": set(),  # Terminal state (within retention period)
}


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TenantCredentials:
    """Credentials returned after tenant creation."""

    tenant_id: str
    namespace: str
    client_id: str
    client_secret: str  # Only returned once; stored as bcrypt hash


@dataclass(frozen=True, slots=True)
class RotatedCredentials:
    """Credentials returned after key rotation."""

    new_client_id: str
    new_client_secret: str
    grace_until: datetime


# ---------------------------------------------------------------------------
# TenantService
# ---------------------------------------------------------------------------


class TenantService:
    """Manages tenant lifecycle: create, approve, suspend, deactivate.

    All operations validate domain uniqueness across all lifecycle states
    and invalidate Redis tenant status cache on state changes.
    """

    def __init__(
        self,
        db: AsyncSession,
        redis: aioredis.Redis,
        settings: Settings,
    ) -> None:
        self.db = db
        self.redis = redis
        self.settings = settings

    # ------------------------------------------------------------------
    # Create (Req 1.1, 1.2, 1.3)
    # ------------------------------------------------------------------

    async def create_tenant(
        self,
        name: str,
        namespace: str,
        domain: str,
        contact_email: str,
    ) -> TenantCredentials:
        """Create a new tenant in 'pending' state with API credentials.

        Validates namespace and domain uniqueness across all lifecycle states.
        Provisions a placeholder KMS key ARN (real provisioning in production).

        Raises:
            TenantConflictError: If namespace or domain already exists.
        """
        # Check namespace uniqueness
        existing = await self.db.execute(
            select(Tenant).where(Tenant.namespace == namespace)
        )
        if existing.scalar_one_or_none() is not None:
            raise TenantConflictError(
                field="namespace",
                value=namespace,
                message=f"Namespace '{namespace}' is already in use.",
            )

        # Check domain uniqueness across all states (Req 1.3)
        existing_domain = await self.db.execute(
            select(Tenant).where(Tenant.domain == domain)
        )
        if existing_domain.scalar_one_or_none() is not None:
            raise TenantConflictError(
                field="domain",
                value=domain,
                message=f"Domain '{domain}' is already registered.",
            )

        # Create tenant record
        tenant = Tenant(
            namespace=namespace,
            name=name,
            domain=domain,
            contact_email=contact_email,
            status="pending",
        )
        self.db.add(tenant)
        await self.db.flush()  # Get tenant.id without committing

        # Provision encryption key (placeholder ARN for now)
        encryption_key = TenantEncryptionKey(
            tenant_id=tenant.id,
            kms_key_arn=f"arn:aws:kms:{self.settings.aws_region}:000000000000:key/{tenant.id}",
            status="active",
        )
        self.db.add(encryption_key)

        # Generate API client credentials
        client_id = f"{namespace}_{_generate_random_string(16)}"
        client_secret = _generate_random_string(48)
        client_secret_hash = pwd_context.hash(client_secret)

        api_client = ApiClient(
            tenant_id=tenant.id,
            client_id=client_id,
            client_secret_hash=client_secret_hash,
            status="active",
        )
        self.db.add(api_client)

        await self.db.commit()
        await self.db.refresh(tenant)

        # Cache tenant status
        await cache_tenant_status(str(tenant.id), "pending")

        logger.info("Tenant created: id=%s namespace=%s", tenant.id, namespace)

        return TenantCredentials(
            tenant_id=str(tenant.id),
            namespace=namespace,
            client_id=client_id,
            client_secret=client_secret,
        )

    # ------------------------------------------------------------------
    # Approve (Req 1.4)
    # ------------------------------------------------------------------

    async def approve_tenant(self, tenant_id: UUID) -> Tenant:
        """Transition a tenant from 'pending' to 'active'.

        Only Super_Admins can approve tenants.

        Raises:
            TenantNotFoundError: If tenant doesn't exist.
            TenantTransitionError: If transition is not valid.
        """
        tenant = await self._get_tenant(tenant_id)
        self._validate_transition(tenant, "active")

        tenant.status = "active"
        await self.db.commit()
        await self.db.refresh(tenant)

        await cache_tenant_status(
            str(tenant.id), "active", tenant.rate_limit_per_hour
        )

        logger.info("Tenant approved: id=%s namespace=%s", tenant.id, tenant.namespace)
        return tenant

    # ------------------------------------------------------------------
    # Suspend (Req 1.5)
    # ------------------------------------------------------------------

    async def suspend_tenant(self, tenant_id: UUID) -> Tenant:
        """Suspend a tenant — deny all API access within 10 seconds.

        Raises:
            TenantNotFoundError: If tenant doesn't exist.
            TenantTransitionError: If transition is not valid.
        """
        tenant = await self._get_tenant(tenant_id)
        self._validate_transition(tenant, "suspended")

        tenant.status = "suspended"
        await self.db.commit()
        await self.db.refresh(tenant)

        # Immediately invalidate cache so middleware blocks within seconds
        await cache_tenant_status(str(tenant.id), "suspended")

        logger.warning("Tenant suspended: id=%s namespace=%s", tenant.id, tenant.namespace)
        return tenant

    # ------------------------------------------------------------------
    # Deactivate (Req 1.6)
    # ------------------------------------------------------------------

    async def deactivate_tenant(self, tenant_id: UUID) -> Tenant:
        """Deactivate a tenant — read-only archive state.

        Data retained for configurable retention period before permanent deletion.

        Raises:
            TenantNotFoundError: If tenant doesn't exist.
            TenantTransitionError: If transition is not valid.
        """
        tenant = await self._get_tenant(tenant_id)
        self._validate_transition(tenant, "deactivated")

        tenant.status = "deactivated"
        await self.db.commit()
        await self.db.refresh(tenant)

        await cache_tenant_status(str(tenant.id), "deactivated")

        logger.warning("Tenant deactivated: id=%s namespace=%s", tenant.id, tenant.namespace)
        return tenant

    # ------------------------------------------------------------------
    # Reactivate (suspended -> active)
    # ------------------------------------------------------------------

    async def reactivate_tenant(self, tenant_id: UUID) -> Tenant:
        """Reactivate a suspended tenant.

        Raises:
            TenantNotFoundError: If tenant doesn't exist.
            TenantTransitionError: If transition is not valid.
        """
        tenant = await self._get_tenant(tenant_id)
        self._validate_transition(tenant, "active")

        tenant.status = "active"
        await self.db.commit()
        await self.db.refresh(tenant)

        await cache_tenant_status(
            str(tenant.id), "active", tenant.rate_limit_per_hour
        )

        logger.info("Tenant reactivated: id=%s namespace=%s", tenant.id, tenant.namespace)
        return tenant

    # ------------------------------------------------------------------
    # Configuration (Req 1.7, 1.8)
    # ------------------------------------------------------------------

    async def update_tenant_config(
        self,
        tenant_id: UUID,
        storage_quota_bytes: int | None = None,
        rate_limit_per_hour: int | None = None,
        retention_years: int | None = None,
    ) -> Tenant:
        """Update per-tenant quota and rate limit configuration.

        Args:
            storage_quota_bytes: Range 1 MB (1048576) to 10 TB (10995116277760).
            rate_limit_per_hour: Range 1 to 1,000,000.
            retention_years: Range 1 to 99.

        Raises:
            TenantNotFoundError: If tenant doesn't exist.
            ValueError: If values are out of allowed range.
        """
        tenant = await self._get_tenant(tenant_id)

        if storage_quota_bytes is not None:
            if not (1_048_576 <= storage_quota_bytes <= 10_995_116_277_760):
                raise ValueError(
                    "storage_quota_bytes must be between 1 MB and 10 TB"
                )
            tenant.storage_quota_bytes = storage_quota_bytes

        if rate_limit_per_hour is not None:
            if not (1 <= rate_limit_per_hour <= 1_000_000):
                raise ValueError(
                    "rate_limit_per_hour must be between 1 and 1,000,000"
                )
            tenant.rate_limit_per_hour = rate_limit_per_hour

        if retention_years is not None:
            if not (1 <= retention_years <= 99):
                raise ValueError("retention_years must be between 1 and 99")
            tenant.retention_years = retention_years

        await self.db.commit()
        await self.db.refresh(tenant)

        # Update rate limit in cache
        await cache_tenant_status(
            str(tenant.id), tenant.status, tenant.rate_limit_per_hour
        )

        return tenant

    # ------------------------------------------------------------------
    # API Key Rotation (Req 13.4, 13.9)
    # ------------------------------------------------------------------

    async def rotate_api_key(
        self,
        tenant_id: UUID,
        grace_hours: int = 24,
    ) -> RotatedCredentials:
        """Rotate API credentials with a grace period for the old key.

        During the grace period, both old and new keys are accepted.

        Args:
            grace_hours: Hours during which the old key remains valid.

        Raises:
            TenantNotFoundError: If tenant doesn't exist.
        """
        tenant = await self._get_tenant(tenant_id)

        # Find the current active API client
        result = await self.db.execute(
            select(ApiClient).where(
                ApiClient.tenant_id == tenant_id,
                ApiClient.status == "active",
            )
        )
        current_client = result.scalar_one_or_none()

        if current_client:
            # Move current key to grace period
            current_client.status = "grace_period"
            current_client.grace_until = datetime.now(UTC) + timedelta(
                hours=grace_hours
            )

        # Generate new credentials
        new_client_id = f"{tenant.namespace}_{_generate_random_string(16)}"
        new_client_secret = _generate_random_string(48)
        new_client_secret_hash = pwd_context.hash(new_client_secret)

        new_api_client = ApiClient(
            tenant_id=tenant_id,
            client_id=new_client_id,
            client_secret_hash=new_client_secret_hash,
            status="active",
        )
        self.db.add(new_api_client)

        grace_until = datetime.now(UTC) + timedelta(hours=grace_hours)
        await self.db.commit()

        logger.info(
            "API key rotated: tenant_id=%s new_client_id=%s grace_hours=%d",
            tenant_id,
            new_client_id,
            grace_hours,
        )

        return RotatedCredentials(
            new_client_id=new_client_id,
            new_client_secret=new_client_secret,
            grace_until=grace_until,
        )

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    async def get_tenant(self, tenant_id: UUID) -> Tenant:
        """Get a tenant by ID. Raises TenantNotFoundError if not found."""
        return await self._get_tenant(tenant_id)

    async def get_tenant_by_namespace(self, namespace: str) -> Tenant | None:
        """Get a tenant by namespace. Returns None if not found."""
        result = await self.db.execute(
            select(Tenant).where(Tenant.namespace == namespace)
        )
        return result.scalar_one_or_none()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get_tenant(self, tenant_id: UUID) -> Tenant:
        """Fetch tenant by ID or raise TenantNotFoundError."""
        result = await self.db.execute(
            select(Tenant).where(Tenant.id == tenant_id)
        )
        tenant = result.scalar_one_or_none()
        if tenant is None:
            raise TenantNotFoundError(tenant_id)
        return tenant

    def _validate_transition(self, tenant: Tenant, target_status: str) -> None:
        """Validate that a status transition is allowed."""
        allowed = _VALID_TRANSITIONS.get(tenant.status, set())
        if target_status not in allowed:
            raise TenantTransitionError(
                current=tenant.status,
                target=target_status,
                tenant_id=str(tenant.id),
            )


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class TenantNotFoundError(Exception):
    """Raised when a tenant ID does not exist."""

    def __init__(self, tenant_id: UUID) -> None:
        self.tenant_id = tenant_id
        super().__init__(f"Tenant not found: {tenant_id}")


class TenantConflictError(Exception):
    """Raised when namespace or domain conflicts with an existing tenant."""

    def __init__(self, field: str, value: str, message: str) -> None:
        self.field = field
        self.value = value
        super().__init__(message)


class TenantTransitionError(Exception):
    """Raised when an invalid status transition is attempted."""

    def __init__(self, current: str, target: str, tenant_id: str) -> None:
        self.current = current
        self.target = target
        self.tenant_id = tenant_id
        super().__init__(
            f"Invalid transition from '{current}' to '{target}' for tenant {tenant_id}"
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _generate_random_string(length: int) -> str:
    """Generate a URL-safe random string of the given length."""
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------


async def get_tenant_service(
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
) -> TenantService:
    """Provide a TenantService instance for route handlers."""
    return TenantService(db=db, redis=redis, settings=get_settings())
