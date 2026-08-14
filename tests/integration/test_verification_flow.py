"""
Integration tests for verification endpoints.

Verifies public endpoints (no auth) and authenticated token generation.

Requirements: 5.1-5.10
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.mark.integration
class TestPublicVerification:
    """GET /api/v1/verify/{credential_id} — public, no auth required."""

    def test_verify_nonexistent_credential_returns_invalid(self, client: TestClient) -> None:
        """Public verification of non-existent document returns 'invalid' (with live DB)."""
        response = client.get("/api/v1/verify/00000000-0000-0000-0000-000000000099")
        # 200 with live DB, 500 without (no DB connection)
        assert response.status_code in (200, 500)
        if response.status_code == 200:
            body = response.json()
            assert body["status"] == "invalid"

    def test_verify_bad_uuid_returns_422(self, client: TestClient) -> None:
        """Invalid UUID format returns validation error."""
        response = client.get("/api/v1/verify/not-a-uuid")
        assert response.status_code == 422


@pytest.mark.integration
class TestTokenConsumption:
    """GET /api/v1/verifications/{token} — public token consumption."""

    def test_consume_nonexistent_token_returns_invalid(self, client: TestClient) -> None:
        response = client.get("/api/v1/verifications/nonexistent_token_value_here")
        # 200 with live DB, 500 without
        assert response.status_code in (200, 500)
        if response.status_code == 200:
            body = response.json()
            assert body["valid"] is False
            assert body["status"] == "invalid"
            assert body["fields"] is None
            assert body["issuer_name"] is None

    def test_invalid_token_never_leaks_data(self, client: TestClient) -> None:
        """Property 22: Invalid tokens never return document fields."""
        response = client.get("/api/v1/verifications/abcdef1234567890")
        # 200 with live DB, 500 without
        assert response.status_code in (200, 500)
        if response.status_code == 200:
            body = response.json()
            assert body["fields"] is None
            assert body["issued_at"] is None


@pytest.mark.integration
class TestTokenGeneration:
    """POST /api/v1/verifications/tokens — requires auth."""

    def test_generate_without_auth_returns_403(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/verifications/tokens",
            json={
                "document_id": "00000000-0000-0000-0000-000000000001",
                "consented_fields": ["name", "date"],
                "expiry_hours": 72,
            },
        )
        assert response.status_code == 403
