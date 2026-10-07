"""
Property tests for U2 Wallet.

Properties (PBT-03/07):
* delete-from-wallet always yields hidden=true AND public=false, for any starting
  flag combination and status (BR-W4 / Q4=B);
* publishing a revoked assertion is always rejected, never succeeds (BR-W5);
* making an active assertion public always yields public=true (S11);
* making any assertion private always yields public=false.
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("S3_BUCKET_NAME", "test-bucket")
os.environ.setdefault("JWT_PRIVATE_KEY", "-----BEGIN RSA PRIVATE KEY-----\nX\n-----END RSA PRIVATE KEY-----")
os.environ.setdefault("JWT_PUBLIC_KEY", "-----BEGIN PUBLIC KEY-----\nX\n-----END PUBLIC KEY-----")

from app.config import get_settings

get_settings.cache_clear()

import pytest
from hypothesis import given
from hypothesis import settings as h_settings

from app.services.wallet_service import WalletConflictError, WalletService
from tests.property.strategies import assertion_statuses, wallet_flag_combos

OWNER = "learner@example.test"
TENANT = uuid4()


def _assertion(status: str, flags: dict):
    return SimpleNamespace(
        id=uuid4(),
        badge_class_id=uuid4(),
        beneficiary_id=OWNER,
        status=status,
        issued_at=datetime(2026, 1, 1, tzinfo=UTC),
        expires_at=None,
        accepted=flags["accepted"],
        hidden=flags["hidden"],
        public=flags["public"],
        revoked_at=None,
    )


def _badge_class(a):
    return SimpleNamespace(id=a.badge_class_id, name="B", description=None, image_s3_key=None)


class _Result:
    def __init__(self, obj):
        self._obj = obj

    def scalar_one_or_none(self):
        return self._obj


class _FakeSession:
    def __init__(self, results):
        self._results = list(results)
        self.added: list = []

    def add(self, obj) -> None:
        self.added.append(obj)

    async def execute(self, *_a, **_k):
        return _Result(self._results.pop(0) if self._results else None)

    async def commit(self):
        return None

    async def refresh(self, _obj):
        return None


def _service(results):
    return WalletService(db=_FakeSession(results), settings=get_settings())


class TestDeleteInvariant:
    @given(status=assertion_statuses, flags=wallet_flag_combos)
    @h_settings(max_examples=100)
    def test_delete_always_hidden_and_private(self, status: str, flags: dict) -> None:
        a = _assertion(status, flags)
        svc = _service([None, a])
        ok = asyncio.run(svc.delete_from_wallet(TENANT, OWNER, a.id))
        assert ok is True
        assert a.hidden is True
        assert a.public is False


class TestPublishInvariant:
    @given(flags=wallet_flag_combos)
    @h_settings(max_examples=75)
    def test_revoked_never_publishable(self, flags: dict) -> None:
        a = _assertion("revoked", flags)
        started_public = a.public
        svc = _service([None, a])
        with pytest.raises(WalletConflictError):
            asyncio.run(svc.set_public(TENANT, OWNER, a.id, public=True))
        # The guard fires before any mutation: public is never *transitioned on*.
        assert a.public == started_public

    @given(flags=wallet_flag_combos)
    @h_settings(max_examples=75)
    def test_active_publish_sets_public(self, flags: dict) -> None:
        a = _assertion("active", flags)
        svc = _service([None, a, _badge_class(a)])
        item = asyncio.run(svc.set_public(TENANT, OWNER, a.id, public=True))
        assert a.public is True
        assert item is not None and item.public is True

    @given(status=assertion_statuses, flags=wallet_flag_combos)
    @h_settings(max_examples=75)
    def test_make_private_always_unsets_public(self, status: str, flags: dict) -> None:
        a = _assertion(status, flags)
        svc = _service([None, a, _badge_class(a)])
        item = asyncio.run(svc.set_public(TENANT, OWNER, a.id, public=False))
        assert a.public is False
        assert item is not None and item.public is False
