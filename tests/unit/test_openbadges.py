"""
Unit tests for app.services.openbadges — Open Badges 2.0 serialization.

Requirements covered: FR-4 (assertion), FR-13/S13 (hosted verification),
Q3=A (revocation semantics), Q2=C (expiry), Q5=A (hashed recipient identity).
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("S3_BUCKET_NAME", "test-bucket")
os.environ.setdefault("JWT_PRIVATE_KEY", "-----BEGIN RSA PRIVATE KEY-----\nX\n-----END RSA PRIVATE KEY-----")
os.environ.setdefault("JWT_PUBLIC_KEY", "-----BEGIN PUBLIC KEY-----\nX\n-----END PUBLIC KEY-----")


from app.services.openbadges import (
    AssertionData,
    BadgeClassData,
    IssuerProfile,
    OpenBadgesSerializer,
    hash_identity,
)

_ISSUER = IssuerProfile(
    id_url="https://example.test/issuers/t1",
    name="Acme Institute",
    url="https://acme.test",
    email="badges@acme.test",
)

_BADGE = BadgeClassData(
    id_url="https://example.test/classes/c1",
    name="Python Expert",
    description="Awarded for Python mastery.",
    image_url="https://example.test/img.png",
    criteria_narrative="Complete the assessment.",
    criteria_url="https://acme.test/criteria",
    issuer=_ISSUER,
    tags=["python", "backend"],
    alignment=[{"targetName": "PY-1", "targetUrl": "https://acme.test/py1"}],
)


def _assertion(**overrides) -> AssertionData:
    base = dict(
        id_url="https://example.test/assertions/a1",
        recipient_identity="learner@example.test",
        recipient_salt="deadbeef",
        issued_on=datetime(2026, 1, 1, tzinfo=UTC),
        verify_url="https://example.test/assertions/a1",
        badge_class=_BADGE,
    )
    base.update(overrides)
    return AssertionData(**base)


class TestHashIdentity:
    """Q5=A: recipient identity is hashed with salt, never emitted raw."""

    def test_hash_is_prefixed_sha256(self) -> None:
        h = hash_identity("learner@example.test", "deadbeef")
        assert h.startswith("sha256$")
        assert len(h) == len("sha256$") + 64  # hex digest length

    def test_hash_is_salt_dependent(self) -> None:
        a = hash_identity("learner@example.test", "salt1")
        b = hash_identity("learner@example.test", "salt2")
        assert a != b

    def test_hash_is_deterministic(self) -> None:
        a = hash_identity("learner@example.test", "salt1")
        b = hash_identity("learner@example.test", "salt1")
        assert a == b


class TestIssuer:
    def test_issuer_shape(self) -> None:
        doc = OpenBadgesSerializer().issuer(_ISSUER)
        assert doc["type"] == "Issuer"
        assert doc["id"] == _ISSUER.id_url
        assert doc["name"] == "Acme Institute"
        assert doc["url"] == "https://acme.test"
        assert doc["email"] == "badges@acme.test"
        assert doc["@context"] == "https://w3id.org/openbadges/v2"


class TestBadgeClass:
    def test_badge_class_shape(self) -> None:
        doc = OpenBadgesSerializer().badge_class(_BADGE)
        assert doc["type"] == "BadgeClass"
        assert doc["name"] == "Python Expert"
        assert doc["issuer"]["type"] == "Issuer"
        assert doc["criteria"]["id"] == "https://acme.test/criteria"
        assert doc["criteria"]["narrative"] == "Complete the assessment."
        assert doc["tags"] == ["python", "backend"]


class TestAssertion:
    def test_recipient_is_hashed_never_raw(self) -> None:
        doc = OpenBadgesSerializer().assertion(_assertion())
        recipient = doc["recipient"]
        assert recipient["hashed"] is True
        assert recipient["salt"] == "deadbeef"
        assert recipient["identity"].startswith("sha256$")
        # The raw email must not appear anywhere in the recipient object.
        assert "learner@example.test" not in str(recipient)

    def test_verification_is_hosted(self) -> None:
        doc = OpenBadgesSerializer().assertion(_assertion())
        assert doc["verification"] == {"type": "HostedBadge"}

    def test_expiry_emitted_only_when_set(self) -> None:
        ser = OpenBadgesSerializer()
        non_expiring = ser.assertion(_assertion(expires=None))
        assert "expires" not in non_expiring

        expiry = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=365)
        expiring = ser.assertion(_assertion(expires=expiry))
        assert "expires" in expiring

    def test_revoked_assertion_reports_revoked(self) -> None:
        doc = OpenBadgesSerializer().assertion(
            _assertion(revoked=True, revocation_reason="issued in error")
        )
        assert doc["revoked"] is True
        assert doc["revocationReason"] == "issued in error"

    def test_active_assertion_has_no_revoked_flag(self) -> None:
        doc = OpenBadgesSerializer().assertion(_assertion(revoked=False))
        assert "revoked" not in doc


class TestParseRoundTrip:
    def test_parse_extracts_identifiers(self) -> None:
        ser = OpenBadgesSerializer()
        doc = ser.assertion(_assertion())
        parsed = ser.parse_assertion(doc)
        assert parsed["id_url"] == "https://example.test/assertions/a1"
        assert parsed["badge_name"] == "Python Expert"
        assert parsed["recipient_is_hashed"] is True
        assert parsed["recipient_salt"] == "deadbeef"
