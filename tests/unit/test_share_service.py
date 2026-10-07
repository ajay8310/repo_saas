"""
Unit tests for app.services.share_service (U3 — S12).

Requirements covered: BR-P3 (OG meta from badge fields), BR-P4 (LinkedIn deep
link, no API), BR-P5 (share URL tagged with channel), round-trip of the channel.

The DB-touching ``build_share`` is covered by integration; here we test the pure
URL/meta builders and the channel round-trip helper via a service instance with
a stub session (the builders never touch it).
"""

from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("S3_BUCKET_NAME", "test-bucket")
os.environ.setdefault("JWT_PRIVATE_KEY", "-----BEGIN RSA PRIVATE KEY-----\nX\n-----END RSA PRIVATE KEY-----")
os.environ.setdefault("JWT_PUBLIC_KEY", "-----BEGIN PUBLIC KEY-----\nX\n-----END PUBLIC KEY-----")

from types import SimpleNamespace
from uuid import uuid4

from app.config import get_settings
from app.services.share_service import ShareService, parse_channel_from_share_url


def _service() -> ShareService:
    get_settings.cache_clear()
    return ShareService(db=SimpleNamespace(), settings=get_settings())


class TestLinkedInUrl:
    def test_linkedin_wraps_target_url(self) -> None:
        svc = _service()
        target = "https://host/api/v1/public/badges/assertions/x?channel=linkedin"
        url = svc._linkedin_url(target)
        assert url.startswith("https://www.linkedin.com/sharing/share-offsite/?url=")
        # Target is percent-encoded (no raw ? / : from the inner URL).
        assert "%3A%2F%2F" in url


class TestOpenGraph:
    def test_og_uses_badge_fields(self) -> None:
        svc = _service()
        badge = SimpleNamespace(name="Python Expert", description="Mastery of Python.")
        og = svc._open_graph("https://host/x", badge)
        assert og["og:title"] == "Python Expert"
        assert og["og:description"] == "Mastery of Python."
        assert og["og:url"] == "https://host/x"

    def test_og_falls_back_without_class(self) -> None:
        svc = _service()
        og = svc._open_graph("https://host/x", None)
        assert og["og:title"] == "Verified Badge"
        assert og["og:description"]


class TestChannelRoundTrip:
    def test_channel_survives_url_round_trip(self) -> None:
        svc = _service()
        aid = uuid4()
        url = svc._public_url(aid) + "?channel=linkedin"
        assert parse_channel_from_share_url(url) == "linkedin"

    def test_missing_channel_returns_none(self) -> None:
        svc = _service()
        assert parse_channel_from_share_url(svc._public_url(uuid4())) is None
