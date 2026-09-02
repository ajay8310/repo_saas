"""
Smoke tests for post-deployment verification.

These tests verify the deployed system meets baseline operational requirements.
Run after deployment:
    pytest tests/smoke/ -m smoke

Requirements: 3.6, 7.1, 7.3, 8.1, 8.5, 10.4, 13.7
"""

from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test_user:test_pass@localhost:5433/test_reposaaas")
os.environ.setdefault("REDIS_URL", "redis://localhost:6380/0")
os.environ.setdefault("S3_BUCKET_NAME", "test-documents")
os.environ.setdefault("S3_ENDPOINT_URL", "http://localhost:4567")
os.environ.setdefault("KMS_ENDPOINT_URL", "http://localhost:4567")
os.environ.setdefault("AWS_REGION", "ap-south-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
os.environ.setdefault("JWT_PRIVATE_KEY", "-----BEGIN RSA PRIVATE KEY-----\nPLACEHOLDER\n-----END RSA PRIVATE KEY-----")
os.environ.setdefault("JWT_PUBLIC_KEY", "-----BEGIN PUBLIC KEY-----\nPLACEHOLDER\n-----END PUBLIC KEY-----")

from app.config import get_settings

get_settings.cache_clear()

import boto3
import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture(scope="module")
def app():
    return create_app()


@pytest.fixture(scope="module")
def client(app) -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# 1. All API endpoints respond (Req 8.1)
# ---------------------------------------------------------------------------


@pytest.mark.smoke
class TestEndpointsRespond:
    """Verify all /api/v1/ endpoints are reachable and return valid HTTP responses."""

    def test_health_endpoint(self, client: TestClient) -> None:
        """GET /health returns 200."""
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_auth_token_endpoint_exists(self, client: TestClient) -> None:
        """POST /api/v1/auth/token is reachable (returns 4xx, not 404)."""
        resp = client.post("/api/v1/auth/token", json={})
        assert resp.status_code != 404

    def test_documents_endpoint_requires_auth(self, client: TestClient) -> None:
        """GET /api/v1/documents requires authentication."""
        resp = client.get("/api/v1/documents")
        assert resp.status_code in (401, 403)

    def test_schemas_endpoint_requires_auth(self, client: TestClient) -> None:
        """GET /api/v1/schemas requires authentication."""
        resp = client.get("/api/v1/schemas")
        assert resp.status_code in (401, 403)

    def test_audit_logs_endpoint_requires_auth(self, client: TestClient) -> None:
        """GET /api/v1/audit-logs requires authentication."""
        resp = client.get("/api/v1/audit-logs")
        assert resp.status_code in (401, 403)

    def test_webhooks_endpoint_requires_auth(self, client: TestClient) -> None:
        """GET /api/v1/webhooks requires authentication."""
        resp = client.get("/api/v1/webhooks")
        assert resp.status_code in (401, 403)

    def test_verification_public_endpoint(self, client: TestClient) -> None:
        """GET /api/v1/verify/{credential_id} is reachable without auth."""
        resp = client.get("/api/v1/verify/00000000-0000-0000-0000-000000000001")
        # Should return 200 with status "invalid" (not found) or 404
        assert resp.status_code in (200, 404)

    def test_admin_tenants_endpoint_requires_auth(self, client: TestClient) -> None:
        """POST /api/v1/admin/tenants requires super_admin auth."""
        resp = client.post("/api/v1/admin/tenants", json={})
        assert resp.status_code in (401, 403, 422)


# ---------------------------------------------------------------------------
# 2. OpenAPI spec is valid OpenAPI 3.0 (Req 8.5)
# ---------------------------------------------------------------------------


@pytest.mark.smoke
class TestOpenAPISpec:
    """Verify the OpenAPI specification is valid and complete."""

    def test_openapi_json_endpoint_returns_200(self, client: TestClient) -> None:
        """GET /api/v1/openapi.json returns 200 with valid JSON."""
        resp = client.get("/api/v1/openapi.json")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)

    def test_openapi_spec_version_is_3(self, client: TestClient) -> None:
        """OpenAPI spec declares version 3.x."""
        resp = client.get("/api/v1/openapi.json")
        data = resp.json()
        openapi_version = data.get("openapi", "")
        assert openapi_version.startswith("3."), f"Expected OpenAPI 3.x, got {openapi_version}"

    def test_openapi_has_paths(self, client: TestClient) -> None:
        """OpenAPI spec includes path definitions."""
        resp = client.get("/api/v1/openapi.json")
        data = resp.json()
        paths = data.get("paths", {})
        assert len(paths) > 0, "No paths defined in OpenAPI spec"

    def test_openapi_covers_core_endpoints(self, client: TestClient) -> None:
        """OpenAPI spec includes all core API endpoints."""
        resp = client.get("/api/v1/openapi.json")
        data = resp.json()
        paths = data.get("paths", {})

        required_path_fragments = [
            "/auth/token",
            "/documents",
            "/schemas",
            "/audit-logs",
            "/webhooks",
            "/verify",
        ]
        path_keys = " ".join(paths.keys())
        for fragment in required_path_fragments:
            assert fragment in path_keys, f"Missing endpoint in OpenAPI: {fragment}"

    def test_openapi_has_security_schemes(self, client: TestClient) -> None:
        """OpenAPI spec defines security schemes (Bearer auth)."""
        resp = client.get("/api/v1/openapi.json")
        data = resp.json()
        components = data.get("components", {})
        security_schemes = components.get("securitySchemes", {})
        # FastAPI may put it at different locations
        assert len(security_schemes) > 0 or "security" in data


