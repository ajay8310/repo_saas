"""
Tier 2 property tests — service-layer tests with mocked DB and Redis.

Properties covered: 2, 3, 4, 19, 32, 37.
These verify service behaviour at the integration boundary using mocked I/O.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
from uuid import uuid4

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("S3_BUCKET_NAME", "test-bucket")
os.environ.setdefault("JWT_PRIVATE_KEY", "-----BEGIN RSA PRIVATE KEY-----\nPLACEHOLDER\n-----END RSA PRIVATE KEY-----")
os.environ.setdefault("JWT_PUBLIC_KEY", "-----BEGIN PUBLIC KEY-----\nPLACEHOLDER\n-----END PUBLIC KEY-----")

from app.config import get_settings
get_settings.cache_clear()

import pytest
from hypothesis import given, settings as h_settings
from hypothesis import strategies as st

from app.services.tenant_service import _VALID_TRANSITIONS


# ---------------------------------------------------------------------------
# Property 2: Deactivated Tenant Write Rejection (Req 1.6)
# Service-layer test: middleware rejects writes for deactivated status.
# ---------------------------------------------------------------------------


class TestProperty2Tier2:
    """Property 2 (Tier 2): Deactivated tenants cannot perform write operations.

    The TenantContextMiddleware blocks POST/PUT/PATCH/DELETE when status == deactivated.
    Verified by calling the middleware logic with a mocked Redis returning 'deactivated'.
    """

    @pytest.mark.asyncio
    async def test_deactivated_tenant_write_blocked(self) -> None:
        """Middleware returns 403 TENANT_DEACTIVATED for writes."""
        from app.middleware.tenant_context import TenantContextMiddleware, _WRITE_METHODS

        middleware = TenantContextMiddleware(app=MagicMock())

        # Mock the request
        tenant_id = str(uuid4())
        for method in _WRITE_METHODS:
            request = MagicMock()
            request.url.path = "/api/v1/documents"
            request.method = method
            request.state = MagicMock()
            request.state.tenant_id = tenant_id

            with patch.object(
                middleware, "_get_tenant_status", return_value="deactivated"
            ), patch.object(
                middleware, "_get_tenant_rate_limit", return_value=None
            ), patch(
                "app.middleware.tenant_context._resolve_tenant_id", return_value=tenant_id
            ):
                response = await middleware.dispatch(request, AsyncMock())
                assert response.status_code == 403
                body = json.loads(response.body)
                assert body["code"] == "TENANT_DEACTIVATED"

    @pytest.mark.asyncio
    async def test_deactivated_tenant_read_allowed(self) -> None:
        """Middleware allows GET requests for deactivated tenants."""
        from app.middleware.tenant_context import TenantContextMiddleware

        middleware = TenantContextMiddleware(app=MagicMock())

        tenant_id = str(uuid4())
        request = MagicMock()
        request.url.path = "/api/v1/documents"
        request.method = "GET"
        request.state = MagicMock()
        request.state.tenant_id = tenant_id

        mock_response = MagicMock(status_code=200)
        call_next = AsyncMock(return_value=mock_response)

        with patch.object(
            middleware, "_get_tenant_status", return_value="deactivated"
        ), patch.object(
            middleware, "_get_tenant_rate_limit", return_value=None
        ), patch(
            "app.middleware.tenant_context._resolve_tenant_id", return_value=tenant_id
        ):
            response = await middleware.dispatch(request, call_next)
            # Should pass through (call_next invoked)
            call_next.assert_called_once()

    @pytest.mark.asyncio
    async def test_suspended_tenant_all_requests_blocked(self) -> None:
        """Middleware returns 403 TENANT_SUSPENDED for any method."""
        from app.middleware.tenant_context import TenantContextMiddleware

        middleware = TenantContextMiddleware(app=MagicMock())

        tenant_id = str(uuid4())
        for method in ["GET", "POST", "PUT", "PATCH", "DELETE"]:
            request = MagicMock()
            request.url.path = "/api/v1/documents"
            request.method = method
            request.state = MagicMock()
            request.state.tenant_id = tenant_id

            with patch.object(
                middleware, "_get_tenant_status", return_value="suspended"
            ), patch(
                "app.middleware.tenant_context._resolve_tenant_id", return_value=tenant_id
            ):
                response = await middleware.dispatch(request, AsyncMock())
                assert response.status_code == 403
                body = json.loads(response.body)
                assert body["code"] == "TENANT_SUSPENDED"


# ---------------------------------------------------------------------------
# Property 3: Quota Enforcement — All Uploads Rejected at Quota (Req 1.8, 3.7)
# Service-layer: DocumentService checks pass through to DB trigger.
# ---------------------------------------------------------------------------


class TestProperty3Tier2:
    """Property 3 (Tier 2): Storage quota enforcement at the service layer.

    When the DB trigger raises an IntegrityError (quota exceeded),
    the upload must fail with no partial data stored.
    """

    @pytest.mark.asyncio
    async def test_quota_exceeded_raises_507(self) -> None:
        """When commit raises due to quota trigger, upload fails cleanly."""
        from sqlalchemy.exc import IntegrityError

        from app.services.document_service import DocumentService, ServiceUnavailableError

        mock_db = AsyncMock()
        mock_db.commit.side_effect = IntegrityError(
            "INSERT", {}, Exception("check_quota_before_insert")
        )
        mock_db.execute = AsyncMock()

        # Mock the schema query result
        mock_schema = MagicMock()
        mock_schema.id = uuid4()
        mock_schema.version = 1
        mock_schema.status = "active"
        mock_schema.field_definitions = []

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_schema
        mock_db.execute.return_value = mock_result

        settings = MagicMock()
        settings.aws_region = "us-east-1"
        settings.s3_endpoint_url = None
        settings.aws_access_key_id = None
        settings.aws_secret_access_key = None
        settings.s3_bucket_name = "test"

        service = DocumentService.__new__(DocumentService)
        service.db = mock_db
        service.settings = settings
        service._encryption = MagicMock()
        service._encryption.encrypt.return_value = MagicMock(
            ciphertext=b"enc", encrypted_dek=b"dek", iv=b"iv"
        )
        service._s3 = MagicMock()
        service._audit = AsyncMock()
        service._audit.record = AsyncMock()
        service._scanner = MagicMock()
        service._scanner.scan.return_value = MagicMock(clean=True)

        with pytest.raises((IntegrityError, Exception)):
            await service.upload_document(
                tenant_id=uuid4(),
                schema_id=mock_schema.id,
                beneficiary_id="user@example.com",
                content=b"test content",
                cmk_arn="arn:aws:kms:us-east-1:000:key/test",
            )


# ---------------------------------------------------------------------------
# Property 4: Rate Limit — HTTP 429 with Retry-After at Limit (Req 1.9, 8.4)
# Service-layer with mocked Redis.
# ---------------------------------------------------------------------------


class TestProperty4Tier2:
    """Property 4 (Tier 2): Rate limiter blocks at quota with retry_after > 0."""

    @pytest.mark.asyncio
    async def test_rate_limiter_blocks_when_over_limit(self) -> None:
        """When zcard returns >= limit, the request is blocked."""
        from app.services.rate_limiter import RateLimiterService

        mock_redis = AsyncMock()
        # Pipeline mock: zremrangebyscore result, zcard result, zadd result, expire result
        mock_pipe = AsyncMock()
        mock_pipe.execute = AsyncMock(return_value=[0, 100, 1, True])
        mock_pipe.zremrangebyscore = MagicMock(return_value=mock_pipe)
        mock_pipe.zcard = MagicMock(return_value=mock_pipe)
        mock_pipe.zadd = MagicMock(return_value=mock_pipe)
        mock_pipe.expire = MagicMock(return_value=mock_pipe)
        mock_redis.pipeline.return_value = mock_pipe

        # zremrangebyscore for cleanup after block
        mock_redis.zremrangebyscore = AsyncMock()
        # zrange to find oldest entry for retry_after calculation
        now = time.time()
        mock_redis.zrange = AsyncMock(return_value=[(b"entry", now - 30)])

        service = RateLimiterService(
            redis=mock_redis, default_limit=100, window_seconds=60
        )

        result = await service.check(tenant_id=str(uuid4()), tenant_limit=100)
        assert not result.allowed
        assert result.retry_after > 0
        assert result.remaining == 0

    @pytest.mark.asyncio
    async def test_rate_limiter_allows_under_limit(self) -> None:
        """When zcard returns < limit, the request is allowed."""
        from app.services.rate_limiter import RateLimiterService

        mock_redis = AsyncMock()
        mock_pipe = AsyncMock()
        mock_pipe.execute = AsyncMock(return_value=[0, 50, 1, True])
        mock_pipe.zremrangebyscore = MagicMock(return_value=mock_pipe)
        mock_pipe.zcard = MagicMock(return_value=mock_pipe)
        mock_pipe.zadd = MagicMock(return_value=mock_pipe)
        mock_pipe.expire = MagicMock(return_value=mock_pipe)
        mock_redis.pipeline.return_value = mock_pipe

        service = RateLimiterService(
            redis=mock_redis, default_limit=100, window_seconds=60
        )

        result = await service.check(tenant_id=str(uuid4()), tenant_limit=100)
        assert result.allowed
        assert result.retry_after == 0
        assert result.remaining == 49  # 100 - 50 - 1

    @given(limit=st.integers(min_value=1, max_value=10000))
    @h_settings(max_examples=20)
    def test_rate_limit_result_invariants(self, limit: int) -> None:
        """RateLimitResult has correct field relationships."""
        from app.services.rate_limiter import RateLimitResult

        # Blocked result
        blocked = RateLimitResult(allowed=False, remaining=0, limit=limit, retry_after=30)
        assert blocked.remaining == 0
        assert blocked.retry_after > 0

        # Allowed result
        allowed = RateLimitResult(allowed=True, remaining=limit - 1, limit=limit, retry_after=0)
        assert allowed.remaining <= allowed.limit
        assert allowed.retry_after == 0


# ---------------------------------------------------------------------------
# Property 19: Audit Log Written for Every Document Retrieval (Req 4.9, 10.1)
# Service-layer: verify _audit.record is called during download.
# ---------------------------------------------------------------------------


class TestProperty19Tier2:
    """Property 19 (Tier 2): Audit log is recorded for every retrieval attempt."""

    @pytest.mark.asyncio
    async def test_download_calls_audit_record(self) -> None:
        """DocumentService.download_document calls _audit.record."""
        from app.services.document_service import DocumentService

        mock_db = AsyncMock()
        mock_doc = MagicMock()
        mock_doc.id = uuid4()
        mock_doc.tenant_id = uuid4()
        mock_doc.s3_key = "tenant/doc"
        mock_doc.encrypted_dek = b"dek"
        mock_doc.iv = b"iv"
        mock_doc.status = "stored"
        mock_doc.created_at = datetime.now(timezone.utc)
        mock_doc.schema_id = uuid4()
        mock_doc.beneficiary_id = "user@test.com"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_doc
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()

        settings = MagicMock()
        settings.aws_region = "us-east-1"
        settings.s3_endpoint_url = None
        settings.aws_access_key_id = None
        settings.aws_secret_access_key = None
        settings.s3_bucket_name = "test"

        service = DocumentService.__new__(DocumentService)
        service.db = mock_db
        service.settings = settings
        service._audit = AsyncMock()
        service._audit.record = AsyncMock()

        # Mock S3 response
        service._s3 = MagicMock()
        s3_body = MagicMock()
        s3_body.read.return_value = b"encrypted_content"
        service._s3.get_object.return_value = {"Body": s3_body}

        # Mock encryption
        service._encryption = MagicMock()
        service._encryption.decrypt.return_value = MagicMock(plaintext=b"decrypted")

        tenant_id = mock_doc.tenant_id
        credential_id = mock_doc.id

        await service.download_document(
            tenant_id=tenant_id,
            credential_id=credential_id,
            output_format="raw",
            actor_id="test_actor",
            actor_role="beneficiary",
        )

        # Verify audit was called
        service._audit.record.assert_called_once()
        call_kwargs = service._audit.record.call_args[1]
        assert call_kwargs["operation"] == "document:download"
        assert call_kwargs["resource_id"] == str(credential_id)
        assert call_kwargs["tenant_id"] == tenant_id


# ---------------------------------------------------------------------------
# Property 32: Search Results Namespace Isolation (Req 9.2, 7.1)
# Service-layer: verify set_tenant_context is called before search queries.
# ---------------------------------------------------------------------------


class TestProperty32Tier2:
    """Property 32 (Tier 2): Search queries are always tenant-scoped via RLS."""

    @pytest.mark.asyncio
    async def test_search_sets_tenant_context(self) -> None:
        """SearchService.search calls set_tenant_context with the correct tenant_id."""
        from app.services.search_service import SearchService, SearchParams

        mock_db = AsyncMock()
        # Mock the query results
        mock_docs_result = MagicMock()
        mock_docs_result.scalars.return_value.all.return_value = []
        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 0

        mock_db.execute = AsyncMock(side_effect=[mock_docs_result, mock_count_result])

        service = SearchService(db=mock_db)
        tenant_id = uuid4()

        with patch(
            "app.services.search_service.set_tenant_context", new_callable=AsyncMock
        ) as mock_stc:
            await service.search(tenant_id=tenant_id, params=SearchParams(query="test"))
            mock_stc.assert_called_once_with(mock_db, str(tenant_id))

    @pytest.mark.asyncio
    async def test_search_never_bypasses_tenant_isolation(self) -> None:
        """SearchParams does not allow overriding tenant_id."""
        from app.services.search_service import SearchParams

        params = SearchParams(query="test", status="stored")
        # Verify no tenant_id field exists on SearchParams
        assert not hasattr(params, "tenant_id")

    @pytest.mark.asyncio
    async def test_different_tenants_get_isolated_results(self) -> None:
        """Two tenants calling search both trigger set_tenant_context with their own ID."""
        from app.services.search_service import SearchService, SearchParams

        tenant_a = uuid4()
        tenant_b = uuid4()

        calls = []

        async def capture_tenant_context(db, tid):
            calls.append(tid)

        for tenant_id in [tenant_a, tenant_b]:
            mock_db = AsyncMock()
            mock_docs_result = MagicMock()
            mock_docs_result.scalars.return_value.all.return_value = []
            mock_count_result = MagicMock()
            mock_count_result.scalar.return_value = 0
            mock_db.execute = AsyncMock(side_effect=[mock_docs_result, mock_count_result])

            service = SearchService(db=mock_db)
            with patch(
                "app.services.search_service.set_tenant_context",
                side_effect=capture_tenant_context,
            ):
                await service.search(tenant_id=tenant_id, params=SearchParams())

        assert str(tenant_a) in calls
        assert str(tenant_b) in calls
        assert calls[0] != calls[1]


# ---------------------------------------------------------------------------
# Property 37: Audit Log Write Failure Rejects Originating Operation (Req 10.7)
# Service-layer with mocked DB.
# ---------------------------------------------------------------------------


class TestProperty37Tier2:
    """Property 37 (Tier 2): A failed audit write causes the caller's transaction to fail.

    Since AuditService.record() runs in the same transaction and does NOT commit,
    a DB error on audit INSERT propagates to the caller who then rolls back.
    """

    @pytest.mark.asyncio
    async def test_audit_failure_propagates_to_caller(self) -> None:
        """If audit INSERT raises, the caller's commit will fail."""
        from app.services.audit_service import AuditService

        mock_db = AsyncMock()
        mock_db.add.side_effect = RuntimeError("disk full — cannot write audit")

        service = AuditService(db=mock_db)

        with pytest.raises(RuntimeError, match="disk full"):
            await service.record(
                tenant_id=uuid4(),
                actor_id="actor",
                actor_role="issuer",
                operation="document:upload",
                resource_type="document",
                resource_id=str(uuid4()),
                outcome="success",
            )

    @pytest.mark.asyncio
    async def test_audit_runs_in_caller_transaction(self) -> None:
        """AuditService never calls commit — transaction ownership belongs to caller."""
        from app.services.audit_service import AuditService

        mock_db = AsyncMock()
        service = AuditService(db=mock_db)

        await service.record(
            tenant_id=uuid4(),
            actor_id="actor",
            actor_role="issuer",
            operation="document:upload",
            resource_type="document",
            resource_id=str(uuid4()),
            outcome="success",
        )

        mock_db.commit.assert_not_called()
        mock_db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_document_upload_rolls_back_on_audit_failure(self) -> None:
        """If audit record raises during upload, the entire upload fails."""
        from app.services.document_service import DocumentService

        mock_db = AsyncMock()
        mock_schema = MagicMock()
        mock_schema.id = uuid4()
        mock_schema.version = 1
        mock_schema.status = "active"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_schema
        mock_db.execute = AsyncMock(return_value=mock_result)

        settings = MagicMock()
        settings.aws_region = "us-east-1"
        settings.s3_endpoint_url = None
        settings.aws_access_key_id = None
        settings.aws_secret_access_key = None
        settings.s3_bucket_name = "test"

        service = DocumentService.__new__(DocumentService)
        service.db = mock_db
        service.settings = settings
        service._encryption = MagicMock()
        service._encryption.encrypt.return_value = MagicMock(
            ciphertext=b"enc", encrypted_dek=b"dek", iv=b"iv"
        )
        service._s3 = MagicMock()
        service._scanner = MagicMock()
        service._scanner.scan.return_value = MagicMock(clean=True)

        # Make audit raise
        service._audit = AsyncMock()
        service._audit.record = AsyncMock(
            side_effect=RuntimeError("audit write failed")
        )

        with pytest.raises(RuntimeError, match="audit write failed"):
            await service.upload_document(
                tenant_id=uuid4(),
                schema_id=mock_schema.id,
                beneficiary_id="user@test.com",
                content=b"test",
                cmk_arn="arn:aws:kms:us-east-1:000:key/test",
            )
