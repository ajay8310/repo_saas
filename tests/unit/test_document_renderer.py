"""
Unit tests for document rendering (signed PDF + JSON-LD with QR code).

Uses a real RSA keypair so the RS256 proof path is genuinely exercised and
verifiable, rather than mocked.

Requirements covered: 4.7 (downloadable credential with credential ID + QR).
"""

from __future__ import annotations

import json
import os

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

# ---- Generate a real keypair BEFORE Settings is first resolved ----
_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PRIV = _key.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption(),
).decode()
_PUB = _key.public_key().public_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PublicFormat.SubjectPublicKeyInfo,
).decode()

os.environ["DATABASE_URL"] = "postgresql+asyncpg://test:test@localhost:5432/test"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["S3_BUCKET_NAME"] = "test-bucket"
os.environ["JWT_PRIVATE_KEY"] = _PRIV
os.environ["JWT_PUBLIC_KEY"] = _PUB
os.environ["VERIFICATION_BASE_URL"] = "https://verify.example.gov"

from app.config import get_settings

get_settings.cache_clear()

import pytest  # noqa: E402
from jose import jwt  # noqa: E402

from app.services.document_renderer import (  # noqa: E402
    RenderContext,
    build_verification_url,
    generate_qr_png,
    render_json_ld,
    render_pdf,
    sign_payload,
)


@pytest.fixture(autouse=True)
def _real_signing_keys(monkeypatch):
    """Guarantee this module's real RSA keys are the ones Settings serves.

    ``app/db/session.py`` resolves Settings at import time, so the lru_cache can
    already hold another test module's placeholder keys by the time these tests
    run. Re-asserting the env and clearing the cache per test makes the suite
    order-independent, and clearing again on teardown avoids leaking our keys
    into other modules.
    """
    monkeypatch.setenv("JWT_PRIVATE_KEY", _PRIV)
    monkeypatch.setenv("JWT_PUBLIC_KEY", _PUB)
    monkeypatch.setenv("VERIFICATION_BASE_URL", "https://verify.example.gov")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


CREDENTIAL_ID = "11111111-2222-3333-4444-555555555555"


def _ctx(**overrides) -> RenderContext:
    base = dict(
        credential_id=CREDENTIAL_ID,
        issuer_name="State Education Board",
        schema_name="B.Tech Degree Certificate",
        schema_version=3,
        beneficiary_id="john.doe@email.com",
        issued_at="2025-06-01T10:00:00+00:00",
        status="stored",
        fields={"student_name": "John Doe", "graduation_year": 2025, "grade": "A"},
    )
    base.update(overrides)
    return RenderContext(**base)


class TestVerificationUrl:
    def test_url_uses_configured_base(self) -> None:
        url = build_verification_url(CREDENTIAL_ID)
        assert url == f"https://verify.example.gov/verify/{CREDENTIAL_ID}"

    def test_trailing_slash_in_base_is_not_duplicated(self) -> None:
        # rstrip("/") in the implementation guards against a doubled slash.
        assert "//verify" not in build_verification_url(CREDENTIAL_ID).replace(
            "https://", ""
        )


class TestQrCode:
    def test_returns_png_magic_bytes(self) -> None:
        png = generate_qr_png("https://example.com/verify/abc")
        assert png.startswith(b"\x89PNG\r\n\x1a\n")

    def test_longer_payload_still_encodes(self) -> None:
        png = generate_qr_png("https://example.com/verify/" + "x" * 300)
        assert png.startswith(b"\x89PNG\r\n\x1a\n")
        assert len(png) > 100


class TestProofSigning:
    def test_proof_is_verifiable_with_public_key(self) -> None:
        payload = {"credential_id": CREDENTIAL_ID, "issuer": "Test"}
        jws = sign_payload(payload)
        decoded = jwt.decode(jws, _PUB, algorithms=["RS256"])
        assert decoded["credential_id"] == CREDENTIAL_ID

    def test_proof_header_is_rs256(self) -> None:
        jws = sign_payload({"credential_id": CREDENTIAL_ID})
        assert jwt.get_unverified_header(jws)["alg"] == "RS256"


