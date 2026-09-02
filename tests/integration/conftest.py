"""
Integration test fixtures.

These tests require Docker Compose services (PostgreSQL, Redis, LocalStack, ClamAV).
Start environment:
    docker compose -f docker-compose.test.yml up -d
Run tests:
    pytest tests/integration/ -m integration
"""

from __future__ import annotations

import os

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

# ---------------------------------------------------------------------------
# Generate real RSA keys for JWT tests
# ---------------------------------------------------------------------------

_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PRIV_PEM = _private_key.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption(),
).decode()
_PUB_PEM = _private_key.public_key().public_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PublicFormat.SubjectPublicKeyInfo,
).decode()

# ---------------------------------------------------------------------------
# Environment — points at docker-compose.test.yml services
# ---------------------------------------------------------------------------

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test_user:test_pass@localhost:5433/test_reposaaas")
os.environ.setdefault("SYNC_DATABASE_URL", "postgresql://test_user:test_pass@localhost:5433/test_reposaaas")
os.environ.setdefault("REDIS_URL", "redis://localhost:6380/0")
os.environ.setdefault("S3_BUCKET_NAME", "test-documents")
os.environ.setdefault("S3_ENDPOINT_URL", "http://localhost:4567")
os.environ.setdefault("KMS_ENDPOINT_URL", "http://localhost:4567")
os.environ.setdefault("SES_ENDPOINT_URL", "http://localhost:4567")
os.environ.setdefault("SNS_ENDPOINT_URL", "http://localhost:4567")
os.environ.setdefault("CLAMAV_HOST", "localhost")
os.environ.setdefault("CLAMAV_PORT", "3311")
os.environ.setdefault("AWS_REGION", "ap-south-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("CELERY_BROKER_URL", "redis://localhost:6380/0")
os.environ.setdefault("CELERY_RESULT_BACKEND", "redis://localhost:6380/0")
os.environ["JWT_PRIVATE_KEY"] = _PRIV_PEM
os.environ["JWT_PUBLIC_KEY"] = _PUB_PEM

from app.config import get_settings

get_settings.cache_clear()

import asyncio
from collections.abc import AsyncGenerator, Generator
from datetime import UTC
from uuid import uuid4

import boto3
import pytest
import pytest_asyncio
import redis.asyncio as aioredis
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import Settings
from app.main import create_app

# ---------------------------------------------------------------------------
# Core fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def event_loop() -> Generator:
    """Create a session-scoped event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def settings() -> Settings:
    """Resolved application settings for the test environment."""
    return get_settings()


@pytest.fixture(scope="session")
def app():
    """Create the FastAPI app for integration tests."""
    return create_app()


@pytest.fixture(scope="session")
def sync_client(app):
    """Synchronous test client (for simple health-check style tests)."""
    from fastapi.testclient import TestClient

    return TestClient(app, raise_server_exceptions=False)


@pytest_asyncio.fixture(scope="session")
async def async_client(app) -> AsyncGenerator[AsyncClient, None]:
    """Async HTTP client for testing API endpoints."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


# ---------------------------------------------------------------------------
# Database fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="session")
async def db_engine(settings):
    """Async SQLAlchemy engine connected to test database."""
    engine = create_async_engine(
        settings.database_url,
        echo=False,
        pool_size=5,
        max_overflow=10,
    )
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="session")
async def session_factory(db_engine):
    """Session factory for creating test DB sessions."""
    return async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def db_session(session_factory) -> AsyncGenerator[AsyncSession, None]:
    """Per-test database session with automatic rollback."""
    async with session_factory() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def clean_db(db_engine):
    """Truncate all application tables before a test (use sparingly)."""
    async with db_engine.begin() as conn:
        # Truncate in dependency order
        await conn.execute(text("""
            TRUNCATE TABLE webhook_events, webhooks,
                          verification_tokens, digilocker_pushes,
                          notification_preferences,
                          documents, bulk_jobs,
                          schema_versions, document_schemas,
                          audit_logs,
                          api_clients, tenant_encryption_keys,
                          user_accounts, tenants
            CASCADE
        """))
    yield