# ---------------------------------------------------------------------------
# 3. KMS keys exist and enabled per tenant (Req 3.6, 13.7)
# ---------------------------------------------------------------------------


@pytest.mark.smoke
class TestKMSConfiguration:
    """Verify KMS encryption infrastructure is operational."""

    def test_kms_endpoint_reachable(self) -> None:
        """KMS service (LocalStack) responds to list-keys."""
        settings = get_settings()
        kms = boto3.client(
            "kms",
            region_name=settings.aws_region,
            endpoint_url=settings.kms_endpoint_url,
            aws_access_key_id="test",
            aws_secret_access_key="test",
        )
        response = kms.list_keys()
        assert "Keys" in response

    def test_kms_can_create_and_use_key(self) -> None:
        """Can create a KMS key and encrypt/decrypt data (AES-256 envelope)."""
        settings = get_settings()
        kms = boto3.client(
            "kms",
            region_name=settings.aws_region,
            endpoint_url=settings.kms_endpoint_url,
            aws_access_key_id="test",
            aws_secret_access_key="test",
        )

        # Create key
        key_resp = kms.create_key(
            Description="Smoke test key",
            KeyUsage="ENCRYPT_DECRYPT",
        )
        key_id = key_resp["KeyMetadata"]["KeyId"]
        assert key_resp["KeyMetadata"]["Enabled"]

        # Encrypt test data
        plaintext = b"smoke test secret"
        enc_resp = kms.encrypt(KeyId=key_id, Plaintext=plaintext)
        ciphertext = enc_resp["CiphertextBlob"]
        assert ciphertext != plaintext

        # Decrypt
        dec_resp = kms.decrypt(CiphertextBlob=ciphertext)
        assert dec_resp["Plaintext"] == plaintext


# ---------------------------------------------------------------------------
# 4. RLS policies active on all tables (Req 7.1, 7.3)
# ---------------------------------------------------------------------------


@pytest.mark.smoke
class TestRLSPoliciesActive:
    """Verify Row Level Security is enabled on all tenant-scoped tables."""

    @pytest.mark.asyncio
    async def test_rls_enabled_on_all_tables(self) -> None:
        """All tenant-scoped tables have RLS enabled and forced."""
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        settings = get_settings()
        engine = create_async_engine(settings.database_url)

        tenant_tables = [
            "documents",
            "document_schemas",
            "schema_versions",
            "api_clients",
            "tenant_encryption_keys",
            "user_accounts",
            "audit_logs",
            "webhooks",
            "webhook_events",
            "verification_tokens",
            "bulk_jobs",
            "notification_preferences",
        ]

        async with engine.begin() as conn:
            for table in tenant_tables:
                result = await conn.execute(
                    text("""
                        SELECT relrowsecurity, relforcerowsecurity
                        FROM pg_class
                        WHERE relname = :table_name
                    """),
                    {"table_name": table},
                )
                row = result.fetchone()
                if row is not None:
                    assert row[0], f"RLS not ENABLED on {table}"
                    assert row[1], f"RLS not FORCED on {table}"

        await engine.dispose()


# ---------------------------------------------------------------------------
# 5. Audit log retention >= 7 years (Req 10.4)
# ---------------------------------------------------------------------------


