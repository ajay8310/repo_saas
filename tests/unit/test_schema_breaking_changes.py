"""
Unit tests for schema breaking-change detection.

Verifies that detect_breaking_changes() correctly separates changes that
invalidate already-issued documents from changes that are safe to apply.

Requirements covered: 2.3 (reject breaking schema updates), 2.4 (versioning).
"""

from __future__ import annotations

import os

# ---- test env setup (schema_service imports db.session, which reads Settings) ----
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

from app.services.schema_service import detect_breaking_changes  # noqa: E402


def _changes(old: list[dict], new: list[dict]) -> set[str]:
    """Return just the set of change kinds, for concise assertions."""
    return {c["change"] for c in detect_breaking_changes(old, new)}


# A small baseline schema reused across tests.
BASE = [
    {"name": "student_name", "type": "string", "required": True},
    {"name": "graduation_year", "type": "number", "required": True},
    {"name": "honours", "type": "boolean", "required": False},
    {"name": "grade", "type": "enumeration", "required": True,
     "allowed_values": ["A", "B", "C"]},
]


class TestNonBreakingChanges:
    """Additive and relaxing changes must be allowed through."""

    def test_identical_definitions_are_not_breaking(self) -> None:
        assert detect_breaking_changes(BASE, BASE) == []

    def test_adding_optional_field_is_not_breaking(self) -> None:
        new = BASE + [{"name": "notes", "type": "string", "required": False}]
        assert detect_breaking_changes(BASE, new) == []

    def test_widening_enumeration_is_not_breaking(self) -> None:
        new = [
            dict(f, allowed_values=["A", "B", "C", "D"])
            if f["name"] == "grade" else f
            for f in BASE
        ]
        assert detect_breaking_changes(BASE, new) == []

    def test_required_becoming_optional_is_not_breaking(self) -> None:
        new = [
            dict(f, required=False) if f["name"] == "student_name" else f
            for f in BASE
        ]
        assert detect_breaking_changes(BASE, new) == []

    def test_field_reordering_is_not_breaking(self) -> None:
        assert detect_breaking_changes(BASE, list(reversed(BASE))) == []

    def test_empty_to_optional_field_is_not_breaking(self) -> None:
        new = [{"name": "anything", "type": "string", "required": False}]
        assert detect_breaking_changes([], new) == []


class TestBreakingChanges:
    """Removals and tightening must be flagged."""

    def test_removing_field_is_breaking(self) -> None:
        new = [f for f in BASE if f["name"] != "honours"]
        result = detect_breaking_changes(BASE, new)
        assert {"change": "field_removed", "field": "honours"} in result

    def test_renaming_field_is_breaking(self) -> None:
        """A rename is a removal plus an addition — both should surface."""
        new = [
            {"name": "full_name", "type": "string", "required": True}
            if f["name"] == "student_name" else f
            for f in BASE
        ]
        kinds = _changes(BASE, new)
        assert "field_removed" in kinds
        assert "required_field_added" in kinds

    def test_changing_type_is_breaking(self) -> None:
        new = [
            dict(f, type="string") if f["name"] == "graduation_year" else f
            for f in BASE
        ]
        result = detect_breaking_changes(BASE, new)
        change = next(c for c in result if c["change"] == "type_changed")
        assert change["field"] == "graduation_year"
        assert change["from"] == "number"
        assert change["to"] == "string"

    def test_adding_required_field_is_breaking(self) -> None:
        new = BASE + [{"name": "roll_no", "type": "string", "required": True}]
        result = detect_breaking_changes(BASE, new)
        assert {"change": "required_field_added", "field": "roll_no"} in result

    def test_optional_becoming_required_is_breaking(self) -> None:
        new = [
            dict(f, required=True) if f["name"] == "honours" else f
            for f in BASE
        ]
        result = detect_breaking_changes(BASE, new)
        assert {"change": "optional_became_required", "field": "honours"} in result

    def test_narrowing_enumeration_is_breaking(self) -> None:
        new = [
            dict(f, allowed_values=["A", "B"]) if f["name"] == "grade" else f
            for f in BASE
        ]
        result = detect_breaking_changes(BASE, new)
        change = next(c for c in result if c["change"] == "enum_values_removed")
        assert change["field"] == "grade"
        assert change["removed_values"] == ["C"]

    def test_removing_all_fields_flags_every_removal(self) -> None:
        result = detect_breaking_changes(BASE, [])
        assert len(result) == len(BASE)
        assert all(c["change"] == "field_removed" for c in result)


class TestCombinedChanges:
    """Multiple independent breaking changes are reported together."""

    def test_type_change_and_removal_both_reported(self) -> None:
        new = [
            {"name": "student_name", "type": "string", "required": True},
            {"name": "graduation_year", "type": "string", "required": True},
            {"name": "grade", "type": "enumeration", "required": True,
             "allowed_values": ["A", "B", "C"]},
        ]
        kinds = _changes(BASE, new)
        assert kinds == {"field_removed", "type_changed"}

    def test_fields_without_names_are_ignored_safely(self) -> None:
        """Malformed entries shouldn't crash the differ."""
        assert detect_breaking_changes([{"type": "string"}], [{"type": "string"}]) == []
