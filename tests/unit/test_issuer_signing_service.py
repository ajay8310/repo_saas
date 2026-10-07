"""
Unit tests for app.services.issuer_signing_service (U4, Q7).

Requirements covered: per-tenant RS256 keypair generation + sign/verify with the
published public key. The DB-bound methods (ensure_keypair, sign) are covered by
integration later; here we test the cryptographic core: a generated keypair
produces a JWS that verifies with its own public key and fails with a foreign
key.
"""

from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("S3_BUCKET_NAME", "test-bucket")
os.environ.setdefault("JWT_PRIVATE_KEY", "-----BEGIN RSA PRIVATE KEY-----\nX\n-----END RSA PRIVATE KEY-----")
os.environ.setdefault("JWT_PUBLIC_KEY", "-----BEGIN PUBLIC KEY-----\nX\n-----END PUBLIC KEY-----")

import pytest
from jose import jwt

from app.services.issuer_signing_service import _generate_rsa_pem


class TestKeypairGeneration:
    def test_generates_distinct_pem_keypair(self) -> None:
        priv, pub = _generate_rsa_pem()
        assert "PRIVATE KEY" in priv
        assert "PUBLIC KEY" in pub
        # Two generations differ.
        priv2, _ = _generate_rsa_pem()
        assert priv != priv2


class TestSignVerifyRoundTrip:
    def test_jws_verifies_with_own_public_key(self) -> None:
        priv, pub = _generate_rsa_pem()
        payload = {"assertion_id": "a1", "issuer": "Acme"}
        token = jwt.encode(payload, priv, algorithm="RS256")
        decoded = jwt.decode(token, pub, algorithms=["RS256"])
        assert decoded["assertion_id"] == "a1"
        assert decoded["issuer"] == "Acme"

    def test_foreign_public_key_rejects(self) -> None:
        priv, _ = _generate_rsa_pem()
        _, other_pub = _generate_rsa_pem()
        token = jwt.encode({"x": 1}, priv, algorithm="RS256")
        from jose.exceptions import JWTError

        with pytest.raises(JWTError):
            jwt.decode(token, other_pub, algorithms=["RS256"])
