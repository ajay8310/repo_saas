"""
Unit tests for the U6 badge-download service paths and assertion listing.

Covers CertificateService.build_badge_json / build_badge_png / _assertion_doc
(FR-U6-1/2/3/4), ownership enforcement (FR-U6-5, NFR-U6-1), and
IssuanceService.list_assertions (FR-U6-6).

Uses a fake async session (queued execute results; sync add; async
commit/refresh), with S3 mocked, mirroring the wallet/template service tests.
"""

from __future__ import annotations

import io
import os
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("S3_BUCKET_NAME", "test-bucket")
os.environ.setdefault("JWT_PRIVATE_KEY", "-----BEGIN RSA PRIVATE KEY-----\nX\n-----END RSA PRIVATE KEY-----")
os.environ.setdefault("JWT_PUBLIC_KEY", "-----BEGIN PUBLIC KEY-----\nX\n-----END PUBLIC KEY-----")

import pytest
from PIL import Image

from app.config import get_settings
from app.services.badge_baker import BadgeImageNotBakeableError, read_baked
from app.services.certificate_service import (
    CertificateNotFoundError,
    CertificateService,
)
from app.services.issuance_service import IssuanceService

TENANT = uuid4()
OWNER = "jane@example.com"


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (16, 16), (180, 140, 20)).save(buf, format="PNG")
    return buf.getvalue()


