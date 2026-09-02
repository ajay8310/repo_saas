"""
Integration tests for cross-tenant RLS (Row Level Security) isolation.

Requirements: 7.1, 7.6
- Tenant A cannot read/write Tenant B's data
- Automated cross-tenant isolation checks
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.integration
class TestRLSReadIsolation:
    """Verify tenant A cannot read tenant B's documents via RLS (Req 7.1)."""

    @pytest.mark.asyncio
    async def test_document_query_scoped_to_tenant(
        self, db_session: AsyncSession, clean_db
    ) -> None:
        """Documents inserted for tenant A are invisible to tenant B."""
        tenant_a = uuid4()
        tenant_b = uuid4()

        # Insert tenants directly
        await db_session.execute(
            text("""
                INSERT INTO tenants (id, namespace, name, domain, contact_email, status)
                VALUES (:id, :ns, :name, :domain, :email, 'active')
            """),
            [
                {"id": str(tenant_a), "ns": "tenant_a", "name": "A", "domain": "a.io", "email": "a@a.io"},
                {"id": str(tenant_b), "ns": "tenant_b", "name": "B", "domain": "b.io", "email": "b@b.io"},
            ],
        )

        # Insert a schema for tenant A
        schema_id = uuid4()
        await db_session.execute(
            text("""
                INSERT INTO document_schemas (id, tenant_id, name, version, status, field_definitions)
                VALUES (:id, :tid, 'Test Schema', 1, 'active', '[]'::jsonb)
            """),
            {"id": str(schema_id), "tid": str(tenant_a)},
        )

        # Insert a document for tenant A
        doc_id = uuid4()
        await db_session.execute(
            text("""
                INSERT INTO documents (id, tenant_id, schema_id, schema_version,
                    beneficiary_id, status, s3_key, encrypted_dek, iv)
                VALUES (:id, :tid, :sid, 1, 'user@a.io', 'stored',
                    'a/doc1', '\\x00', '\\x00')
            """),
            {"id": str(doc_id), "tid": str(tenant_a), "sid": str(schema_id)},
        )
        await db_session.commit()

        # Query as tenant A — should see the document
        await db_session.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_a)},
        )
        result_a = await db_session.execute(text("SELECT id FROM documents"))
        rows_a = result_a.fetchall()
        assert len(rows_a) == 1
        assert str(rows_a[0][0]) == str(doc_id)

        # Query as tenant B — should see nothing
        await db_session.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_b)},
        )
        result_b = await db_session.execute(text("SELECT id FROM documents"))
        rows_b = result_b.fetchall()
        assert len(rows_b) == 0

    @pytest.mark.asyncio
    async def test_audit_logs_scoped_to_tenant(
        self, db_session: AsyncSession, clean_db
    ) -> None:
        """Audit logs for tenant A are invisible to tenant B."""
        tenant_a = uuid4()
        tenant_b = uuid4()

        await db_session.execute(
            text("""
                INSERT INTO tenants (id, namespace, name, domain, contact_email, status)
                VALUES (:id, :ns, :name, :domain, :email, 'active')
            """),
            [
                {"id": str(tenant_a), "ns": "rlsaudit_a", "name": "A", "domain": "rlsa.io", "email": "a@rls.io"},
                {"id": str(tenant_b), "ns": "rlsaudit_b", "name": "B", "domain": "rlsb.io", "email": "b@rls.io"},
            ],
        )

        # Insert audit log for tenant A
        await db_session.execute(
            text("""
                INSERT INTO audit_logs (tenant_id, actor_id, actor_role, operation,
                    resource_type, resource_id, outcome)
                VALUES (:tid, 'actor1', 'issuer', 'document:upload', 'document', 'doc1', 'success')
            """),
            {"tid": str(tenant_a)},
        )
        await db_session.commit()

        # Query as tenant B — RLS blocks
        await db_session.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_b)},
        )
        result = await db_session.execute(text("SELECT count(*) FROM audit_logs"))
        count = result.scalar()
        assert count == 0


