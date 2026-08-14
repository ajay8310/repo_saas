"""
Integration test fixtures.

These tests require Docker Compose services (PostgreSQL, Redis, LocalStack).
Run with: pytest tests/integration/ -m integration
"""

from __future__ import annotations

import os

# Integration test environment
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://reposaaas:reposaaas@localhost:5432/reposaaas")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("S3_BUCKET_NAME", "reposaaas-documents-dev")
os.environ.setdefault("S3_ENDPOINT_URL", "http://localhost:4566")
os.environ.setdefault("KMS_ENDPOINT_URL", "http://localhost:4566")
os.environ.setdefault("CLAMAV_HOST", "localhost")
os.environ.setdefault("CLAMAV_PORT", "3310")
os.environ.setdefault(
    "JWT_PRIVATE_KEY",
    "-----BEGIN RSA PRIVATE KEY-----\nPLACEHOLDER\n-----END RSA PRIVATE KEY-----",
)
os.environ.setdefault(
    "JWT_PUBLIC_KEY",
    "-----BEGIN PUBLIC KEY-----\nPLACEHOLDER\n-----END PUBLIC KEY-----",
)

from app.config import get_settings
get_settings.cache_clear()

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture(scope="session")
def app():
    """Create the FastAPI app for integration tests."""
    return create_app()


@pytest.fixture(scope="session")
def client(app) -> TestClient:
    """Synchronous test client for the full app."""
    return TestClient(app, raise_server_exceptions=False)
