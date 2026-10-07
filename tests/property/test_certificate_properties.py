"""
Property tests for U4 Certificates & Issuer Signing.

Properties (PBT-07):
* Every built-in template always produces a valid PDF (starts with %PDF) for
  arbitrary content, with or without embedded images.
* An issuer-signed JWS always verifies with the matching public key and never
  with a foreign public key, over arbitrary payloads (Q7).
"""

from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("S3_BUCKET_NAME", "test-bucket")
os.environ.setdefault("JWT_PRIVATE_KEY", "-----BEGIN RSA PRIVATE KEY-----\nX\n-----END RSA PRIVATE KEY-----")
os.environ.setdefault("JWT_PUBLIC_KEY", "-----BEGIN PUBLIC KEY-----\nX\n-----END PUBLIC KEY-----")

from app.config import get_settings

get_settings.cache_clear()

import pytest
from hypothesis import given
from hypothesis import settings as h_settings
from hypothesis import strategies as st
from jose import jwt
from jose.exceptions import JWTError

from app.services.certificate_renderer import CertificateContext, render_certificate
from app.services.issuer_signing_service import _generate_rsa_pem
from tests.property.strategies import (
    badge_names,
    certificate_templates,
    recipient_identities,
    signing_payloads,
)

# Generate the (expensive) RSA keypairs once; property examples reuse them.
_PRIV, _PUB = _generate_rsa_pem()
_, _OTHER_PUB = _generate_rsa_pem()


class TestTemplatePdfProperty:
    @given(
        template=certificate_templates,
        badge=badge_names,
        recipient=recipient_identities,
        revoked=st.booleans(),
    )
    @h_settings(max_examples=60, deadline=None)
    def test_every_template_emits_valid_pdf(
        self, template: str, badge: str, recipient: str, revoked: bool
    ) -> None:
        ctx = CertificateContext(
            assertion_id="a1",
            badge_name=badge,
            recipient_display=recipient[:40],
            issuer_name="Issuer",
            issued_at="2026-01-01T00:00:00+00:00",
            expires_at=None,
            criteria=None,
            verify_url="https://example.test/verify/a1",
            signature_jws="eyJ.payload.sig",
            status="revoked" if revoked else "active",
            revoked_at="2026-02-01" if revoked else None,
        )
        pdf = render_certificate(ctx, template)
        assert pdf[:5] == b"%PDF-"


class TestIssuerSignatureProperty:
    @given(payload=signing_payloads)
    @h_settings(max_examples=60, deadline=None)
    def test_signature_verifies_with_own_key(self, payload: dict) -> None:
        token = jwt.encode(payload, _PRIV, algorithm="RS256")
        decoded = jwt.decode(token, _PUB, algorithms=["RS256"])
        # Every key in the payload round-trips.
        for k, v in payload.items():
            assert decoded[k] == v

    @given(payload=signing_payloads)
    @h_settings(max_examples=40, deadline=None)
    def test_signature_rejected_by_foreign_key(self, payload: dict) -> None:
        token = jwt.encode(payload, _PRIV, algorithm="RS256")
        with pytest.raises(JWTError):
            jwt.decode(token, _OTHER_PUB, algorithms=["RS256"])
