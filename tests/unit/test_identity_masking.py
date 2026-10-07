"""
Unit tests for app.services.identity_masking (U3 Q5=A, BR-P2).

The raw email must never survive masking; non-email handles pass through.
"""

from __future__ import annotations

from app.services.identity_masking import mask_identity


class TestMaskIdentity:
    def test_email_is_masked(self) -> None:
        masked = mask_identity("alice@example.com")
        assert masked != "alice@example.com"
        assert "alice" not in masked
        assert masked.endswith(".com")

    def test_short_local_part(self) -> None:
        masked = mask_identity("al@example.com")
        assert masked.startswith("a*")

    def test_non_email_passes_through(self) -> None:
        assert mask_identity("learner-42") == "learner-42"

    def test_empty(self) -> None:
        assert mask_identity("") == ""
