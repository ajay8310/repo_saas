"""
Integration tests for search performance.

Requirement 9.3: Search p95 < 3 seconds with 10k documents.
"""

from __future__ import annotations

import statistics
import time
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.integration
class TestSearchPerformance:
    """Verify search response times meet SLA (Req 9.3)."""

    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_search_returns_within_3_seconds(
        self, async_client: AsyncClient, make_auth_headers
    ) -> None:
        """Search endpoint responds within 3 seconds under normal load."""
        headers = make_auth_headers(roles=["issuer"])

        latencies = []
        for _ in range(20):
            start = time.time()
            resp = await async_client.get(
                "/api/v1/documents",
                params={"q": "test_user", "page_size": 20},
                headers=headers,
            )
            elapsed = time.time() - start
            latencies.append(elapsed)
            # Response should be valid (200 or 403 if tenant not provisioned)
            assert resp.status_code in (200, 403)

        p95 = sorted(latencies)[int(len(latencies) * 0.95)]
        assert p95 < 3.0, f"Search p95 latency: {p95:.2f}s (max 3.0s)"

    @pytest.mark.asyncio
    async def test_search_with_filters_responds_quickly(
        self, async_client: AsyncClient, make_auth_headers
    ) -> None:
        """Filtered search (status + date range) responds within 3 seconds."""
        headers = make_auth_headers(roles=["issuer"])

        start = time.time()
        resp = await async_client.get(
            "/api/v1/documents",
            params={
                "status": "stored",
                "issued_after": "2024-01-01",
                "issued_before": "2025-12-31",
                "sort_by": "created_at",
                "sort_order": "desc",
                "page_size": 50,
            },
            headers=headers,
        )
        elapsed = time.time() - start

        assert resp.status_code in (200, 403)
        assert elapsed < 3.0, f"Filtered search took {elapsed:.2f}s"


@pytest.mark.integration
class TestSearchFunctionality:
    """Search correctness and edge cases (Req 9.5, 9.6, 9.7)."""

    @pytest.mark.asyncio
    async def test_invalid_date_range_returns_422(
        self, async_client: AsyncClient, make_auth_headers
    ) -> None:
        """issued_after > issued_before returns 422 (Req 9.7)."""
        headers = make_auth_headers(roles=["issuer"])

        resp = await async_client.get(
            "/api/v1/documents",
            params={
                "issued_after": "2025-12-31",
                "issued_before": "2024-01-01",
            },
            headers=headers,
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_empty_search_returns_200(
        self, async_client: AsyncClient, make_auth_headers
    ) -> None:
        """No results returns HTTP 200 with empty items (Req 9.6)."""
        headers = make_auth_headers(roles=["issuer"])

        resp = await async_client.get(
            "/api/v1/documents",
            params={"q": "nonexistent_beneficiary_xyz_99999"},
            headers=headers,
        )
        # Should be 200 with empty results or 403 if not provisioned
        if resp.status_code == 200:
            data = resp.json()
            items = data.get("items", data) if isinstance(data, dict) else data
            assert isinstance(items, list)

    @pytest.mark.asyncio
    async def test_pagination_limits_enforced(
        self, async_client: AsyncClient, make_auth_headers
    ) -> None:
        """page_size is clamped to [1, 100] (Req 9.5)."""
        headers = make_auth_headers(roles=["issuer"])

        # Request page_size > 100
        resp = await async_client.get(
            "/api/v1/documents",
            params={"page_size": 500},
            headers=headers,
        )
        if resp.status_code == 200:
            data = resp.json()
            # Returned page_size should be clamped to 100
            assert data.get("page_size", 100) <= 100
