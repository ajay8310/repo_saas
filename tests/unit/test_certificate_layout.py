"""
Unit tests for app.services.certificate_layout (U5).

Requirements covered: FR-U5-4 (block types + geometry), FR-U5-5 (placeholder
safety), FR-U5-10 (verification detection), FR-U5-12 (layout validation).

Pure functions — no DB/network — so these are fast and deterministic.
"""

from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("S3_BUCKET_NAME", "test-bucket")
os.environ.setdefault("JWT_PRIVATE_KEY", "-----BEGIN RSA PRIVATE KEY-----\nX\n-----END RSA PRIVATE KEY-----")
os.environ.setdefault("JWT_PUBLIC_KEY", "-----BEGIN PUBLIC KEY-----\nX\n-----END PUBLIC KEY-----")

from app.services.certificate_layout import (
    FONT_WHITELIST,
    PLACEHOLDER_WHITELIST,
    layout_has_verification,
    resolve_placeholders,
    validate_layout,
)


def _ctx(**overrides):
    base = dict(
        assertion_id="a-1",
        badge_name="Advanced Python",
        recipient_display="Jane",
        issuer_name="Demo University",
        issued_at="2026-10-08",
        expires_at="2027-10-08",
        criteria="Pass the exam",
        verify_url="https://x/verify/a-1",
        signature_jws="h.p.sig",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


_TEXT_BLOCK = {
    "id": "t",
    "type": "text",
    "x": 0.1,
    "y": 0.1,
    "w": 0.5,
    "h": 0.1,
    "style": {"text": "Hello", "font": "Helvetica", "size": 14, "align": "left"},
}


class TestValidateGeometry:
    def test_valid_layout_has_no_issues(self) -> None:
        layout = {"page": {"orientation": "portrait", "background_color": "#ffffff"},
                  "blocks": [_TEXT_BLOCK]}
        assert validate_layout(layout) == []

    def test_x_plus_w_overflow_flagged(self) -> None:
        blk = {**_TEXT_BLOCK, "x": 0.8, "w": 0.5}  # 1.3 > 1
        issues = validate_layout({"blocks": [blk]})
        assert any("exceeds page width" in i for i in issues)

    def test_y_plus_h_overflow_flagged(self) -> None:
        blk = {**_TEXT_BLOCK, "y": 0.9, "h": 0.3}  # 1.2 > 1
        issues = validate_layout({"blocks": [blk]})
        assert any("exceeds page height" in i for i in issues)

    def test_boundary_exactly_one_is_ok(self) -> None:
        blk = {**_TEXT_BLOCK, "x": 0.2, "w": 0.8, "y": 0.0, "h": 1.0}
        assert validate_layout({"blocks": [blk]}) == []

    def test_duplicate_block_ids_flagged(self) -> None:
        issues = validate_layout({"blocks": [_TEXT_BLOCK, dict(_TEXT_BLOCK)]})
        assert any("duplicate block id" in i for i in issues)

    def test_too_many_blocks_flagged(self) -> None:
        blocks = [{**_TEXT_BLOCK, "id": f"b{i}"} for i in range(5)]
        issues = validate_layout({"blocks": blocks}, max_blocks=3)
        assert any("too many blocks" in i for i in issues)


class TestValidateEnumsAndTypes:
    def test_bad_orientation(self) -> None:
        issues = validate_layout({"page": {"orientation": "diagonal", "background_color": "#fff"}})
        assert issues  # structural failure

    def test_bad_color(self) -> None:
        issues = validate_layout({"page": {"orientation": "portrait", "background_color": "blue"}})
        assert issues

    def test_bad_font(self) -> None:
        blk = {**_TEXT_BLOCK, "style": {**_TEXT_BLOCK["style"], "font": "ComicSans"}}
        issues = validate_layout({"blocks": [blk]})
        assert issues

    def test_font_whitelist_accepts_builtins(self) -> None:
        for font in FONT_WHITELIST:
            blk = {**_TEXT_BLOCK, "style": {**_TEXT_BLOCK["style"], "font": font}}
            assert validate_layout({"blocks": [blk]}) == []

    def test_unknown_block_type(self) -> None:
        blk = {"id": "x", "type": "hologram", "x": 0.1, "y": 0.1, "w": 0.1, "h": 0.1}
        issues = validate_layout({"blocks": [blk]})
        assert issues

    def test_text_block_requires_text(self) -> None:
        blk = {"id": "x", "type": "text", "x": 0.1, "y": 0.1, "w": 0.5, "h": 0.1, "style": {}}
        issues = validate_layout({"blocks": [blk]})
        assert any("requires non-empty" in i for i in issues)

    def test_non_text_block_needs_no_text(self) -> None:
        blk = {"id": "logo", "type": "logo", "x": 0.1, "y": 0.1, "w": 0.2, "h": 0.1}
        assert validate_layout({"blocks": [blk]}) == []


class TestVerificationDetection:
    def test_qr_block_counts_as_verification(self) -> None:
        assert layout_has_verification({"blocks": [{"type": "qr"}]}) is True

    def test_signature_block_counts(self) -> None:
        assert layout_has_verification({"blocks": [{"type": "signature"}]}) is True

    def test_no_verification_block(self) -> None:
        assert layout_has_verification({"blocks": [{"type": "text"}]}) is False

    def test_empty_layout(self) -> None:
        assert layout_has_verification({}) is False


class TestPlaceholders:
    def test_known_tokens_substituted(self) -> None:
        out = resolve_placeholders("{{recipient}} earned {{badge_name}}", _ctx())
        assert out == "Jane earned Advanced Python"

    def test_unknown_token_becomes_empty(self) -> None:
        out = resolve_placeholders("Hi {{nope}}!", _ctx())
        assert out == "Hi !"
        assert "{{" not in out and "}}" not in out

    def test_whitespace_inside_braces(self) -> None:
        out = resolve_placeholders("{{  recipient  }}", _ctx())
        assert out == "Jane"

    def test_empty_text(self) -> None:
        assert resolve_placeholders("", _ctx()) == ""

    def test_all_whitelisted_tokens_resolve(self) -> None:
        for token in PLACEHOLDER_WHITELIST:
            out = resolve_placeholders(f"[{{{{{token}}}}}]", _ctx())
            assert "{{" not in out and "}}" not in out
