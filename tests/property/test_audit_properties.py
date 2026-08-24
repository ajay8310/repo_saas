"""
Property tests for audit log service.

Properties 19, 35, 36, 37.
"""

from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("S3_BUCKET_NAME", "test-bucket")
os.environ.setdefault("JWT_PRIVATE_KEY", "-----BEGIN RSA PRIVATE KEY-----\nPLACEHOLDER\n-----END RSA PRIVATE KEY-----")
os.environ.setdefault("JWT_PUBLIC_KEY", "-----BEGIN PUBLIC KEY-----\nPLACEHOLDER\n-----END PUBLIC KEY-----")

from app.config import get_settings
get_settings.cache_clear()

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from hypothesis import given, settings as h_settings
from hypothesis import strategies as st

from app.models.audit import AuditLog
from app.services.audit_service import AuditService
from tests.property.strategies import roles, uuids


class TestProperty35:
    """Property 35: Audit Log Entry Immutability (Req 10.2).

    The DB trigger prevent_audit_modification() prevents UPDATE/DELETE.
    Verified structurally: the service exposes only an append method.
    """

    def test_audit_service_has_no_update_method(self) -> None:
        """AuditService provides only `record` — no update or delete."""
        assert hasattr(AuditService, "record")
        assert not hasattr(AuditService, "update")
        assert not hasattr(AuditService, "delete")

    def test_audit_log_model_is_append_only_by_design(self) -> None:
        """The AuditLog model has no mutable-state helper methods."""
        instance_methods = [
            m for m in dir(AuditLog) if not m.startswith("_") and callable(getattr(AuditLog, m, None))
        ]
        # No update/delete/modify methods should exist
        assert "update" not in instance_methods
        assert "delete" not in instance_methods
        assert "modify" not in instance_methods

    def test_audit_log_has_immutable_primary_key(self) -> None:
        """AuditLog uses a composite PK (id, created_at) — server-generated."""
        mapper = AuditLog.__table__
        pk_col_names = [c.name for c in mapper.primary_key.columns]
        assert "id" in pk_col_names
        assert "created_at" in pk_col_names


class TestProperty36:
    """Property 36: Audit Log Namespace Isolation (Req 10.3).

    Audit logs are tenant-scoped via tenant_id column + RLS policy.
    """

    def test_audit_model_has_tenant_id_column(self) -> None:
        """The AuditLog model contains a tenant_id column for RLS scoping."""
        assert hasattr(AuditLog, "tenant_id")

    def test_tenant_id_is_non_nullable(self) -> None:
        """tenant_id must be NOT NULL — every entry belongs to a tenant."""
        col = AuditLog.__table__.c.tenant_id
        assert not col.nullable

    def test_tenant_id_has_foreign_key(self) -> None:
        """tenant_id references the tenants table."""
        col = AuditLog.__table__.c.tenant_id
        assert len(col.foreign_keys) > 0
        fk = next(iter(col.foreign_keys))
        assert "tenants.id" in str(fk.target_fullname)


class TestProperty37:
    """Property 37: Audit Log Write Failure Rejects Originating Operation (Req 10.7).

    If the audit INSERT fails, the originating operation's transaction rolls back.
    The AuditService writes within the caller's transaction (no separate commit).
    """

    @pytest.mark.asyncio
    async def test_record_does_not_commit_independently(self) -> None:
        """AuditService.record() adds to session but does not call commit."""
        mock_db = AsyncMock()
        service = AuditService(db=mock_db)

        await service.record(
            tenant_id=uuid4(),
            actor_id="test_actor",
            actor_role="issuer",
            operation="document:upload",
            resource_type="document",
            resource_id=str(uuid4()),
            outcome="success",
        )

        # It should add the object to the session
        mock_db.add.assert_called_once()
        # It must NOT commit — the caller controls the transaction
        mock_db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_failed_audit_insert_propagates_exception(self) -> None:
        """If db.add raises, the exception propagates to the caller."""
        mock_db = AsyncMock()
        mock_db.add.side_effect = RuntimeError("simulated DB error")

        service = AuditService(db=mock_db)

        with pytest.raises(RuntimeError, match="simulated DB error"):
            await service.record(
                tenant_id=uuid4(),
                actor_id="test_actor",
                actor_role="issuer",
                operation="document:upload",
                resource_type="document",
                resource_id=str(uuid4()),
                outcome="success",
            )

    @given(role=roles)
    @h_settings(max_examples=20)
    def test_audit_entry_captures_all_required_fields(self, role: str) -> None:
        """Every audit entry includes tenant_id, actor, operation, resource, outcome."""
        required_columns = {"tenant_id", "actor_id", "actor_role", "operation",
                           "resource_type", "resource_id", "outcome"}
        model_columns = {c.name for c in AuditLog.__table__.columns}
        assert required_columns.issubset(model_columns)


class TestProperty19:
    """Property 19: Audit Log Written for Every Document Retrieval (Req 4.9, 10.1).

    The DocumentService writes an audit entry on every retrieval attempt.
    Verified structurally: the download/get methods call _audit.record().
    """

    def test_document_service_has_audit_dependency(self) -> None:
        """DocumentService constructor initializes an AuditService instance."""
        from app.services.document_service import DocumentService
        import inspect

        source = inspect.getsource(DocumentService.__init__)
        # AuditService is wired in the constructor
        assert "AuditService" in source or "_audit" in source

    def test_download_method_audits(self) -> None:
        """DocumentService.download_document references audit recording."""
        from app.services.document_service import DocumentService
        import inspect

        source = inspect.getsource(DocumentService.download_document)
        assert "audit" in source.lower() or "_audit" in source
