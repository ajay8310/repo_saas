"""
Unit tests for app.services.certificate_template_service (U5).

Requirements covered: FR-U5-1/2/6/7/9/11/12, NFR-U5-1 (tenant scope via the
service layer), NFR-U5-3 (asset upload fails closed on scanner outage).

Drives the service with a minimal fake async session that returns queued
objects for successive ``execute`` calls (``set_tenant_context`` issues the
first SELECT), records ``add``/``flush``/``commit``, and lets us assert the
pure business rules without a live database. S3 and the malware scanner are
replaced with simple fakes.
"""

from __future__ import annotations

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

from app.config import get_settings
from app.services.certificate_template_service import (
    CertificateTemplateService,
    TemplateInUseError,
    TemplateNotFoundError,
    TemplateServiceUnavailableError,
    TemplateValidationError,
)
from app.services.malware_scanner import ScanResult, ScanUnavailableError

TENANT = uuid4()

_VALID_LAYOUT = {
    "page": {"orientation": "landscape", "background_color": "#ffffff"},
    "blocks": [
        {
            "id": "t1",
            "type": "text",
            "x": 0.1,
            "y": 0.1,
            "w": 0.8,
            "h": 0.1,
            "z": 1,
            "style": {"text": "{{recipient}}", "font": "Helvetica-Bold", "size": 20, "align": "center"},
        },
        {"id": "qr", "type": "qr", "x": 0.8, "y": 0.8, "w": 0.15, "h": 0.15, "z": 2},
    ],
}


