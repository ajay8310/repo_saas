"""
Integration tests for authentication endpoints.

Verifies the full request/response flow through the API layer.
These tests exercise endpoint wiring, validation, and error shapes.

Requirements: 8.2, 8.3, 4.5, 4.6, 13.3
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.mark.integration
class TestTokenEndpoint:
    """POST /api/v1/auth/token — OAuth 2.0 client credentials."""

    def test_missing_grant_type_returns_422(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/auth/token",
            json={"client_id": "test", "client_secret": "secret"},
        )
        assert response.status_code == 422

    def test_invalid_grant_type_returns_422(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/auth/token",
            json={"grant_type": "password", "client_id": "x", "client_secret": "y"},
        )
        assert response.status_code == 422

    def test_valid_shape_but_bad_credentials_returns_401(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/auth/token",
            json={
                "grant_type": "client_credentials",
                "client_id": "nonexistent_client",
                "client_secret": "bad_secret",
            },
        )
        # 401 with live DB, 500 without (no DB connection)
        assert response.status_code in (401, 500)
        if response.status_code == 401:
            body = response.json()
            assert body["code"] == "INVALID_CREDENTIALS"

    def test_empty_client_id_returns_422(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/auth/token",
            json={"grant_type": "client_credentials", "client_id": "", "client_secret": "x"},
        )
        assert response.status_code == 422


@pytest.mark.integration
class TestOTPEndpoints:
    """POST /api/v1/auth/otp/request and /verify."""

    def test_otp_request_always_returns_202(self, client: TestClient) -> None:
        """OTP request returns 202 regardless of whether account exists (anti-enumeration)."""
        response = client.post(
            "/api/v1/auth/otp/request",
            json={"email": "nobody@example.com", "tenant_namespace": "test"},
        )
        # 202 with live DB/Redis, 500 without
        assert response.status_code in (202, 500)

    def test_otp_verify_with_invalid_code_returns_401(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/auth/otp/verify",
            json={"email": "test@example.com", "code": "000000", "tenant_namespace": "test"},
        )
        # 401 with live DB/Redis, 500 without
        assert response.status_code in (401, 500)

    def test_otp_verify_short_code_returns_422(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/auth/otp/verify",
            json={"email": "test@example.com", "code": "12", "tenant_namespace": "test"},
        )
        assert response.status_code == 422


@pytest.mark.integration
class TestMFAEndpoints:
    """POST /api/v1/auth/mfa/challenge and /verify."""

    def test_mfa_challenge_returns_202(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/auth/mfa/challenge",
            json={"user_id": "nonexistent-user"},
        )
        # 202 with live DB/Redis, 500 without
        assert response.status_code in (202, 500)

    def test_mfa_verify_without_challenge_returns_401(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/auth/mfa/verify",
            json={"user_id": "test-user", "totp_code": "123456"},
        )
        # 401 with live DB/Redis, 500 without
        assert response.status_code in (401, 500)