def _assertion(**overrides):
    base = dict(
        id=uuid4(),
        badge_class_id=uuid4(),
        tenant_id=TENANT,
        beneficiary_id=OWNER,
        issued_at=datetime(2026, 10, 8, tzinfo=UTC),
        expires_at=None,
        status="active",
        revoked_at=None,
        revocation_reason=None,
        recipient_photo_s3_key=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _badge_class(assertion, image_s3_key=None, **overrides):
    base = dict(
        id=assertion.badge_class_id,
        name="Advanced Python",
        description="desc",
        criteria_narrative="pass the exam",
        criteria_url=None,
        tags=["python"],
        alignment=[],
        image_s3_key=image_s3_key,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _tenant():
    return SimpleNamespace(
        id=TENANT, issuer_name="Demo University", name="Demo",
        issuer_url="https://demo.example", issuer_email="badges@demo.example",
    )


class _Result:
    def __init__(self, obj):
        self._obj = obj

    def scalar_one_or_none(self):
        return self._obj

    def scalars(self):
        return self

    def all(self):
        return self._obj if isinstance(self._obj, list) else []


class _FakeSession:
    def __init__(self, results):
        self._results = list(results)
        self.added: list = []
        self.commits = 0

    def add(self, obj) -> None:
        self.added.append(obj)

    async def execute(self, *_a, **_k):
        return self._results.pop(0) if self._results else _Result(None)

    async def commit(self):
        self.commits += 1

    async def refresh(self, _obj):
        return None


def _cert_service(results, s3_bytes=None):
    get_settings.cache_clear()
    svc = CertificateService(db=_FakeSession(results), settings=get_settings())
    svc._s3 = MagicMock()
    svc._fetch_s3 = MagicMock(return_value=s3_bytes)  # type: ignore[method-assign]
    return svc


# ---------------------------------------------------------------------------
# build_badge_json
# ---------------------------------------------------------------------------


class TestBuildBadgeJson:
    async def test_json_download_ok(self) -> None:
        a = _assertion()
        bc = _badge_class(a)
        # resolution order: tenant GUC, assertion, class, tenant
        svc = _cert_service([_Result(None), _Result(a), _Result(bc), _Result(_tenant())])
        out = await svc.build_badge_json(TENANT, a.id, actor_id="iss")
        assert out.media_type == "application/ld+json"
        assert out.filename == f"badge-{a.id}.json"
        import json
        doc = json.loads(out.content)
        assert doc["type"] == "Assertion"
        assert doc["badge"]["name"] == "Advanced Python"
        assert doc["verification"]["type"] == "HostedBadge"
        assert svc.db.commits == 1  # audit + event committed

    async def test_json_missing_assertion_404(self) -> None:
        svc = _cert_service([_Result(None), _Result(None)])
        with pytest.raises(CertificateNotFoundError):
            await svc.build_badge_json(TENANT, uuid4(), actor_id="iss")

    async def test_json_owner_mismatch_404(self) -> None:
        a = _assertion(beneficiary_id="someone.else@example.com")
        svc = _cert_service([_Result(None), _Result(a)])
        with pytest.raises(CertificateNotFoundError):
            await svc.build_badge_json(TENANT, a.id, require_owner=OWNER)

    async def test_json_revoked_sets_flag(self) -> None:
        a = _assertion(status="revoked", revocation_reason="mistake")
        bc = _badge_class(a)
        svc = _cert_service([_Result(None), _Result(a), _Result(bc), _Result(_tenant())])
        out = await svc.build_badge_json(TENANT, a.id)
        import json
        assert json.loads(out.content).get("revoked") is True


# ---------------------------------------------------------------------------
# build_badge_png
# ---------------------------------------------------------------------------


class TestBuildBadgePng:
    async def test_png_ok_and_roundtrips(self) -> None:
        a = _assertion()
        bc = _badge_class(a, image_s3_key="badges/t/c/img.png")
        svc = _cert_service(
            [_Result(None), _Result(a), _Result(bc), _Result(_tenant())], s3_bytes=_png()
        )
        out = await svc.build_badge_png(TENANT, a.id)
        assert out.media_type == "image/png"
        assert out.filename == f"badge-{a.id}.png"
        back = read_baked(out.content)
        assert back is not None and back["type"] == "Assertion"
        assert back["badge"]["name"] == "Advanced Python"

    async def test_png_no_image_422(self) -> None:
        a = _assertion()
        bc = _badge_class(a, image_s3_key=None)
        svc = _cert_service([_Result(None), _Result(a), _Result(bc), _Result(_tenant())])
        with pytest.raises(BadgeImageNotBakeableError):
            await svc.build_badge_png(TENANT, a.id)

    async def test_png_svg_image_422(self) -> None:
        a = _assertion()
        bc = _badge_class(a, image_s3_key="badges/t/c/logo.svg")
        svc = _cert_service([_Result(None), _Result(a), _Result(bc), _Result(_tenant())])
        with pytest.raises(BadgeImageNotBakeableError):
            await svc.build_badge_png(TENANT, a.id)

    async def test_png_image_fetch_fails_422(self) -> None:
        a = _assertion()
        bc = _badge_class(a, image_s3_key="badges/t/c/img.png")
        svc = _cert_service(
            [_Result(None), _Result(a), _Result(bc), _Result(_tenant())], s3_bytes=None
        )
        with pytest.raises(BadgeImageNotBakeableError):
            await svc.build_badge_png(TENANT, a.id)

    async def test_png_owner_mismatch_404(self) -> None:
        a = _assertion(beneficiary_id="other@example.com")
        svc = _cert_service([_Result(None), _Result(a)])
        with pytest.raises(CertificateNotFoundError):
            await svc.build_badge_png(TENANT, a.id, require_owner=OWNER)


# ---------------------------------------------------------------------------
# IssuanceService.list_assertions
# ---------------------------------------------------------------------------


class TestListAssertions:
    async def test_list_returns_rows(self) -> None:
        get_settings.cache_clear()
        rows = [_assertion(), _assertion(), _assertion()]
        svc = IssuanceService(db=_FakeSession([_Result(None), _Result(rows)]), settings=get_settings())
        out = await svc.list_assertions(TENANT)
        assert len(out) == 3

    async def test_list_empty(self) -> None:
        get_settings.cache_clear()
        svc = IssuanceService(db=_FakeSession([_Result(None), _Result([])]), settings=get_settings())
        out = await svc.list_assertions(TENANT)
        assert out == []