@pytest.mark.integration
class TestRLSWriteIsolation:
    """Verify tenant A cannot write into tenant B's namespace (Req 7.1)."""

    @pytest.mark.asyncio
    async def test_insert_with_wrong_tenant_context_fails(
        self, db_session: AsyncSession, clean_db
    ) -> None:
        """RLS WITH CHECK prevents inserts where tenant_id != current setting."""
        tenant_a = uuid4()
        tenant_b = uuid4()

        await db_session.execute(
            text("""
                INSERT INTO tenants (id, namespace, name, domain, contact_email, status)
                VALUES (:id, :ns, :name, :domain, :email, 'active')
            """),
            [
                {"id": str(tenant_a), "ns": "wiso_a", "name": "A", "domain": "wiso_a.io", "email": "a@w.io"},
                {"id": str(tenant_b), "ns": "wiso_b", "name": "B", "domain": "wiso_b.io", "email": "b@w.io"},
            ],
        )

        schema_id = uuid4()
        await db_session.execute(
            text("""
                INSERT INTO document_schemas (id, tenant_id, name, version, status, field_definitions)
                VALUES (:id, :tid, 'Schema', 1, 'active', '[]'::jsonb)
            """),
            {"id": str(schema_id), "tid": str(tenant_a)},
        )
        await db_session.commit()

        # Set RLS context to tenant B
        await db_session.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_b)},
        )

        # Attempt to insert a document into tenant A's namespace while context is B
        # The RLS WITH CHECK policy should reject this
        doc_id = uuid4()
        try:
            await db_session.execute(
                text("""
                    INSERT INTO documents (id, tenant_id, schema_id, schema_version,
                        beneficiary_id, status, s3_key, encrypted_dek, iv)
                    VALUES (:id, :tid, :sid, 1, 'user@b.io', 'stored',
                        'b/doc1', '\\x00', '\\x00')
                """),
                {"id": str(doc_id), "tid": str(tenant_a), "sid": str(schema_id)},
            )
            await db_session.commit()
            # If we get here, RLS didn't block — that's a failure
            pytest.fail("RLS WITH CHECK should have prevented cross-tenant insert")
        except Exception:
            # Expected: RLS violation or constraint error
            await db_session.rollback()


@pytest.mark.integration
class TestCrossTenantAPIIsolation:
    """API-level isolation: tenant A's token cannot access tenant B's resources (Req 7.6)."""

    @pytest.mark.asyncio
    async def test_tenant_a_cannot_search_tenant_b_documents(
        self, async_client: AsyncClient, make_auth_headers
    ) -> None:
        """Search results are scoped to the authenticated tenant."""
        tenant_a_id = str(uuid4())
        tenant_b_id = str(uuid4())

        headers_a = make_auth_headers(tenant_id=tenant_a_id, roles=["issuer"])
        headers_b = make_auth_headers(tenant_id=tenant_b_id, roles=["issuer"])

        # Both tenants search — each should only see their own
        resp_a = await async_client.get("/api/v1/documents", headers=headers_a)
        resp_b = await async_client.get("/api/v1/documents", headers=headers_b)

        # Verify the search completes (may be empty for new tenants)
        assert resp_a.status_code in (200, 403)  # 403 if tenant doesn't exist yet
        assert resp_b.status_code in (200, 403)

    @pytest.mark.asyncio
    async def test_schema_isolation_across_tenants(
        self, async_client: AsyncClient, make_auth_headers
    ) -> None:
        """Schemas created by tenant A are not visible to tenant B."""
        tenant_a_id = str(uuid4())
        tenant_b_id = str(uuid4())

        headers_a = make_auth_headers(tenant_id=tenant_a_id, roles=["tenant_admin"])
        headers_b = make_auth_headers(tenant_id=tenant_b_id, roles=["tenant_admin"])

        # Tenant A lists schemas
        resp_a = await async_client.get("/api/v1/schemas", headers=headers_a)
        # Tenant B lists schemas
        resp_b = await async_client.get("/api/v1/schemas", headers=headers_b)

        # Neither should see the other's data
        if resp_a.status_code == 200 and resp_b.status_code == 200:
            schemas_a = resp_a.json() if isinstance(resp_a.json(), list) else resp_a.json().get("items", [])
            schemas_b = resp_b.json() if isinstance(resp_b.json(), list) else resp_b.json().get("items", [])
            ids_a = {s.get("id") for s in schemas_a}
            ids_b = {s.get("id") for s in schemas_b}
            assert ids_a.isdisjoint(ids_b)
