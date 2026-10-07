"""
Property tests for U1 Badge Core.

Properties:
* PBT-02 — Open Badges serialize -> parse round-trip preserves identifiers.
* PBT-03 — invariants:
    - hashed recipient identity never contains the raw identity;
    - a revoked assertion is never emitted as valid (always carries revoked=true);
    - expiry is emitted iff the badge is fixed-period (Q2=C);
    - the assertion always exposes exactly one identifier (its hosted id url).
* PBT-07 — domain generators exercise the above across a wide input space.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("S3_BUCKET_NAME", "test-bucket")
os.environ.setdefault("JWT_PRIVATE_KEY", "-----BEGIN RSA PRIVATE KEY-----\nX\n-----END RSA PRIVATE KEY-----")
os.environ.setdefault("JWT_PUBLIC_KEY", "-----BEGIN PUBLIC KEY-----\nX\n-----END PUBLIC KEY-----")

from app.config import get_settings

get_settings.cache_clear()

from hypothesis import given
from hypothesis import settings as h_settings
from hypothesis import strategies as st

from app.services.openbadges import (
    AssertionData,
    BadgeClassData,
    IssuerProfile,
    OpenBadgesSerializer,
    hash_identity,
)
from tests.property.strategies import (
    badge_descriptions,
    badge_names,
    badge_tags,
    recipient_identities,
    recipient_salts,
    validity_days,
)

_SER = OpenBadgesSerializer()

_issued_on = st.datetimes(
    min_value=datetime(2020, 1, 1), max_value=datetime(2030, 1, 1)
).map(lambda d: d.replace(tzinfo=UTC))


@st.composite
def assertions(draw) -> AssertionData:
    """Generate a valid AssertionData with varied badge/issuer/expiry/revocation."""
    issuer = IssuerProfile(
        id_url="https://example.test/issuers/t",
        name=draw(badge_names),
        url=None,
        email=None,
    )
    badge = BadgeClassData(
        id_url="https://example.test/classes/c",
        name=draw(badge_names),
        description=draw(badge_descriptions),
        image_url=None,
        criteria_narrative=None,
        criteria_url=None,
        issuer=issuer,
        tags=draw(badge_tags),
        alignment=[],
    )
    issued = draw(_issued_on)
    vdays = draw(validity_days)
    expires = issued + timedelta(days=vdays) if vdays else None
    revoked = draw(st.booleans())
    return AssertionData(
        id_url="https://example.test/assertions/a",
        recipient_identity=draw(recipient_identities),
        recipient_salt=draw(recipient_salts),
        issued_on=issued,
        verify_url="https://example.test/assertions/a",
        badge_class=badge,
        expires=expires,
        revoked=revoked,
        revocation_reason="reason" if revoked else None,
    )


class TestPBT02RoundTrip:
    """PBT-02: serialize -> parse preserves the stable identifiers."""

    @given(data=assertions())
    @h_settings(max_examples=75)
    def test_round_trip_preserves_identifiers(self, data: AssertionData) -> None:
        doc = _SER.assertion(data)
        parsed = _SER.parse_assertion(doc)
        assert parsed["id_url"] == data.id_url
        assert parsed["badge_name"] == data.badge_class.name
        assert parsed["recipient_salt"] == data.recipient_salt
        assert parsed["recipient_is_hashed"] is True
        assert parsed["revoked"] == data.revoked


class TestPBT03Invariants:
    @given(identity=recipient_identities, salt=recipient_salts)
    @h_settings(max_examples=75)
    def test_raw_identity_never_leaks(self, identity: str, salt: str) -> None:
        """The hashed recipient must not contain the raw identity substring."""
        hashed = hash_identity(identity, salt)
        assert hashed.startswith("sha256$")
        # A long enough identity cannot appear inside a fixed-length hex digest.
        if len(identity) > 8:
            assert identity not in hashed

    @given(data=assertions())
    @h_settings(max_examples=75)
    def test_revoked_never_valid(self, data: AssertionData) -> None:
        """A revoked assertion always carries revoked=true; active never does."""
        doc = _SER.assertion(data)
        if data.revoked:
            assert doc.get("revoked") is True
        else:
            assert "revoked" not in doc

    @given(data=assertions())
    @h_settings(max_examples=75)
    def test_expiry_iff_fixed_period(self, data: AssertionData) -> None:
        """`expires` appears exactly when the assertion has an expiry (Q2=C)."""
        doc = _SER.assertion(data)
        assert ("expires" in doc) == (data.expires is not None)

    @given(data=assertions())
    @h_settings(max_examples=50)
    def test_single_identifier(self, data: AssertionData) -> None:
        """The assertion exposes exactly one top-level id, its hosted URL."""
        doc = _SER.assertion(data)
        assert doc["id"] == data.id_url