class TestPdfRendering:
    def test_output_is_a_valid_pdf(self) -> None:
        pdf = render_pdf(_ctx())
        assert pdf.startswith(b"%PDF-")
        assert b"%%EOF" in pdf

    def test_pdf_is_non_trivial_in_size(self) -> None:
        """A real page with an embedded QR image is comfortably over 2 KB."""
        assert len(render_pdf(_ctx())) > 2000

    def test_revoked_pdf_differs_from_valid_pdf(self) -> None:
        valid = render_pdf(_ctx())
        revoked = render_pdf(
            _ctx(
                status="revoked",
                revoked_at="2025-07-15T09:00:00+00:00",
                revocation_reason="Issued in error",
            )
        )
        assert valid != revoked
        assert revoked.startswith(b"%PDF-")

    def test_renders_with_no_fields(self) -> None:
        """Empty field set must not break layout (undisclosed-fields case)."""
        pdf = render_pdf(_ctx(fields={}))
        assert pdf.startswith(b"%PDF-")

    def test_renders_with_many_fields_without_error(self) -> None:
        many = {f"field_{i}": f"value_{i}" for i in range(40)}
        pdf = render_pdf(_ctx(fields=many))
        assert pdf.startswith(b"%PDF-")


class TestJsonLdRendering:
    def test_has_required_vc_structure(self) -> None:
        doc = json.loads(render_json_ld(_ctx()))
        assert "https://www.w3.org/2018/credentials/v1" in doc["@context"]
        assert doc["id"] == f"urn:credential:{CREDENTIAL_ID}"
        assert "VerifiableCredential" in doc["type"]

    def test_credential_id_is_present(self) -> None:
        """Req 4.7 — the credential ID must be embedded in the output."""
        doc = json.loads(render_json_ld(_ctx()))
        assert CREDENTIAL_ID in doc["id"]

    def test_subject_carries_beneficiary_and_fields(self) -> None:
        doc = json.loads(render_json_ld(_ctx()))
        subject = doc["credentialSubject"]
        assert subject["id"] == "john.doe@email.com"
        assert subject["student_name"] == "John Doe"
        assert subject["grade"] == "A"

    def test_verification_url_is_embedded(self) -> None:
        doc = json.loads(render_json_ld(_ctx()))
        assert doc["credentialStatus"]["verificationUrl"].endswith(
            f"/verify/{CREDENTIAL_ID}"
        )

    def test_proof_block_is_verifiable(self) -> None:
        doc = json.loads(render_json_ld(_ctx()))
        proof = doc["proof"]
        assert proof["type"] == "JsonWebSignature2020"
        assert proof["proofPurpose"] == "assertionMethod"

        decoded = jwt.decode(proof["jws"], _PUB, algorithms=["RS256"])
        assert decoded["credential_id"] == CREDENTIAL_ID
        assert decoded["fields"]["student_name"] == "John Doe"

    def test_tampering_with_subject_does_not_change_proof(self) -> None:
        """The proof covers the payload, so it stays verifiable independently."""
        doc = json.loads(render_json_ld(_ctx()))
        doc["credentialSubject"]["student_name"] = "Someone Else"

        # Proof still decodes to the ORIGINAL value, exposing the tampering.
        decoded = jwt.decode(doc["proof"]["jws"], _PUB, algorithms=["RS256"])
        assert decoded["fields"]["student_name"] == "John Doe"

    def test_revoked_status_included(self) -> None:
        doc = json.loads(
            render_json_ld(
                _ctx(
                    status="revoked",
                    revoked_at="2025-07-15T09:00:00+00:00",
                    revocation_reason="Issued in error",
                )
            )
        )
        status = doc["credentialStatus"]
        assert status["status"] == "revoked"
        assert status["revokedAt"] == "2025-07-15T09:00:00+00:00"
        assert status["revocationReason"] == "Issued in error"

    def test_valid_credential_has_no_revocation_keys(self) -> None:
        doc = json.loads(render_json_ld(_ctx()))
        assert doc["credentialStatus"]["status"] == "stored"
        assert "revokedAt" not in doc["credentialStatus"]

    def test_output_is_valid_utf8_json_bytes(self) -> None:
        raw = render_json_ld(_ctx())
        assert isinstance(raw, bytes)
        json.loads(raw.decode("utf-8"))
