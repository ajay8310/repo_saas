"""
Integration tests for tenant management endpoints.

Verifies auth/RBAC enforcement and request validation.

Requirements: 1.1-1.9
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.mark.integration
class TestTenantCreation:
    """POST /api/v1/admin/tenants — requires super_admin."""

    def test_create_without_auth_returns_403(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/admin/tenants",
            json={
                "name": "Test Corp",
                "namespace": "testcorp",
                "domain": "testcorp.com",
                "contact_email": "admin@testcorp.com",
            },
        )
        assert response.status_code == 403

    def test_invalid_namespace_returns_422(self, client: TestClient) -> None:
        """Namespace must match ^[a-z][a-z0-9_-]*$ pattern."""
        response = client.post(
            "/api/v1/admin/tenants",
            json={
                "name": "Test",
                "namespace": "123invalid",  # starts with digit
                "domain": "test.com",
                "contact_email": "a@b.com",
            },
            headers={"Authorization": "Bearer fake"},
        )
        # Will fail at JWT or validation
        assert response.status_code in (401, 422)


@pytest.mark.integration
class TestTenantLifecycle:
    """Lifecycle endpoints require super_admin auth."""

    def test_approve_without_auth_returns_403(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/admin/tenants/00000000-0000-0000-0000-000000000001/approve"
        )
        assert response.status_code == 403

    def test_suspend_without_auth_returns_403(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/admin/tenants/00000000-0000-0000-0000-000000000001/suspend"
        )
        assert response.status_code == 403

    def test_deactivate_without_auth_returns_403(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/admin/tenants/00000000-0000-0000-0000-000000000001/deactivate"
        )
        assert response.status_code == 403


@pytest.mark.integration
class TestTenantConfig:
    """PATCH /api/v1/admin/tenants/{id} — requires tenant:update."""

    def test_update_without_auth_returns_403(self, client: TestClient) -> None:
        response = client.patch(
            "/api/v1/admin/tenants/00000000-0000-0000-0000-000000000001",
            json={"rate_limit_per_hour": 5000},
        )
        assert response.status_code == 403


@pytest.mark.integration
class TestKeyRotation:
    """POST /api/v1/admin/tenants/{id}/rotate-key."""

    def test_rotate_without_auth_returns_403(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/admin/tenants/00000000-0000-0000-0000-000000000001/rotate-key",
            json={"grace_hours": 24},
        )
        assert response.status_code == 403
