"""
Authentication service — JWT issuance, OTP, MFA, and lockout.

Requirements: 8.2, 8.3, 4.5, 4.6, 13.3, 13.6, 13.8
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

import pyotp
import redis.asyncio as aioredis
from fastapi import Depends
from jose import jwt
from passlib.context import CryptContext
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.redis import get_redis
from app.db.session import get_db
from app.models.tenant import ApiClient, Tenant
from app.models.user import UserAccount

logger = logging.getLogger(__name__)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TokenResult:
    """Successful authentication result containing the issued JWT."""

    access_token: str
    expires_in: int


# ---------------------------------------------------------------------------
# Redis key prefixes
# ---------------------------------------------------------------------------

_OTP_PREFIX = "otp:"
_MFA_CHALLENGE_PREFIX = "mfa_challenge:"
_LOCKOUT_PREFIX = "lockout:"


# ---------------------------------------------------------------------------
# AuthService
# ---------------------------------------------------------------------------


class AuthService:
    """Handles all authentication flows: client credentials, OTP, MFA, lockout.

    Injected into route handlers via FastAPI's Depends().
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
    # JWT generation (shared)
    # ------------------------------------------------------------------

    def _issue_jwt(
        self,
        sub: str,
        tenant_id: UUID,
        roles: list[str],
        expires_in: int | None = None,
    ) -> TokenResult:
        """Create an RS256-signed JWT with standard claims (Req 8.2)."""
        exp_seconds = expires_in or self.settings.jwt_access_token_expire_seconds
        now = datetime.now(timezone.utc)
        claims = {
            "sub": sub,
            "tenant_id": str(tenant_id),
            "roles": roles,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(seconds=exp_seconds)).timestamp()),
        }
        token = jwt.encode(
            claims,
            self.settings.jwt_private_key,
            algorithm=self.settings.jwt_algorithm,
        )
        return TokenResult(access_token=token, expires_in=exp_seconds)

    # ------------------------------------------------------------------
    # 1. OAuth 2.0 Client Credentials (Req 8.2, 8.3)
    # ------------------------------------------------------------------

    async def authenticate_client(
        self, client_id: str, client_secret: str
    ) -> TokenResult | None:
        """Validate client credentials and issue a JWT.

        Returns None if credentials are invalid or the client is locked/revoked.
        """
        # Look up the API client (not tenant-scoped — uses client_id unique index)
        result = await self.db.execute(
            select(ApiClient).where(ApiClient.client_id == client_id)
        )
        api_client = result.scalar_one_or_none()

        if api_client is None:
            return None

        # Check status: active or within grace period
        if api_client.status == "revoked":
            return None
        if api_client.status == "grace_period":
            if api_client.grace_until and api_client.grace_until < datetime.now(timezone.utc):
                return None  # grace period expired

        # Verify the secret against the stored bcrypt hash
        if not pwd_context.verify(client_secret, api_client.client_secret_hash):
            return None

        # Look up the owning tenant to get namespace info
        tenant_result = await self.db.execute(
            select(Tenant).where(Tenant.id == api_client.tenant_id)
        )
        tenant = tenant_result.scalar_one_or_none()
        if tenant is None or tenant.status not in ("active", "pending"):
            return None

        return self._issue_jwt(
            sub=client_id,
            tenant_id=api_client.tenant_id,
            roles=["issuer"],  # API clients default to issuer role
        )

    # ------------------------------------------------------------------
    # 2. OTP Authentication for Beneficiaries (Req 4.5, 4.6)
    # ------------------------------------------------------------------

    async def send_otp(self, email: str, tenant_namespace: str) -> None:
        """Generate and store an OTP for beneficiary login.

        Always returns successfully to prevent user enumeration.
        In production, this would also send the OTP via email/SMS.
        """
        # Look up the user to confirm existence (but always succeed externally)
        result = await self.db.execute(
            select(UserAccount)
            .join(Tenant, Tenant.id == UserAccount.tenant_id)
            .where(
                UserAccount.email == email,
                Tenant.namespace == tenant_namespace,
                UserAccount.role == "beneficiary",
            )
        )
        user = result.scalar_one_or_none()

        if user is None:
            # Don't reveal whether the account exists — just return
            logger.info("OTP requested for non-existent account: %s", email)
            return

        # Check if account is locked
        if await self._is_locked(str(user.id)):
            logger.warning("OTP requested for locked account: %s", email)
            return

        # Generate OTP code
        code = "".join(
            [str(secrets.randbelow(10)) for _ in range(self.settings.otp_length)]
        )

        # Store bcrypt hash in Redis with TTL
        code_hash = pwd_context.hash(code)
        redis_key = f"{_OTP_PREFIX}{email}:{tenant_namespace}"
        await self.redis.set(redis_key, code_hash, ex=self.settings.otp_ttl_seconds)

        # In production: send OTP via notification service (email/SMS)
        # For now, log it in development mode only
        if self.settings.environment == "development":
            logger.debug("OTP for %s: %s (dev only)", email, code)

    async def verify_otp(
        self, email: str, code: str, tenant_namespace: str
    ) -> TokenResult | None:
        """Verify the OTP and issue a JWT if valid (Req 4.6).

        Returns None if OTP is invalid, expired, or already used.
        """
        # Look up the user
        result = await self.db.execute(
            select(UserAccount)
            .join(Tenant, Tenant.id == UserAccount.tenant_id)
            .where(
                UserAccount.email == email,
                Tenant.namespace == tenant_namespace,
                UserAccount.role == "beneficiary",
            )
        )
        user = result.scalar_one_or_none()

        if user is None:
            return None

        # Check lockout
        if await self._is_locked(str(user.id)):
            return None

        # Retrieve OTP hash from Redis
        redis_key = f"{_OTP_PREFIX}{email}:{tenant_namespace}"
        stored_hash = await self.redis.get(redis_key)

        if stored_hash is None:
            # OTP expired or never generated
            await self._record_failed_attempt(user)
            return None

        # Verify the code against the stored hash
        if not pwd_context.verify(code, stored_hash):
            await self._record_failed_attempt(user)
            return None

        # OTP is valid — delete it immediately (single-use, Req 4.6)
        await self.redis.delete(redis_key)

        # Reset failed attempts on success
        await self._reset_failed_attempts(user)

        return self._issue_jwt(
            sub=str(user.id),
            tenant_id=user.tenant_id,
            roles=[user.role],
        )

    # ------------------------------------------------------------------
    # 3. MFA / TOTP for Admin Accounts (Req 13.3)
    # ------------------------------------------------------------------

    async def initiate_mfa(self, user_id: str) -> None:
        """Initiate an MFA challenge for an admin account.

        Stores a challenge marker in Redis with a 5-minute TTL.
        The user must submit their TOTP code within this window.
        """
        result = await self.db.execute(
            select(UserAccount).where(UserAccount.id == user_id)
        )
        user = result.scalar_one_or_none()

        if user is None:
            # Don't reveal non-existence
            return

        if user.role not in ("super_admin", "tenant_admin"):
            logger.warning("MFA initiated for non-admin user: %s", user_id)
            return

        if not user.mfa_enabled or not user.mfa_secret:
            logger.warning("MFA not enrolled for user: %s", user_id)
            return

        # Store challenge marker with TTL
        challenge_key = f"{_MFA_CHALLENGE_PREFIX}{user_id}"
        timeout_seconds = self.settings.mfa_challenge_timeout_minutes * 60
        await self.redis.set(challenge_key, "pending", ex=timeout_seconds)

    async def verify_mfa(
        self, user_id: str, totp_code: str
    ) -> TokenResult | None:
        """Verify TOTP code and complete admin authentication (Req 13.3).

        Returns None if the code is invalid, expired, or the challenge window elapsed.
        """
        result = await self.db.execute(
            select(UserAccount).where(UserAccount.id == user_id)
        )
        user = result.scalar_one_or_none()

        if user is None:
            return None

        # Check lockout
        if await self._is_locked(str(user.id)):
            return None

        # Verify challenge was initiated within the timeout window
        challenge_key = f"{_MFA_CHALLENGE_PREFIX}{user_id}"
        challenge = await self.redis.get(challenge_key)
        if challenge is None:
            # Challenge expired or never initiated
            return None

        if not user.mfa_secret:
            return None

        # Verify the TOTP code
        totp = pyotp.TOTP(user.mfa_secret)
        if not totp.verify(totp_code, valid_window=1):
            # Invalid code — record MFA failure
            await self._record_mfa_failure(user)
            return None

        # MFA verified — clean up challenge marker and reset counters
        await self.redis.delete(challenge_key)
        await self._reset_failed_attempts(user)

        return self._issue_jwt(
            sub=str(user.id),
            tenant_id=user.tenant_id,
            roles=[user.role],
        )

    # ------------------------------------------------------------------
    # 4. Account Lockout Logic (Req 13.6, 13.8)
    # ------------------------------------------------------------------

    async def _is_locked(self, user_id: str) -> bool:
        """Check if the account is currently locked (via Redis cache)."""
        lockout_key = f"{_LOCKOUT_PREFIX}{user_id}"
        locked = await self.redis.get(lockout_key)
        return locked is not None

    async def _record_failed_attempt(self, user: UserAccount) -> None:
        """Increment failed auth attempts and lock if threshold reached (Req 13.6)."""
        user.failed_auth_attempts += 1

        if user.failed_auth_attempts >= self.settings.max_failed_auth_attempts:
            lockout_duration = timedelta(minutes=self.settings.auth_lockout_minutes)
            user.locked_until = datetime.now(timezone.utc) + lockout_duration

            # Set lockout in Redis for fast checking
            lockout_key = f"{_LOCKOUT_PREFIX}{user.id}"
            await self.redis.set(
                lockout_key, "locked", ex=self.settings.auth_lockout_minutes * 60
            )

            logger.warning(
                "Account locked: user_id=%s attempts=%d duration=%d min",
                user.id,
                user.failed_auth_attempts,
                self.settings.auth_lockout_minutes,
            )

        await self.db.commit()

    async def _record_mfa_failure(self, user: UserAccount) -> None:
        """Record a failed MFA attempt and lock admin if threshold reached (Req 13.8)."""
        user.failed_auth_attempts += 1

        if user.failed_auth_attempts >= self.settings.max_failed_mfa_attempts:
            lockout_duration = timedelta(minutes=self.settings.mfa_lockout_minutes)
            user.locked_until = datetime.now(timezone.utc) + lockout_duration

            # Set lockout in Redis
            lockout_key = f"{_LOCKOUT_PREFIX}{user.id}"
            await self.redis.set(
                lockout_key, "locked", ex=self.settings.mfa_lockout_minutes * 60
            )

            logger.warning(
                "Admin MFA lockout: user_id=%s attempts=%d duration=%d min",
                user.id,
                user.failed_auth_attempts,
                self.settings.mfa_lockout_minutes,
            )

        await self.db.commit()

    async def _reset_failed_attempts(self, user: UserAccount) -> None:
        """Reset failed attempt counter and clear lockout on successful auth."""
        if user.failed_auth_attempts > 0 or user.locked_until is not None:
            user.failed_auth_attempts = 0
            user.locked_until = None
            await self.db.commit()

        # Clear Redis lockout cache
        lockout_key = f"{_LOCKOUT_PREFIX}{user.id}"
        await self.redis.delete(lockout_key)


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------


async def get_auth_service(
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
) -> AuthService:
    """Provide an AuthService instance for route handlers."""
    return AuthService(db=db, redis=redis, settings=get_settings())