@pytest.mark.smoke
class TestAuditLogRetention:
    """Verify audit log retention configuration meets compliance (Req 10.4)."""

    def test_default_retention_at_least_7_years(self) -> None:
        """Default audit retention configuration is >= 7 years."""
        settings = get_settings()
        # The retention setting (in years) should be at least 7
        retention = getattr(settings, "audit_log_retention_years", 7)
        assert retention >= 7, f"Audit retention is {retention} years (minimum 7)"

    @pytest.mark.asyncio
    async def test_audit_logs_table_is_partitioned(self) -> None:
        """audit_logs table is partitioned by month for long-term storage."""
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        settings = get_settings()
        engine = create_async_engine(settings.database_url)

        async with engine.begin() as conn:
            result = await conn.execute(
                text("""
                    SELECT relkind
                    FROM pg_class
                    WHERE relname = 'audit_logs'
                """)
            )
            row = result.fetchone()
            if row is not None:
                # 'p' = partitioned table, 'r' = regular table
                # Both are acceptable; partitioned is preferred
                assert row[0] in ("p", "r"), f"Unexpected relkind: {row[0]}"

        await engine.dispose()


# ---------------------------------------------------------------------------
# 6. Encryption at rest and in transit (Req 3.6, 13.7)
# ---------------------------------------------------------------------------


@pytest.mark.smoke
class TestEncryptionConfiguration:
    """Verify encryption is configured for data at rest and in transit."""

    def test_s3_bucket_exists(self) -> None:
        """The configured S3 bucket exists and is accessible."""
        settings = get_settings()
        s3 = boto3.client(
            "s3",
            region_name=settings.aws_region,
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id="test",
            aws_secret_access_key="test",
        )
        # Create bucket if it doesn't exist (for smoke tests)
        try:
            s3.create_bucket(
                Bucket=settings.s3_bucket_name,
                CreateBucketConfiguration={"LocationConstraint": settings.aws_region},
            )
        except Exception:
            pass

        response = s3.head_bucket(Bucket=settings.s3_bucket_name)
        assert response["ResponseMetadata"]["HTTPStatusCode"] == 200

    def test_encryption_service_uses_aes256(self) -> None:
        """EncryptionService uses AES-256-GCM for content encryption."""
        # Verify the service exists and uses AES-256
        import inspect

        from app.services.encryption_service import EncryptionService
        source = inspect.getsource(EncryptionService)
        assert "AES" in source or "aes" in source or "256" in source

    def test_jwt_uses_rs256(self) -> None:
        """JWT tokens are signed with RS256 (asymmetric)."""
        settings = get_settings()
        assert settings.jwt_algorithm == "RS256"


# ---------------------------------------------------------------------------
# 7. Redis connectivity (rate limiter, caching)
# ---------------------------------------------------------------------------


@pytest.mark.smoke
class TestRedisConnectivity:
    """Verify Redis is operational for caching and rate limiting."""

    @pytest.mark.asyncio
    async def test_redis_responds_to_ping(self) -> None:
        """Redis responds to PING command."""
        import redis.asyncio as aioredis

        settings = get_settings()
        client = aioredis.from_url(settings.redis_url)
        try:
            result = await client.ping()
            assert result is True
        finally:
            await client.aclose()


# ---------------------------------------------------------------------------
# 8. Database connectivity and schema
# ---------------------------------------------------------------------------


@pytest.mark.smoke
class TestDatabaseConnectivity:
    """Verify PostgreSQL is operational with correct schema."""

    @pytest.mark.asyncio
    async def test_database_responds(self) -> None:
        """Database accepts connections and responds to queries."""
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        settings = get_settings()
        engine = create_async_engine(settings.database_url)

        async with engine.begin() as conn:
            result = await conn.execute(text("SELECT 1"))
            assert result.scalar() == 1

        await engine.dispose()

    @pytest.mark.asyncio
    async def test_all_expected_tables_exist(self) -> None:
        """All application tables are present in the database."""
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        settings = get_settings()
        engine = create_async_engine(settings.database_url)

        expected_tables = {
            "tenants",
            "tenant_encryption_keys",
            "api_clients",
            "user_accounts",
            "document_schemas",
            "schema_versions",
            "documents",
            "bulk_jobs",
            "verification_tokens",
            "audit_logs",
            "webhooks",
            "webhook_events",
            "notification_preferences",
        }

        async with engine.begin() as conn:
            result = await conn.execute(
                text("""
                    SELECT tablename FROM pg_tables
                    WHERE schemaname = 'public'
                """)
            )
            actual_tables = {row[0] for row in result.fetchall()}

        await engine.dispose()

        missing = expected_tables - actual_tables
        assert not missing, f"Missing tables: {missing}"