# ---------------------------------------------------------------------------
# Redis fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="session")
async def redis_client(settings) -> AsyncGenerator[aioredis.Redis, None]:
    """Async Redis client connected to test Redis."""
    client = aioredis.from_url(settings.redis_url, decode_responses=True)
    yield client
    await client.aclose()


@pytest_asyncio.fixture
async def clean_redis(redis_client):
    """Flush test Redis before a test."""
    await redis_client.flushdb()
    yield redis_client


# ---------------------------------------------------------------------------
# LocalStack / AWS fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def s3_client(settings):
    """Boto3 S3 client pointing at LocalStack."""
    return boto3.client(
        "s3",
        region_name=settings.aws_region,
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )


@pytest.fixture(scope="session")
def kms_client(settings):
    """Boto3 KMS client pointing at LocalStack."""
    return boto3.client(
        "kms",
        region_name=settings.aws_region,
        endpoint_url=settings.kms_endpoint_url,
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )


@pytest.fixture(scope="session")
def ses_client(settings):
    """Boto3 SES client pointing at LocalStack."""
    return boto3.client(
        "ses",
        region_name=settings.aws_region,
        endpoint_url=settings.ses_endpoint_url,
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )


@pytest.fixture(scope="session")
def sns_client(settings):
    """Boto3 SNS client pointing at LocalStack."""
    return boto3.client(
        "sns",
        region_name=settings.aws_region,
        endpoint_url=settings.sns_endpoint_url,
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )


@pytest.fixture(scope="session", autouse=True)
def setup_s3_bucket(s3_client, settings):
    """Ensure the test S3 bucket exists."""
    try:
        s3_client.create_bucket(
            Bucket=settings.s3_bucket_name,
            CreateBucketConfiguration={"LocationConstraint": settings.aws_region},
        )
    except s3_client.exceptions.BucketAlreadyOwnedByYou:
        pass
    except Exception:
        pass  # LocalStack may already have it


@pytest.fixture(scope="session")
def kms_key_arn(kms_client) -> str:
    """Create a test KMS key and return its ARN."""
    response = kms_client.create_key(
        Description="Test key for integration tests",
        KeyUsage="ENCRYPT_DECRYPT",
    )
    return response["KeyMetadata"]["Arn"]


# ---------------------------------------------------------------------------
# Auth helper fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def auth_headers(settings) -> dict[str, str]:
    """Generate a valid JWT bearer token for a test tenant."""
    from datetime import datetime, timedelta

    from jose import jwt as jose_jwt

    tenant_id = str(uuid4())
    now = datetime.now(UTC)
    claims = {
        "sub": "test_client",
        "tenant_id": tenant_id,
        "roles": ["tenant_admin", "issuer"],
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=1)).timestamp()),
    }
    token = jose_jwt.encode(claims, _PRIV_PEM, algorithm="RS256")
    return {
        "Authorization": f"Bearer {token}",
        "X-Tenant-ID": tenant_id,
    }


@pytest.fixture
def make_auth_headers(settings):
    """Factory for generating auth headers with specific tenant/role."""

    def _make(tenant_id: str | None = None, roles: list[str] | None = None) -> dict[str, str]:
        from datetime import datetime, timedelta

        from jose import jwt as jose_jwt

        tid = tenant_id or str(uuid4())
        now = datetime.now(UTC)
        claims = {
            "sub": "test_client",
            "tenant_id": tid,
            "roles": roles or ["tenant_admin"],
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(hours=1)).timestamp()),
        }
        token = jose_jwt.encode(claims, _PRIV_PEM, algorithm="RS256")
        return {
            "Authorization": f"Bearer {token}",
            "X-Tenant-ID": tid,
        }

    return _make


# ---------------------------------------------------------------------------
# Celery fixtures (for task execution tests)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def celery_config():
    """Celery configuration pointing at test Redis."""
    return {
        "broker_url": os.environ["CELERY_BROKER_URL"],
        "result_backend": os.environ["CELERY_RESULT_BACKEND"],
        "task_always_eager": True,  # Execute tasks synchronously in tests
        "task_eager_propagates": True,
    }


@pytest.fixture(scope="session")
def celery_app(celery_config):
    """Celery app configured for test mode (eager execution)."""
    from app.tasks.celery_app import celery_app as app

    app.conf.update(celery_config)
    return app
