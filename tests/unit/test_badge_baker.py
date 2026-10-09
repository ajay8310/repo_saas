"""
Unit tests for app.services.badge_baker (U6).

Requirements covered: FR-U6-2 (baked PNG with embedded assertion), FR-U6-3
(non-PNG / missing source rejected cleanly), FR-U6-4 (embedded content reflects
the assertion).

Pure functions — no DB/network — so these are fast and deterministic.
"""

from __future__ import annotations

import io
import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("S3_BUCKET_NAME", "test-bucket")
os.environ.setdefault("JWT_PRIVATE_KEY", "-----BEGIN RSA PRIVATE KEY-----\nX\n-----END RSA PRIVATE KEY-----")
os.environ.setdefault("JWT_PUBLIC_KEY", "-----BEGIN PUBLIC KEY-----\nX\n-----END PUBLIC KEY-----")

import pytest
from PIL import Image

from app.services.badge_baker import (
    OB_KEYWORD,
    BadgeImageNotBakeableError,
    bake_png,
    read_baked,
)

_DOC = {
    "@context": "https://w3id.org/openbadges/v2",
    "type": "Assertion",
    "id": "https://x/assertions/abc",
    "badge": {"type": "BadgeClass", "name": "Advanced Python"},
    "verification": {"type": "HostedBadge"},
}


def _png(size=(16, 16), color=(180, 140, 20)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def _jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (16, 16), (10, 20, 30)).save(buf, format="JPEG")
    return buf.getvalue()


class TestBake:
    def test_bake_returns_valid_png(self) -> None:
        out = bake_png(_png(), _DOC)
        assert out[:8] == b"\x89PNG\r\n\x1a\n"

    def test_keyword_constant(self) -> None:
        assert OB_KEYWORD == "openbadges"

    def test_bake_embeds_under_openbadges_keyword(self) -> None:
        out = bake_png(_png(), _DOC)
        img = Image.open(io.BytesIO(out))
        assert OB_KEYWORD in (img.info or {})

    def test_baked_image_still_opens_and_same_size(self) -> None:
        out = bake_png(_png(size=(24, 24)), _DOC)
        img = Image.open(io.BytesIO(out))
        assert img.format == "PNG"
        assert img.size == (24, 24)


class TestRoundTrip:
    def test_read_returns_embedded_doc(self) -> None:
        out = bake_png(_png(), _DOC)
        assert read_baked(out) == _DOC

    def test_read_none_when_no_chunk(self) -> None:
        assert read_baked(_png()) is None

    def test_read_none_on_non_image(self) -> None:
        assert read_baked(b"not an image") is None


class TestRejection:
    def test_empty_rejected(self) -> None:
        with pytest.raises(BadgeImageNotBakeableError):
            bake_png(b"", _DOC)

    def test_svg_rejected(self) -> None:
        with pytest.raises(BadgeImageNotBakeableError):
            bake_png(b"<svg xmlns='http://www.w3.org/2000/svg'></svg>", _DOC)

    def test_garbage_rejected(self) -> None:
        with pytest.raises(BadgeImageNotBakeableError):
            bake_png(b"\x00\x01\x02 not an image", _DOC)

    def test_non_png_raster_rejected(self) -> None:
        # A valid JPEG is a readable image but not a PNG → must be rejected.
        with pytest.raises(BadgeImageNotBakeableError):
            bake_png(_jpeg(), _DOC)
