"""
Integration tests for schema management endpoints.

Requirements: 2.1-2.7
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.mark.integration
class TestSchemaEndpoints:
    """Schema CRUD endpoints require auth + RBAC."""

    def test_create_schema_without_auth_returns_403(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/schemas",
            json={
                "name": "Test Certificate",
                "field_definitions": [
                    {"name": "student_name", "type": "string", "required": True},
                    {"name": "grade", "type": "number", "required": True},
                ],
            },
        )
        assert response.status_code == 403

    def test_list_schemas_without_auth_returns_403(self, client: TestClient) -> None:
        response = client.get("/api/v1/schemas")
        assert response.status_code == 403

    def test_get_schema_without_auth_returns_403(self, client: TestClient) -> None:
        response = client.get("/api/v1/schemas/00000000-0000-0000-0000-000000000001")
        assert response.status_code == 403


@pytest.mark.integration
class TestSearchEndpoint:
    """GET /api/v1/search requires auth."""

    def test_search_without_auth_returns_403(self, client: TestClient) -> None:
        response = client.get("/api/v1/search?q=test")
        assert response.status_code == 403


@pytest.mark.integration
class TestAuditEndpoints:
    """Audit log endpoints require audit:read permission."""

    def test_list_audit_logs_without_auth_returns_403(self, client: TestClient) -> None:
        response = client.get("/api/v1/audit-logs")
        assert response.status_code == 403

    def test_export_audit_logs_without_auth_returns_403(self, client: TestClient) -> None:
        response = client.get("/api/v1/audit-logs/export?format=json")
        assert response.status_code == 403


@pytest.mark.integration
class TestWebhookEndpoints:
    """Webhook endpoints require auth + RBAC."""

    def test_register_webhook_without_auth_returns_403(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/webhooks",
            json={
                "url": "https://example.com/webhook",
                "secret": "a_very_secure_secret_key",
                "event_types": ["document.uploaded"],
            },
        )
        assert response.status_code == 403

    def test_list_webhooks_without_auth_returns_403(self, client: TestClient) -> None:
        response = client.get("/api/v1/webhooks")
        assert response.status_code == 403


@pytest.mark.integration
class TestNotificationEndpoints:
    """Notification preference endpoints require auth."""

    def test_get_preferences_without_auth_returns_403(self, client: TestClient) -> None:
        response = client.get("/api/v1/beneficiaries/me/notification-preferences")
        assert response.status_code == 403

    def test_update_preferences_without_auth_returns_403(self, client: TestClient) -> None:
        response = client.patch(
            "/api/v1/beneficiaries/me/notification-preferences",
            json={"notify_on_issuance": False},
        )
        assert response.status_code == 403
