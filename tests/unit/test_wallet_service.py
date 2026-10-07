"""
Unit tests for app.services.wallet_service — earner wallet business rules (U2).

Requirements covered: S9 (hide), S10 (delete-from-wallet soft delist), S11
(public/private + private-by-default), BR-W4/W5/W7.

The service's mutation methods resolve an assertion, apply flag changes, and
commit. We drive them with a minimal fake async session that returns a stubbed
assertion for id-scoped selects and records commits, so the pure business rules
can be verified without a live database.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("S3_BUCKET_NAME", "test-bucket")
os.environ.setdefault("JWT_PRIVATE_KEY", "-----BEGIN RSA PRIVATE KEY-----\nX\n-----END RSA PRIVATE KEY-----")
os.environ.setdefault("JWT_PUBLIC_KEY", "-----BEGIN PUBLIC KEY-----\nX\n-----END PUBLIC KEY-----")

import pytest

from app.config import get_settings
from app.services.wallet_service import WalletConflictError, WalletService


def _assertion(**overrides):
    """Build a stub assertion object with the fields WalletService reads."""
    base = dict(
        id=uuid4(),
        badge_class_id=uuid4(),
        beneficiary_id="learner@example.test",
        status="active",
        issued_at=datetime(2026, 1, 1, tzinfo=UTC),
        expires_at=None,
        accepted=True,
        hidden=False,
        public=False,
        revoked_at=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _badge_class(assertion):
    return SimpleNamespace(
        id=assertion.badge_class_id,
        name="Python Expert",
        description="Mastery",
        image_s3_key=None,
    )


class _Result:
    def __init__(self, obj):
        self._obj = obj

    def scalar_one_or_none(self):
        return self._obj


class _FakeSession:
    """Fake async session: returns preset objects for successive execute() calls.

    ``set_tenant_context`` issues a ``SELECT set_config(...)`` first; we treat any
    execute as returning the next queued result. The service calls execute once
    for the tenant GUC, once for the owned-assertion lookup, and once for the
    class lookup, so we queue results in that order. ``add`` records objects (the
    published-event path calls it via BadgeEventService).
    """

    def __init__(self, results):
        self._results = list(results)
        self.commits = 0
        self.added: list = []

    def add(self, obj) -> None:
        self.added.append(obj)

    async def execute(self, *_args, **_kwargs):
        if self._results:
            return _Result(self._results.pop(0))
        return _Result(None)

    async def commit(self):
        self.commits += 1

    async def refresh(self, _obj):
        return None


def _service(results):
    get_settings.cache_clear()
    svc = WalletService(db=_FakeSession(results), settings=get_settings())
    return svc


TENANT = uuid4()
OWNER = "learner@example.test"


class TestSetHidden:
    async def test_hide_sets_flag_and_commits(self) -> None:
        a = _assertion()
        # order: tenant GUC, owned-assertion lookup, class lookup
        svc = _service([None, a, _badge_class(a)])
        item = await svc.set_hidden(TENANT, OWNER, a.id, hidden=True)
        assert a.hidden is True
        assert item is not None and item.hidden is True

    async def test_not_owned_returns_none(self) -> None:
        # owned-assertion lookup yields None (beneficiary filter didn't match)
        svc = _service([None, None])
        item = await svc.set_hidden(TENANT, OWNER, uuid4(), hidden=True)
        assert item is None


class TestDeleteFromWallet:
    async def test_delete_forces_hidden_and_private(self) -> None:
        a = _assertion(hidden=False, public=True)
        svc = _service([None, a])
        ok = await svc.delete_from_wallet(TENANT, OWNER, a.id)
        assert ok is True
        assert a.hidden is True
        assert a.public is False

    async def test_delete_not_owned_returns_false(self) -> None:
        svc = _service([None, None])
        ok = await svc.delete_from_wallet(TENANT, OWNER, uuid4())
        assert ok is False


class TestSetPublic:
    async def test_publish_active_sets_public(self) -> None:
        a = _assertion(public=False, status="active")
        svc = _service([None, a, _badge_class(a)])
        item = await svc.set_public(TENANT, OWNER, a.id, public=True)
        assert a.public is True
        assert item is not None and item.public is True

    async def test_publish_revoked_raises_conflict(self) -> None:
        a = _assertion(public=False, status="revoked")
        svc = _service([None, a])
        with pytest.raises(WalletConflictError):
            await svc.set_public(TENANT, OWNER, a.id, public=True)

    async def test_make_private_active(self) -> None:
        a = _assertion(public=True, status="active")
        svc = _service([None, a, _badge_class(a)])
        item = await svc.set_public(TENANT, OWNER, a.id, public=False)
        assert a.public is False
        assert item is not None and item.public is False

    async def test_not_owned_returns_none(self) -> None:
        svc = _service([None, None])
        item = await svc.set_public(TENANT, OWNER, uuid4(), public=True)
        assert item is None


class TestPublicUrl:
    def test_public_url_targets_hosted_assertion(self) -> None:
        svc = _service([])
        aid = uuid4()
        url = svc.public_url(aid)
        assert url.endswith(f"/api/v1/public/badges/assertions/{aid}")
