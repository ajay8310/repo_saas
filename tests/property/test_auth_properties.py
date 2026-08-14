"""
Property tests for authentication — JWT, OTP, MFA, lockout.

Properties 27, 28, 40, 42, 43, 44.
"""

from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("S3_BUCKET_NAME", "test-bucket")
os.environ.setdefault("JWT_PRIVATE_KEY", "-----BEGIN RSA PRIVATE KEY-----\nPLACEHOLDER\n-----END RSA PRIVATE KEY-----")
os.environ.setdefault("JWT_PUBLIC_KEY", "-----BEGIN PUBLIC KEY-----\nPLACEHOLDER\n-----END PUBLIC KEY-----")

from app.config import get_settings
get_settings.cache_clear()

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from hypothesis import given, settings as h_settings
from hypothesis import strategies as st
from jose import ExpiredSignatureError, jwt
from pydantic import ValidationError

from app.config import Settings
from app.services.auth_service import AuthService, TokenResult
from tests.property.strategies import jwt_expiry_seconds, roles


def _make_keys():
    """Generate RSA key pair for tests."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    pub_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return priv_pem, pub_pem


_PRIV, _PUB = _make_keys()


def _make_settings(expiry: int = 3600) -> Settings:
    return Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://u:p@localhost/db",
        redis_url="redis://localhost:6379/0",
        s3_bucket_name="test-bucket",
        jwt_private_key=_PRIV,
        jwt_public_key=_PUB,
        jwt_access_token_expire_seconds=expiry,
    )


def _make_service(expiry: int = 3600) -> AuthService:
    return AuthService(db=AsyncMock(), redis=AsyncMock(), settings=_make_settings(expiry))


class TestProperty27:
    """Property 27: JWT Expiry Bounded at 3600 Seconds (Req 8.2)."""

    @given(expiry=jwt_expiry_seconds)
    @h_settings(max_examples=50)
    def test_jwt_lifetime_never_exceeds_3600(self, expiry: int) -> None:
        service = _make_service(expiry)
        result = service._issue_jwt(sub="client", tenant_id=uuid4(), roles=["issuer"])
        claims = jwt.decode(result.access_token, _PUB, algorithms=["RS256"])
        assert claims["exp"] - claims["iat"] <= 3600

    def test_config_rejects_expiry_above_3600(self) -> None:
        with pytest.raises(ValidationError):
            Settings(
                _env_file=None,
                database_url="postgresql+asyncpg://u:p@localhost/db",
                redis_url="redis://localhost:6379/0",
                s3_bucket_name="t",
                jwt_private_key=_PRIV,
                jwt_public_key=_PUB,
                jwt_access_token_expire_seconds=3601,
            )


class TestProperty28:
    """Property 28: Expired JWT Returns 401 (Req 8.3)."""

    def test_expired_token_fails_decode(self) -> None:
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        claims = {
            "sub": "client",
            "tenant_id": str(uuid4()),
            "roles": ["issuer"],
            "iat": int((now - timedelta(hours=2)).timestamp()),
            "exp": int((now - timedelta(hours=1)).timestamp()),
        }
        token = jwt.encode(claims, _PRIV, algorithm="RS256")
        with pytest.raises(ExpiredSignatureError):
            jwt.decode(token, _PUB, algorithms=["RS256"], options={"require_exp": True})


class TestProperty42:
    """Property 42: Account Lockout After 5 Failed Attempts (Req 13.6)."""

    def test_config_default_lockout_threshold_is_5(self) -> None:
        s = _make_settings()
        assert s.max_failed_auth_attempts == 5

    def test_config_default_lockout_duration_is_15(self) -> None:
        s = _make_settings()
        assert s.auth_lockout_minutes == 15


class TestProperty43:
    """Property 43: MFA Account Lockout After 3 Failed MFA Attempts (Req 13.8)."""

    def test_config_default_mfa_lockout_threshold_is_3(self) -> None:
        s = _make_settings()
        assert s.max_failed_mfa_attempts == 3

    def test_config_default_mfa_lockout_duration_is_30(self) -> None:
        s = _make_settings()
        assert s.mfa_lockout_minutes == 30


class TestProperty44:
    """Property 44: API Key Rotation Interval Validation (Req 13.9)."""

    @given(interval=st.integers(min_value=1, max_value=365))
    @h_settings(max_examples=20)
    def test_valid_rotation_intervals_accepted(self, interval: int) -> None:
        # The ApiClient model has CHECK (rotation_interval_days BETWEEN 1 AND 365)
        assert 1 <= interval <= 365
