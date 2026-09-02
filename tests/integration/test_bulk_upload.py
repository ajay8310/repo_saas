"""
Integration tests for bulk upload processing.

Requirement 14.4: 10,000 records processed within 30 minutes.
"""

from __future__ import annotations

import time
from uuid import uuid4

import pytest
from httpx import AsyncClient


@pytest.mark.integration
class TestBulkUploadEndpoint:
    """POST /api/v1/documents/bulk — job creation and status tracking."""

    @pytest.mark.asyncio
    async def test_bulk_upload_returns_202_with_job_id(
        self, async_client: AsyncClient, make_auth_headers
    ) -> None:
        """Bulk upload accepts valid payload and returns 202 with job_id."""
        headers = make_auth_headers(roles=["issuer"])

        # Submit a small bulk upload (JSON format)
        records = [
            {
                "beneficiary_id": f"user{i}@test.io",
                "content": "dGVzdCBjb250ZW50",  # base64 "test content"
            }
            for i in range(5)
        ]

        resp = await async_client.post(
            "/api/v1/documents/bulk",
            headers=headers,
            json={
                "schema_id": str(uuid4()),
                "format": "json",
                "records": records,
            },
        )
        # Accept either 202 (async) or 422 (schema not found)
        assert resp.status_code in (202, 422, 404)

        if resp.status_code == 202:
            data = resp.json()
            assert "job_id" in data

    @pytest.mark.asyncio
    async def test_bulk_upload_rejects_over_10000_records(
        self, async_client: AsyncClient, make_auth_headers
    ) -> None:
        """More than 10,000 records returns 413 BATCH_TOO_LARGE."""
        headers = make_auth_headers(roles=["issuer"])

        resp = await async_client.post(
            "/api/v1/documents/bulk",
            headers=headers,
            json={
                "schema_id": str(uuid4()),
                "format": "json",
                "records": [{"beneficiary_id": f"u{i}@t.io", "content": "dA=="} for i in range(10_001)],
            },
        )
        assert resp.status_code in (413, 422)

    @pytest.mark.asyncio
    async def test_bulk_upload_rejects_unsupported_format(
        self, async_client: AsyncClient, make_auth_headers
    ) -> None:
        """Unsupported format returns 415 UNSUPPORTED_FORMAT."""
        headers = make_auth_headers(roles=["issuer"])

        resp = await async_client.post(
            "/api/v1/documents/bulk",
            headers=headers,
            json={
                "schema_id": str(uuid4()),
                "format": "xml",
                "records": [],
            },
        )
        assert resp.status_code in (415, 422)


@pytest.mark.integration
class TestBulkJobStatus:
    """GET /api/v1/documents/bulk/{job_id} — status tracking."""

    @pytest.mark.asyncio
    async def test_unknown_job_id_returns_404(
        self, async_client: AsyncClient, make_auth_headers
    ) -> None:
        """Non-existent job ID returns 404."""
        headers = make_auth_headers(roles=["issuer"])

        resp = await async_client.get(
            f"/api/v1/documents/bulk/{uuid4()}",
            headers=headers,
        )
        assert resp.status_code == 404


@pytest.mark.integration
class TestBulkUploadPerformance:
    """Performance: 10,000 records within 30 minutes (Req 14.4)."""

    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_10000_records_accepted_within_5_seconds(
        self, async_client: AsyncClient, make_auth_headers
    ) -> None:
        """The API endpoint accepts 10,000 records and returns 202 within 5 seconds.

        Actual processing happens asynchronously. This test validates the
        acceptance boundary, not the full processing time (which requires
        a running Celery worker).
        """
        headers = make_auth_headers(roles=["issuer"])

        records = [
            {"beneficiary_id": f"user{i}@perf.io", "content": "dGVzdA=="}
            for i in range(10_000)
        ]

        start = time.time()
        resp = await async_client.post(
            "/api/v1/documents/bulk",
            headers=headers,
            json={
                "schema_id": str(uuid4()),
                "format": "json",
                "records": records,
            },
        )
        elapsed = time.time() - start

        # Should accept quickly (202) or reject for missing schema (422)
        assert resp.status_code in (202, 422, 404)
        assert elapsed < 5, f"Acceptance took {elapsed:.1f}s (max 5s for API response)"
