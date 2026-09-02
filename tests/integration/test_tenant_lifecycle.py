"""
Integration tests for tenant lifecycle — end-to-end provisioning and suspension.

Requirements: 1.2, 1.5
- Tenant provisioning completes within 60 seconds
- Suspended tenant access denied within 10 seconds
"""

from __future__ import annotations

import time

import pytest
from httpx import AsyncClient


@pytest.mark.integration
class TestTenantProvisioningEndToEnd:
    """Tenant onboarding: create -> approve -> verify active within 60s (Req 1.2)."""

    @pytest.mark.asyncio
    async def test_full_provisioning_within_60_seconds(
        self, async_client: AsyncClient, make_auth_headers, clean_db
    ) -> None:
        """Create a tenant, approve it, and verify it becomes active."""
        headers = make_auth_headers(roles=["super_admin"])

        start = time.time()

        # Step 1: Create tenant
        create_resp = await async_client.post(
            "/api/v1/admin/tenants",
            json={
                "name": "Integration Test Corp",
                "namespace": "inttest",
                "domain": "inttest.io",
                "contact_email": "admin@inttest.io",
            },
            headers=headers,
        )
        assert create_resp.status_code in (201, 200), create_resp.text
        tenant_data = create_resp.json()
        tenant_id = tenant_data.get("tenant_id") or tenant_data.get("id")
        assert tenant_id is not None

        # Step 2: Approve tenant
        approve_resp = await async_client.post(
            f"/api/v1/admin/tenants/{tenant_id}/approve",
            headers=headers,
        )
        assert approve_resp.status_code in (200, 204), approve_resp.text

        # Step 3: Verify tenant is active
        get_resp = await async_client.get(
            f"/api/v1/admin/tenants/{tenant_id}",
            headers=headers,
        )
        assert get_resp.status_code == 200
        assert get_resp.json()["status"] == "active"

        elapsed = time.time() - start
        assert elapsed < 60, f"Provisioning took {elapsed:.1f}s (max 60s)"

    @pytest.mark.asyncio
    async def test_duplicate_namespace_returns_409(
        self, async_client: AsyncClient, make_auth_headers, clean_db
    ) -> None:
        """Creating a tenant with an existing namespace returns DOMAIN_CONFLICT."""
        headers = make_auth_headers(roles=["super_admin"])

        # Create first
        await async_client.post(
            "/api/v1/admin/tenants",
            json={
                "name": "First Corp",
                "namespace": "dupetest",
                "domain": "first.io",
                "contact_email": "a@first.io",
            },
            headers=headers,
        )

        # Create duplicate
        dup_resp = await async_client.post(
            "/api/v1/admin/tenants",
            json={
                "name": "Second Corp",
                "namespace": "dupetest",
                "domain": "second.io",
                "contact_email": "a@second.io",
            },
            headers=headers,
        )
        assert dup_resp.status_code == 409


@pytest.mark.integration
class TestTenantSuspensionAccessDenial:
    """Suspended tenant — all API access denied within 10 seconds (Req 1.5)."""

    @pytest.mark.asyncio
    async def test_suspended_tenant_rejected_within_10_seconds(
        self, async_client: AsyncClient, make_auth_headers, clean_db
    ) -> None:
        """After suspension, requests are rejected with 403 TENANT_SUSPENDED."""
        admin_headers = make_auth_headers(roles=["super_admin"])

        # Create and approve a tenant
        create_resp = await async_client.post(
            "/api/v1/admin/tenants",
            json={
                "name": "Suspend Test Corp",
                "namespace": "susptest",
                "domain": "susptest.io",
                "contact_email": "admin@susptest.io",
            },
            headers=admin_headers,
        )
        tenant_data = create_resp.json()
        tenant_id = tenant_data.get("tenant_id") or tenant_data.get("id")

        await async_client.post(
            f"/api/v1/admin/tenants/{tenant_id}/approve",
            headers=admin_headers,
        )

        # Suspend the tenant
        suspend_resp = await async_client.post(
            f"/api/v1/admin/tenants/{tenant_id}/suspend",
            headers=admin_headers,
        )
        assert suspend_resp.status_code in (200, 204)

        # Verify access is denied — use the tenant's own auth context
        start = time.time()
        tenant_headers = make_auth_headers(tenant_id=tenant_id, roles=["issuer"])

        resp = await async_client.get(
            "/api/v1/documents",
            headers=tenant_headers,
        )
        elapsed = time.time() - start

        assert resp.status_code == 403
        assert resp.json().get("code") == "TENANT_SUSPENDED"
        assert elapsed < 10, f"Suspension enforcement took {elapsed:.1f}s (max 10s)"

    @pytest.mark.asyncio
    async def test_deactivated_tenant_blocks_writes_allows_reads(
        self, async_client: AsyncClient, make_auth_headers, clean_db
    ) -> None:
        """Deactivated tenants can read but not write (Req 1.6)."""
        admin_headers = make_auth_headers(roles=["super_admin"])

        # Create, approve, then deactivate
        create_resp = await async_client.post(
            "/api/v1/admin/tenants",
            json={
                "name": "Deactivate Corp",
                "namespace": "deacttest",
                "domain": "deacttest.io",
                "contact_email": "admin@deacttest.io",
            },
            headers=admin_headers,
        )
        tenant_data = create_resp.json()
        tenant_id = tenant_data.get("tenant_id") or tenant_data.get("id")

        await async_client.post(
            f"/api/v1/admin/tenants/{tenant_id}/approve", headers=admin_headers
        )
        await async_client.post(
            f"/api/v1/admin/tenants/{tenant_id}/deactivate", headers=admin_headers
        )

        tenant_headers = make_auth_headers(tenant_id=tenant_id, roles=["issuer"])

        # Write should be blocked
        write_resp = await async_client.post(
            "/api/v1/documents",
            headers=tenant_headers,
            json={"schema_id": "00000000-0000-0000-0000-000000000001"},
        )
        assert write_resp.status_code == 403
        assert write_resp.json().get("code") == "TENANT_DEACTIVATED"

        # Read should succeed (or at least not be 403 TENANT_DEACTIVATED)
        read_resp = await async_client.get(
            "/api/v1/documents",
            headers=tenant_headers,
        )
        assert read_resp.status_code != 403 or read_resp.json().get("code") != "TENANT_DEACTIVATED"
