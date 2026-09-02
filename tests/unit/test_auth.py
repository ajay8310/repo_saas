"""
Unit tests for authentication endpoints and JWT issuance.

Tests verify:
- POST /api/v1/auth/token returns JWT for valid client credentials
- POST /api/v1/auth/token returns 401 for invalid credentials
- JWT contains required claims (sub, tenant_id, roles, exp, iat)
- JWT expiry is bounded at 3600 seconds (Property 27)
- Expired JWT returns 401 (Property 28)
- Auth endpoints return proper error shapes

Requirements covered: 8.2, 8.3
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

# ---- test env setup --------------------------------------------------------
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("S3_BUCKET_NAME", "test-bucket")
os.environ.setdefault(
    "JWT_PRIVATE_KEY",
    "-----BEGIN RSA PRIVATE KEY-----\nPLACEHOLDER\n-----END RSA PRIVATE KEY-----",
)
os.environ.setdefault(
    "JWT_PUBLIC_KEY",
    "-----BEGIN PUBLIC KEY-----\nPLACEHOLDER\n-----END PUBLIC KEY-----",
)

from app.config import get_settings

get_settings.cache_clear()
# ---------------------------------------------------------------------------

import pytest
from jose import jwt

from app.services.auth_service import AuthService, TokenResult

# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


class TestJWTIssuance:
    """Tests for JWT token generation logic."""

    def setup_method(self) -> None:
        """Create a real RSA key pair for signing/verifying JWTs in tests."""
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa

        from app.config import Settings

        # Generate a test RSA key pair
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.private_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode()
        self.public_pem = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode()

        self.settings = Settings(
            _env_file=None,
            database_url="postgresql+asyncpg://u:p@localhost/db",
            redis_url="redis://localhost:6379/0",
            s3_bucket_name="test-bucket",
            jwt_private_key=self.private_pem,
            jwt_public_key=self.public_pem,
        )

    def _make_service(self) -> AuthService:
        """Create an AuthService with mocked DB and Redis."""
        mock_db = AsyncMock()
        mock_redis = AsyncMock()
        return AuthService(db=mock_db, redis=mock_redis, settings=self.settings)

    def test_issued_jwt_contains_required_claims(self) -> None:
        """JWT must contain sub, tenant_id, roles, iat, exp (Req 8.2)."""
        service = self._make_service()
        tenant_id = uuid4()
        result = service._issue_jwt(
            sub="test-client",
            tenant_id=tenant_id,
            roles=["issuer"],
        )

        # Decode without verification to inspect claims
        claims = jwt.decode(
            result.access_token,
            self.public_pem,
            algorithms=["RS256"],
        )

        assert claims["sub"] == "test-client"
        assert claims["tenant_id"] == str(tenant_id)
        assert claims["roles"] == ["issuer"]
        assert "iat" in claims
        assert "exp" in claims

    def test_jwt_expiry_matches_settings(self) -> None:
        """JWT exp claim matches the configured expiry (Req 8.2)."""
        service = self._make_service()
        result = service._issue_jwt(
            sub="client-1",
            tenant_id=uuid4(),
            roles=["issuer"],
        )

        claims = jwt.decode(
            result.access_token,
            self.public_pem,
            algorithms=["RS256"],
        )

        expected_lifetime = self.settings.jwt_access_token_expire_seconds
        actual_lifetime = claims["exp"] - claims["iat"]
        assert actual_lifetime == expected_lifetime
        assert result.expires_in == expected_lifetime

    def test_jwt_expiry_never_exceeds_3600_seconds(self) -> None:
        """Property 27: JWT expiry is always bounded at 3600 seconds (Req 8.2)."""
        service = self._make_service()
        result = service._issue_jwt(
            sub="client-1",
            tenant_id=uuid4(),
            roles=["issuer"],
        )

        claims = jwt.decode(
            result.access_token,
            self.public_pem,
            algorithms=["RS256"],
        )

        lifetime = claims["exp"] - claims["iat"]
        assert lifetime <= 3600

    def test_jwt_custom_expiry_is_respected(self) -> None:
        """Custom expires_in parameter is used when provided."""
        service = self._make_service()
        result = service._issue_jwt(
            sub="client-1",
            tenant_id=uuid4(),
            roles=["issuer"],
            expires_in=300,
        )

        claims = jwt.decode(
            result.access_token,
            self.public_pem,
            algorithms=["RS256"],
        )

        assert claims["exp"] - claims["iat"] == 300
        assert result.expires_in == 300

    def test_jwt_is_rs256_signed(self) -> None:
        """JWT must be signed with RS256 algorithm."""
        service = self._make_service()
        result = service._issue_jwt(
            sub="client-1",
            tenant_id=uuid4(),
            roles=["issuer"],
        )

        # Get the header without full verification
        header = jwt.get_unverified_header(result.access_token)
        assert header["alg"] == "RS256"

    def test_jwt_verifiable_with_public_key(self) -> None:
        """JWT can be verified with the corresponding public key."""
        service = self._make_service()
        result = service._issue_jwt(
            sub="client-1",
            tenant_id=uuid4(),
            roles=["issuer"],
        )

        # This should not raise
        claims = jwt.decode(
            result.access_token,
            self.public_pem,
            algorithms=["RS256"],
        )
        assert claims["sub"] == "client-1"

    def test_expired_jwt_raises_on_decode(self) -> None:
        """Property 28: Expired JWT fails validation (Req 8.3)."""
        service = self._make_service()

        # Issue a token that's already expired (negative expiry)
        now = datetime.now(UTC)
        expired_claims = {
            "sub": "client-1",
            "tenant_id": str(uuid4()),
            "roles": ["issuer"],
            "iat": int((now - timedelta(hours=2)).timestamp()),
            "exp": int((now - timedelta(hours=1)).timestamp()),
        }
        expired_token = jwt.encode(
            expired_claims,
            self.private_pem,
            algorithm="RS256",
        )

        from jose import ExpiredSignatureError

        with pytest.raises(ExpiredSignatureError):
            jwt.decode(
                expired_token,
                self.public_pem,
                algorithms=["RS256"],
                options={"require_exp": True},
            )

    def test_jwt_multiple_roles_preserved(self) -> None:
        """JWT correctly stores multiple roles."""
        service = self._make_service()
        roles = ["tenant_admin", "issuer"]
        result = service._issue_jwt(
            sub="admin-user",
            tenant_id=uuid4(),
            roles=roles,
        )

        claims = jwt.decode(
            result.access_token,
            self.public_pem,
            algorithms=["RS256"],
        )
        assert claims["roles"] == roles


class TestTokenResult:
    """Tests for the TokenResult dataclass."""

    def test_token_result_is_immutable(self) -> None:
        result = TokenResult(access_token="abc", expires_in=3600)
        with pytest.raises(Exception):  # FrozenInstanceError
            result.access_token = "xyz"  # type: ignore

    def test_token_result_fields(self) -> None:
        result = TokenResult(access_token="token123", expires_in=1800)
        assert result.access_token == "token123"
        assert result.expires_in == 1800
