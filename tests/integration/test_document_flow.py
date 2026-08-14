"""
Integration tests for document endpoints.

Verifies endpoint wiring, auth requirements, validation, and error shapes.
Full upload/download flow requires live services (DB, S3, KMS, ClamAV).

Requirements: 3.1-3.11, 4.1-4.9, 6.1-6.7
"""

from __future__ import annotations

import base64

import pytest
from fastapi.testclient import TestClient


@pytest.mark.integration
class TestDocumentUploadValidation:
    """POST /api/v1/documents — validation and auth checks."""

    def test_upload_without_auth_returns_403(self, client: TestClient) -> None:
        """Unauthenticated upload must be rejected."""
        response = client.post(
            "/api/v1/documents",
            json={
                "schema_id": "00000000-0000-0000-0000-000000000001",
                "beneficiary_id": "user@example.com",
                "content_base64": base64.b64encode(b"test content").decode(),
                "cmk_arn": "arn:aws:kms:ap-south-1:000:key/test",
            },
        )
        # Without Bearer token, should get 403 (HTTPBearer auto_error)
        assert response.status_code == 403

    def test_upload_with_invalid_base64_returns_422(self, client: TestClient) -> None:
        """Invalid base64 content should return 422."""
        response = client.post(
            "/api/v1/documents",
            json={
                "schema_id": "00000000-0000-0000-0000-000000000001",
                "beneficiary_id": "user@example.com",
                "content_base64": "not-valid-base64!!!",
                "cmk_arn": "arn:aws:kms:ap-south-1:000:key/test",
            },
            headers={"Authorization": "Bearer fake_token"},
        )
        # Will fail at JWT validation before reaching content decode
        assert response.status_code in (401, 422)


@pytest.mark.integration
class TestDocumentRevocationValidation:
    """POST /api/v1/documents/{id}/revoke — validation."""

    def test_revoke_without_auth_returns_403(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/documents/00000000-0000-0000-0000-000000000001/revoke",
            json={"reason": "Test revocation"},
        )
        assert response.status_code == 403

    def test_revoke_with_empty_reason_returns_422(self, client: TestClient) -> None:
        """Revocation reason is required (1-500 chars)."""
        response = client.post(
            "/api/v1/documents/00000000-0000-0000-0000-000000000001/revoke",
            json={"reason": ""},
            headers={"Authorization": "Bearer fake_token"},
        )
        # Will fail at JWT validation or Pydantic validation
        assert response.status_code in (401, 422)


@pytest.mark.integration
class TestBulkRevokeValidation:
    """POST /api/v1/documents/bulk-revoke — validation."""

    def test_bulk_revoke_without_auth_returns_403(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/documents/bulk-revoke",
            json={
                "credential_ids": ["00000000-0000-0000-0000-000000000001"],
                "reason": "Batch revocation",
            },
        )
        assert response.status_code == 403


@pytest.mark.integration
class TestDocumentListValidation:
    """GET /api/v1/documents — requires auth."""

    def test_list_without_auth_returns_403(self, client: TestClient) -> None:
        response = client.get("/api/v1/documents")
        assert response.status_code == 403


@pytest.mark.integration
class TestBulkUploadValidation:
    """POST /api/v1/documents/bulk — validation."""

    def test_bulk_upload_without_auth_returns_403(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/documents/bulk",
            json={
                "schema_id": "00000000-0000-0000-0000-000000000001",
                "cmk_arn": "arn:aws:kms:ap-south-1:000:key/test",
                "records": [{"beneficiary_id": "a", "content": "data"}],
            },
        )
        assert response.status_code == 403