def _template(**overrides):
    base = dict(
        id=uuid4(),
        tenant_id=TENANT,
        name="Tpl",
        orientation="landscape",
        layout=dict(_VALID_LAYOUT),
        logo_s3_key=None,
        background_s3_key=None,
        version=1,
        status="active",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class _Result:
    def __init__(self, obj, scalar=None):
        self._obj = obj
        self._scalar = scalar

    def scalar_one_or_none(self):
        return self._obj

    def scalar(self):
        return self._scalar


class _FakeSession:
    def __init__(self, results):
        self._results = list(results)
        self.added: list = []
        self.commits = 0
        self.flushes = 0

    def add(self, obj) -> None:
        self.added.append(obj)

    async def execute(self, *_a, **_k):
        return self._results.pop(0) if self._results else _Result(None)

    async def flush(self):
        self.flushes += 1

    async def commit(self):
        self.commits += 1

    async def refresh(self, _obj):
        return None


class _FakeScanner:
    def __init__(self, clean=True, raise_unavailable=False):
        self._clean = clean
        self._raise = raise_unavailable

    def scan(self, _content: bytes) -> ScanResult:
        if self._raise:
            raise ScanUnavailableError("down")
        return ScanResult(clean=self._clean, reason=None if self._clean else "EICAR")


def _service(results, scanner=None):
    get_settings.cache_clear()
    svc = CertificateTemplateService(db=_FakeSession(results), settings=get_settings())
    svc._s3 = MagicMock()  # put_object/get_object are no-ops unless configured
    svc._scanner = scanner or _FakeScanner()
    return svc


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------


class TestCreate:
    async def test_create_valid_adds_flushes_commits(self) -> None:
        svc = _service([_Result(None)])  # tenant GUC
        tpl = await svc.create(TENANT, "My Template", "landscape", _VALID_LAYOUT)
        assert tpl.name == "My Template"
        assert tpl.orientation == "landscape"
        # one CertificateTemplate + one AuditLog added; flush before audit.
        assert svc.db.flushes == 1
        assert svc.db.commits == 1
        assert len(svc.db.added) == 2

    async def test_create_rejects_blank_name(self) -> None:
        svc = _service([])
        with pytest.raises(TemplateValidationError):
            await svc.create(TENANT, "   ", "portrait", _VALID_LAYOUT)

    async def test_create_rejects_bad_orientation(self) -> None:
        svc = _service([])
        with pytest.raises(TemplateValidationError):
            await svc.create(TENANT, "T", "sideways", _VALID_LAYOUT)

    async def test_create_rejects_invalid_layout(self) -> None:
        svc = _service([])
        bad = {"page": {"orientation": "portrait", "background_color": "#fff"}, "blocks": []}
        with pytest.raises(TemplateValidationError):
            await svc.create(TENANT, "T", "portrait", bad)  # bad hex color


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------


class TestUpdate:
    async def test_update_bumps_version(self) -> None:
        tpl = _template(version=3)
        svc = _service([_Result(None), _Result(tpl)])  # tenant GUC, _get
        out = await svc.update(TENANT, tpl.id, name="Renamed")
        assert out.name == "Renamed"
        assert out.version == 4

    async def test_update_missing_raises(self) -> None:
        svc = _service([_Result(None), _Result(None)])
        with pytest.raises(TemplateNotFoundError):
            await svc.update(TENANT, uuid4(), name="x")

    async def test_update_rejects_invalid_layout(self) -> None:
        tpl = _template()
        svc = _service([_Result(None), _Result(tpl)])
        bad_layout = {"blocks": [{"id": "x", "type": "text", "x": 0.9, "y": 0.1, "w": 0.5, "h": 0.1,
                                  "style": {"text": "hi"}}]}  # x+w > 1
        with pytest.raises(TemplateValidationError):
            await svc.update(TENANT, tpl.id, layout=bad_layout)


# ---------------------------------------------------------------------------
# delete (archive, blocked if in use)
# ---------------------------------------------------------------------------


class TestDelete:
    async def test_delete_archives_when_unused(self) -> None:
        tpl = _template(status="active")
        # tenant GUC, _get, in-use count=0
        svc = _service([_Result(None), _Result(tpl), _Result(None, scalar=0)])
        await svc.delete(TENANT, tpl.id)
        assert tpl.status == "archived"
        assert svc.db.commits == 1

    async def test_delete_blocked_when_in_use(self) -> None:
        tpl = _template(status="active")
        svc = _service([_Result(None), _Result(tpl), _Result(None, scalar=2)])
        with pytest.raises(TemplateInUseError):
            await svc.delete(TENANT, tpl.id)
        assert tpl.status == "active"  # unchanged

    async def test_delete_missing_raises(self) -> None:
        svc = _service([_Result(None), _Result(None)])
        with pytest.raises(TemplateNotFoundError):
            await svc.delete(TENANT, uuid4())


# ---------------------------------------------------------------------------
# asset upload
# ---------------------------------------------------------------------------


_PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


class TestUploadAsset:
    async def test_upload_logo_sets_key(self) -> None:
        tpl = _template()
        svc = _service([_Result(None), _Result(tpl)])
        key = await svc.upload_asset(TENANT, tpl.id, "logo", _PNG, "image/png")
        assert key.endswith(".png")
        assert "templates" in key and "logo-" in key
        assert tpl.logo_s3_key == key
        svc._s3.put_object.assert_called_once()

    async def test_upload_background_sets_key(self) -> None:
        tpl = _template()
        svc = _service([_Result(None), _Result(tpl)])
        key = await svc.upload_asset(TENANT, tpl.id, "background", _PNG, "image/png")
        assert tpl.background_s3_key == key

    async def test_upload_bad_kind(self) -> None:
        svc = _service([])
        with pytest.raises(TemplateValidationError):
            await svc.upload_asset(TENANT, uuid4(), "banner", _PNG, "image/png")

    async def test_upload_bad_content_type(self) -> None:
        svc = _service([])
        with pytest.raises(TemplateValidationError):
            await svc.upload_asset(TENANT, uuid4(), "logo", _PNG, "image/gif")

    async def test_upload_rejects_malware(self) -> None:
        tpl = _template()
        svc = _service([_Result(None), _Result(tpl)], scanner=_FakeScanner(clean=False))
        with pytest.raises(TemplateValidationError):
            await svc.upload_asset(TENANT, tpl.id, "logo", _PNG, "image/png")

    async def test_upload_fails_closed_on_scanner_outage(self) -> None:
        tpl = _template()
        svc = _service([_Result(None), _Result(tpl)], scanner=_FakeScanner(raise_unavailable=True))
        with pytest.raises(TemplateServiceUnavailableError):
            await svc.upload_asset(TENANT, tpl.id, "logo", _PNG, "image/png")

    async def test_upload_to_missing_template(self) -> None:
        svc = _service([_Result(None), _Result(None)])
        with pytest.raises(TemplateNotFoundError):
            await svc.upload_asset(TENANT, uuid4(), "logo", _PNG, "image/png")


# ---------------------------------------------------------------------------
# assignment
# ---------------------------------------------------------------------------


class TestAssign:
    async def test_assign_sets_custom_template_id(self) -> None:
        badge = SimpleNamespace(id=uuid4(), custom_template_id=None)
        tpl = _template(status="active")
        # tenant GUC, badge lookup, template lookup
        svc = _service([_Result(None), _Result(badge), _Result(tpl)])
        out = await svc.assign_to_class(TENANT, badge.id, tpl.id)
        assert out.custom_template_id == tpl.id

    async def test_clear_assignment(self) -> None:
        badge = SimpleNamespace(id=uuid4(), custom_template_id=uuid4())
        svc = _service([_Result(None), _Result(badge)])
        out = await svc.assign_to_class(TENANT, badge.id, None)
        assert out.custom_template_id is None

    async def test_assign_missing_class(self) -> None:
        svc = _service([_Result(None), _Result(None)])
        with pytest.raises(TemplateNotFoundError):
            await svc.assign_to_class(TENANT, uuid4(), uuid4())

    async def test_assign_missing_or_archived_template(self) -> None:
        badge = SimpleNamespace(id=uuid4(), custom_template_id=None)
        archived = _template(status="archived")
        svc = _service([_Result(None), _Result(badge), _Result(archived)])
        with pytest.raises(TemplateNotFoundError):
            await svc.assign_to_class(TENANT, badge.id, archived.id)


# ---------------------------------------------------------------------------
# preview (renders sample data without persistence)
# ---------------------------------------------------------------------------


class TestPreview:
    async def test_inline_preview_returns_pdf(self) -> None:
        svc = _service([])
        preview = await svc.render_preview(TENANT, _VALID_LAYOUT)
        assert preview.media_type == "application/pdf"
        assert preview.content[:4] == b"%PDF"

    async def test_preview_of_saved(self) -> None:
        tpl = _template()
        svc = _service([_Result(None), _Result(tpl)])
        preview = await svc.render_preview_of(TENANT, tpl.id)
        assert preview.content[:4] == b"%PDF"

    async def test_preview_of_missing_raises(self) -> None:
        svc = _service([_Result(None), _Result(None)])
        with pytest.raises(TemplateNotFoundError):
            await svc.render_preview_of(TENANT, uuid4())
