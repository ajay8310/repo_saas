"""
Unit tests for app.main — FastAPI app factory and health-check endpoint.

These tests verify:
- The app is created successfully with expected metadata.
- GET /health returns 200 with the expected JSON structure.
- CORS middleware is wired correctly.

Requirements covered: 8.1 (versioned REST API), 14.1 (concurrent requests / basic availability).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

# ---- test env setup --------------------------------------------------------
# Override required env vars before importing app.main so that Settings
# validation does not fail in environments without a real .env file.
import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("S3_BUCKET_NAME", "test-bucket")
os.environ.setdefault(
    "JWT_PRIVATE_KEY",
    # Minimal RSA-2048 private key for tests (not used for real crypto here)
    "-----BEGIN RSA PRIVATE KEY-----\n"
    "MIIEowIBAAKCAQEA2a2rwplBQLzHPZe5TNJT3MHuEIzFGOlSIZPLgIHNnMkMD0jy\n"
    "zAsAKnzJ3RLP0tRZRRYMSqGCEGLEPMBcjEzMpRGCRUGSrFoNfQwDPAOyGG8gkB5t\n"
    "kSLMNdJ7c/0KNRjICUEzw5OJzg/Xz0zSQfBGKAr/vfxlPqjm7HlGvFAtfJBGZnNc\n"
    "PLACEHOLDER_NOT_FOR_REAL_USE==\n"
    "-----END RSA PRIVATE KEY-----",
)
os.environ.setdefault(
    "JWT_PUBLIC_KEY",
    "-----BEGIN PUBLIC KEY-----\n"
    "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA2a2rwplBQLzHPZe5TNJT\n"
    "PLACEHOLDER_NOT_FOR_REAL_USE==\n"
    "-----END PUBLIC KEY-----",
)

# Clear settings cache so our env overrides take effect.
from app.config import get_settings
get_settings.cache_clear()

from app.main import create_app  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client() -> TestClient:
    """Create a synchronous test client for the FastAPI app."""
    test_app = create_app()
    return TestClient(test_app, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestHealthCheck:
    """Tests for GET /health."""

    def test_returns_200(self, client: TestClient) -> None:
        response = client.get("/health")
        assert response.status_code == 200

    def test_content_type_is_json(self, client: TestClient) -> None:
        response = client.get("/health")
        assert "application/json" in response.headers["content-type"]

    def test_body_contains_status_ok(self, client: TestClient) -> None:
        body = client.get("/health").json()
        assert body["status"] == "ok"

    def test_body_contains_service_name(self, client: TestClient) -> None:
        body = client.get("/health").json()
        assert "service" in body
        assert isinstance(body["service"], str)
        assert len(body["service"]) > 0

    def test_body_contains_environment(self, client: TestClient) -> None:
        body = client.get("/health").json()
        assert "environment" in body
        assert body["environment"] in ("development", "staging", "production")

    def test_body_contains_timestamp(self, client: TestClient) -> None:
        body = client.get("/health").json()
        assert "timestamp" in body
        assert isinstance(body["timestamp"], int)
        assert body["timestamp"] > 0


class TestOpenAPISpec:
    """Tests for the OpenAPI spec endpoint (Requirement 8.5)."""

    def test_openapi_json_accessible(self, client: TestClient) -> None:
        settings = get_settings()
        response = client.get(f"{settings.api_v1_prefix}/openapi.json")
        assert response.status_code == 200

    def test_openapi_version_is_3x(self, client: TestClient) -> None:
        settings = get_settings()
        spec = client.get(f"{settings.api_v1_prefix}/openapi.json").json()
        # OpenAPI 3.x uses "openapi" key; FastAPI generates 3.1.x
        assert spec.get("openapi", "").startswith("3.")

    def test_openapi_has_info_title(self, client: TestClient) -> None:
        settings = get_settings()
        spec = client.get(f"{settings.api_v1_prefix}/openapi.json").json()
        assert spec["info"]["title"] == settings.app_name


class TestCORSMiddleware:
    """Tests that CORS headers are present on preflight requests."""

    def test_preflight_returns_cors_headers(self, client: TestClient) -> None:
        # Derive the Origin from the configured allow-list.  Hardcoding an
        # origin made this test depend on the developer's local .env: a
        # deployment that restricts CORS to its own frontend would see
        # Starlette reject the preflight with 400 ("Disallowed CORS origin")
        # and fail a test that is only meant to prove CORS is wired up.
        allowed = get_settings().cors_allowed_origins
        origin = "https://example.com" if "*" in allowed else allowed[0]

        response = client.options(
            "/health",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
            },
        )
        # Either 200 or 204 is acceptable for an OPTIONS preflight
        assert response.status_code in (200, 204)
        assert "access-control-allow-origin" in response.headers


class TestAppMetadata:
    """Tests that the application is configured with expected metadata."""

    def test_app_has_correct_title(self) -> None:
        settings = get_settings()
        test_app = create_app()
        assert test_app.title == settings.app_name

    def test_api_prefix_matches_settings(self) -> None:
        settings = get_settings()
        assert settings.api_v1_prefix == "/api/v1"
