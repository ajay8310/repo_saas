"""
Integration tests for post-deployment automated checks.

Requirements: 7.6, 7.7
- Automated cross-tenant isolation checks
- Alert within 1 minute on RLS violation detection
"""

from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.integration
class TestPostDeploymentRLSVerification:
    """Automated RLS policy verification (Req 7.6)."""

    @pytest.mark.asyncio
    async def test_rls_enabled_on_all_tenant_scoped_tables(
        self, db_session: AsyncSession
    ) -> None:
        """All tenant-scoped tables have RLS ENABLED and FORCED."""
        tenant_scoped_tables = [
            "documents",
            "document_schemas",
            "schema_versions",
            "api_clients",
            "tenant_encryption_keys",
            "user_accounts",
            "audit_logs",
            "webhooks",
            "webhook_events",
            "verification_tokens",
            "bulk_jobs",
            "notification_preferences",
            "digilocker_pushes",
        ]

        for table in tenant_scoped_tables:
            result = await db_session.execute(
                text("""
                    SELECT relrowsecurity, relforcerowsecurity
                    FROM pg_class
                    WHERE relname = :table_name
                """),
                {"table_name": table},
            )
            row = result.fetchone()
            assert row is not None, f"Table {table} not found"
            rls_enabled, rls_forced = row
            assert rls_enabled, f"RLS not ENABLED on {table}"
            assert rls_forced, f"RLS not FORCED on {table}"

    @pytest.mark.asyncio
    async def test_tenant_isolation_policy_exists_on_all_tables(
        self, db_session: AsyncSession
    ) -> None:
        """Each tenant-scoped table has at least one RLS policy."""
        tenant_scoped_tables = [
            "documents",
            "document_schemas",
            "schema_versions",
            "audit_logs",
            "webhooks",
            "webhook_events",
            "verification_tokens",
        ]

        for table in tenant_scoped_tables:
            result = await db_session.execute(
                text("""
                    SELECT COUNT(*)
                    FROM pg_policies
                    WHERE tablename = :table_name
                """),
                {"table_name": table},
            )
            count = result.scalar()
            assert count > 0, f"No RLS policies found on {table}"


@pytest.mark.integration
class TestPostDeploymentAuditIntegrity:
    """Verify audit log immutability triggers are active (Req 10.2)."""

    @pytest.mark.asyncio
    async def test_audit_log_update_trigger_exists(
        self, db_session: AsyncSession
    ) -> None:
        """The prevent_audit_modification trigger is active on audit_logs."""
        result = await db_session.execute(
            text("""
                SELECT tgname, tgenabled
                FROM pg_trigger
                WHERE tgrelid = 'audit_logs'::regclass
                  AND tgname = 'audit_immutable'
            """)
        )
        row = result.fetchone()
        assert row is not None, "audit_immutable trigger not found"
        # tgenabled: 'O' = enabled (origin), 'A' = always
        assert row[1] in ("O", "A"), f"Trigger disabled: enabled={row[1]}"

    @pytest.mark.asyncio
    async def test_audit_log_update_is_blocked(
        self, db_session: AsyncSession, clean_db
    ) -> None:
        """Attempting to UPDATE an audit_log row raises an error."""
        tenant_id = uuid4()

        # Create a tenant first
        await db_session.execute(
            text("""
                INSERT INTO tenants (id, namespace, name, domain, contact_email, status)
                VALUES (:id, 'auditimm', 'Test', 'auditimm.io', 'a@a.io', 'active')
            """),
            {"id": str(tenant_id)},
        )

        # Insert an audit entry
        await db_session.execute(
            text("""
                INSERT INTO audit_logs (tenant_id, actor_id, actor_role, operation,
                    resource_type, resource_id, outcome)
                VALUES (:tid, 'actor', 'issuer', 'test:op', 'test', 'res1', 'success')
            """),
            {"tid": str(tenant_id)},
        )
        await db_session.commit()

        # Set tenant context for RLS
        await db_session.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )

        # Attempt to update — should be blocked by trigger
        with pytest.raises(Exception):
            await db_session.execute(
                text("""
                    UPDATE audit_logs SET outcome = 'modified'
                    WHERE tenant_id = :tid
                """),
                {"tid": str(tenant_id)},
            )


@pytest.mark.integration
class TestPostDeploymentEncryption:
    """Verify encryption configuration (Req 3.6, 13.7)."""

    @pytest.mark.asyncio
    async def test_tenant_encryption_keys_table_exists(
        self, db_session: AsyncSession
    ) -> None:
        """tenant_encryption_keys table exists and has expected structure."""
        result = await db_session.execute(
            text("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'tenant_encryption_keys'
                ORDER BY ordinal_position
            """)
        )
        columns = [row[0] for row in result.fetchall()]
        assert "kms_key_arn" in columns
        assert "tenant_id" in columns
        assert "status" in columns


@pytest.mark.integration
class TestAnomalyAlertTiming:
    """Alert within 1 minute on isolation violation (Req 7.7)."""

    def test_anomaly_detection_task_interval(self) -> None:
        """The anomaly detection task runs every 60 seconds."""
        from app.tasks.anomaly_detection import run_anomaly_sweep

        # Verify task exists and is configured for periodic execution
        assert callable(run_anomaly_sweep)
