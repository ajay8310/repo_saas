"""Open Badges 2.0 serialization (FR-4, FR-13, S13).

Pure, dependency-free logic that renders the three hosted Open Badges 2.0
artifacts — ``Assertion``, ``BadgeClass``, and ``Issuer`` — as JSON-LD dicts,
and parses an assertion dict back into its identifying fields (used by the
round-trip property test PBT-02).

Design notes
------------
* **Recipient privacy (Q5=A)**: the earner identity is never emitted raw. It is
  hashed as ``sha256$<hex>`` over ``identity + salt`` per the OB ``IdentityObject``
  spec, with ``hashed: true`` and the ``salt`` included so a verifier who already
  knows the email can confirm the match without the email ever appearing in the
  document.
* **Revocation (Q3=A)**: a revoked assertion is still served (HTTP 200) with
  ``revoked: true`` and an optional ``revocationReason`` — the OB-compliant way to
  express revocation, rather than a 404.
* **Expiry (Q2=C)**: ``expires`` is emitted only for fixed-period badges; a
  non-expiring badge simply omits the field.
* **Baking is deferred (Q5=B)** — the hosted assertion URL is the verifiable
  artifact for U1; PNG/SVG baking is future work (FR-2.3).

This module knows nothing about the database or HTTP layer; callers pass in
already-resolved primitives so the serializer stays trivially testable.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime

_OB_CONTEXT = "https://w3id.org/openbadges/v2"


def hash_identity(identity: str, salt: str) -> str:
    """Return an OB ``sha256$<hex>`` hashed identity string.

    The salt is appended to the identity before hashing, matching how a
    verifier reconstructs the value. Identity comparison is therefore possible
    only for someone who already knows both the plaintext identity and the salt.
    """
    digest = hashlib.sha256((identity + salt).encode("utf-8")).hexdigest()
    return f"sha256${digest}"


@dataclass(frozen=True, slots=True)
class IssuerProfile:
    """Minimal issuer identity for the OB ``Issuer`` / ``Profile`` object."""

    id_url: str
    name: str
    url: str | None = None
    email: str | None = None


@dataclass(frozen=True, slots=True)
class BadgeClassData:
    """Inputs required to render an OB ``BadgeClass``."""

    id_url: str
    name: str
    description: str | None
    image_url: str | None
    criteria_narrative: str | None
    criteria_url: str | None
    issuer: IssuerProfile
    tags: list[str] = field(default_factory=list)
    alignment: list[dict] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class AssertionData:
    """Inputs required to render an OB ``Assertion``."""

    id_url: str
    recipient_identity: str
    recipient_salt: str
    issued_on: datetime
    verify_url: str
    badge_class: BadgeClassData
    expires: datetime | None = None
    revoked: bool = False
    revocation_reason: str | None = None


class OpenBadgesSerializer:
    """Render and parse Open Badges 2.0 JSON-LD artifacts."""

    def issuer(self, issuer: IssuerProfile) -> dict:
        """Serialize an OB ``Issuer`` (Profile) object."""
        doc: dict = {
            "@context": _OB_CONTEXT,
            "type": "Issuer",
            "id": issuer.id_url,
            "name": issuer.name,
        }
        if issuer.url:
            doc["url"] = issuer.url
        if issuer.email:
            doc["email"] = issuer.email
        return doc

    def badge_class(self, badge: BadgeClassData) -> dict:
        """Serialize an OB ``BadgeClass`` object."""
        criteria: dict = {}
        if badge.criteria_url:
            criteria["id"] = badge.criteria_url
        if badge.criteria_narrative:
            criteria["narrative"] = badge.criteria_narrative

        doc: dict = {
            "@context": _OB_CONTEXT,
            "type": "BadgeClass",
            "id": badge.id_url,
            "name": badge.name,
            "issuer": self.issuer(badge.issuer),
        }
        if badge.description is not None:
            doc["description"] = badge.description
        if badge.image_url:
            doc["image"] = badge.image_url
        # Criteria is required by the spec; emit at least an empty narrative slot
        # only when we actually have something to say.
        if criteria:
            doc["criteria"] = criteria
        if badge.tags:
            doc["tags"] = list(badge.tags)
        if badge.alignment:
            doc["alignment"] = list(badge.alignment)
        return doc

    def assertion(self, assertion: AssertionData) -> dict:
        """Serialize an OB ``Assertion`` object with hashed recipient identity."""
        doc: dict = {
            "@context": _OB_CONTEXT,
            "type": "Assertion",
            "id": assertion.id_url,
            "recipient": {
                "type": "email",
                "hashed": True,
                "salt": assertion.recipient_salt,
                "identity": hash_identity(
                    assertion.recipient_identity, assertion.recipient_salt
                ),
            },
            "badge": self.badge_class(assertion.badge_class),
            "issuedOn": _iso(assertion.issued_on),
            "verification": {"type": "HostedBadge"},
        }
        # The hosted assertion URL is the verification target.
        doc["id"] = assertion.id_url
        if assertion.expires is not None:
            doc["expires"] = _iso(assertion.expires)
        if assertion.revoked:
            doc["revoked"] = True
            if assertion.revocation_reason:
                doc["revocationReason"] = assertion.revocation_reason
        return doc

    def parse_assertion(self, doc: dict) -> dict:
        """Extract identifying fields from a serialized assertion.

        Inverse of :meth:`assertion` for the fields that survive serialization
        (the raw recipient identity is intentionally NOT recoverable). Used by
        the round-trip property test to assert structural stability.
        """
        recipient = doc.get("recipient", {})
        badge = doc.get("badge", {})
        return {
            "id_url": doc.get("id"),
            "recipient_hashed": recipient.get("identity"),
            "recipient_salt": recipient.get("salt"),
            "recipient_is_hashed": recipient.get("hashed", False),
            "badge_id_url": badge.get("id"),
            "badge_name": badge.get("name"),
            "issued_on": doc.get("issuedOn"),
            "expires": doc.get("expires"),
            "revoked": doc.get("revoked", False),
            "revocation_reason": doc.get("revocationReason"),
        }


def _iso(value: datetime) -> str:
    """Serialize a datetime to an ISO 8601 string (OB timestamps)."""
    return value.isoformat()
