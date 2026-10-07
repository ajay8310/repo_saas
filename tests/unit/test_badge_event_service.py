"""
Unit tests for app.services.badge_event_service — event-type validation.

Requirements covered: FR-7 (analytics events). The service adds rows to the
caller's transaction; here we verify the validation guard rejects unknown event
types before any DB interaction, using a stub session that records ``add``.
"""

from __future__ import annotations

import os
from uuid import uuid4

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("S3_BUCKET_NAME", "test-bucket")
os.environ.setdefault("JWT_PRIVATE_KEY", "-----BEGIN RSA PRIVATE KEY-----\nX\n-----END RSA PRIVATE KEY-----")
os.environ.setdefault("JWT_PUBLIC_KEY", "-----BEGIN PUBLIC KEY-----\nX\n-----END PUBLIC KEY-----")

import pytest

from app.services.badge_event_service import BadgeEventService


class _StubSession:
    """Minimal stand-in that records objects passed to ``add``."""

    def __init__(self) -> None:
        self.added: list = []

    def add(self, obj) -> None:  # noqa: ANN001
        self.added.append(obj)


class TestEventTypeValidation:
    def test_valid_event_type_is_added(self) -> None:
        session = _StubSession()
        svc = BadgeEventService(db=session)  # type: ignore[arg-type]
        svc.record(tenant_id=uuid4(), event_type="issued", badge_class_id=uuid4())
        assert len(session.added) == 1

    def test_unknown_event_type_raises(self) -> None:
        session = _StubSession()
        svc = BadgeEventService(db=session)  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            svc.record(tenant_id=uuid4(), event_type="not_a_real_event")
        assert session.added == []
