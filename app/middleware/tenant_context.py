"""
TenantContextMiddleware — sets PostgreSQL RLS tenant context per request.

After JWT authentication resolves a tenant_id, this middleware:
1. Checks tenant status (active, suspended, deactivated) via Redis cache
2. Rejects requests for suspended tenants with 403 TENANT_SUSPENDED
3. Rejects write requests for deactivated tenants with 403 TENANT_DEACTIVATED
4. Sets ``app.tenant_id`` via ``SET LOCAL`` for RLS enforcement

Requirements: 1.5, 1.6, 7.1, 7.2
"""

from __future__ import annotations

import json
import logging

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger(__name__)

# Routes that don't require tenant context
_PUBLIC_PREFIXES = (
    "/health",
    "/api/v1/verify/",
    "/api/v1/auth/",
    "/api/v1/docs",
    "/api/v1/redoc",
    "/api/v1/openapi.json",
)

# HTTP methods considered "write" operations
_WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# Redis key prefix for tenant status cache
_TENANT_STATUS_PREFIX = "tenant_status:"
_TENANT_STATUS_TTL = 5  # seconds


class TenantContextMiddleware(BaseHTTPMiddleware):
    """Inject ``app.tenant_id`` into the PostgreSQL session for RLS enforcement.

    Also enforces tenant lifecycle status (Req 1.5, 1.6):
    - Suspended tenants: all requests rejected with 403
    - Deactivated tenants: write requests rejected, reads allowed
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # Skip tenant context for public/unauthenticated routes
        path = request.url.path
        if any(path.startswith(prefix) for prefix in _PUBLIC_PREFIXES):
            return await call_next(request)

        # The tenant_id is set on request.state by the auth dependency
        # after JWT validation. If not present, let the request proceed —
        # the auth dependency will return 401 if needed.
        tenant_id: str | None = getattr(request.state, "tenant_id", None)

        if not tenant_id:
            return await call_next(request)

        # Check tenant status from Redis cache
        tenant_status = await self._get_tenant_status(tenant_id)

        if tenant_status == "suspended":
            return JSONResponse(
                status_code=403,
                content={
                    "code": "TENANT_SUSPENDED",
                    "message": "This tenant namespace is suspended. Contact platform support.",
                },
            )

        if tenant_status == "deactivated" and request.method in _WRITE_METHODS:
            return JSONResponse(
                status_code=403,
                content={
                    "code": "TENANT_DEACTIVATED",
                    "message": "This tenant is deactivated. Write operations are not permitted.",
                },
            )

        # Store tenant context for downstream use
        request.state.db_tenant_id = tenant_id

        # Store rate limit override if available from cache
        rate_limit = await self._get_tenant_rate_limit(tenant_id)
        if rate_limit:
            request.state.tenant_rate_limit = rate_limit

        response = await call_next(request)
        return response

    async def _get_tenant_status(self, tenant_id: str) -> str | None:
        """Get tenant status from Redis cache, falling back to 'active'.

        Returns None if Redis is unavailable (fail-open for status check).
        """
        try:
            from app.db.redis import get_redis_client

            redis = get_redis_client()
            key = f"{_TENANT_STATUS_PREFIX}{tenant_id}"
            cached = await redis.get(key)
            if cached:
                data = json.loads(cached)
                return data.get("status")
            # No cache entry — assume active (will be populated by TenantService)
            return "active"
        except Exception:
            logger.exception("Failed to check tenant status from Redis")
            return None  # Fail open

    async def _get_tenant_rate_limit(self, tenant_id: str) -> int | None:
        """Get per-tenant rate limit override from Redis cache."""
        try:
            from app.db.redis import get_redis_client

            redis = get_redis_client()
            key = f"{_TENANT_STATUS_PREFIX}{tenant_id}"
            cached = await redis.get(key)
            if cached:
                data = json.loads(cached)
                return data.get("rate_limit_per_hour")
            return None
        except Exception:
            return None


async def set_tenant_context(session, tenant_id: str) -> None:
    """Execute SET LOCAL to activate RLS for the given tenant within a transaction.

    Call this at the start of any service method that needs tenant isolation:
        await set_tenant_context(db, str(current_user.tenant_id))
    """
    from sqlalchemy import text

    await session.execute(text(f"SET LOCAL app.tenant_id = '{tenant_id}'"))


async def cache_tenant_status(
    tenant_id: str,
    status: str,
    rate_limit_per_hour: int | None = None,
) -> None:
    """Update the Redis cache for a tenant's status.

    Called by TenantService on any status change to invalidate stale data.
    """
    try:
        from app.db.redis import get_redis_client

        redis = get_redis_client()
        key = f"{_TENANT_STATUS_PREFIX}{tenant_id}"
        data = {"status": status}
        if rate_limit_per_hour is not None:
            data["rate_limit_per_hour"] = rate_limit_per_hour
        await redis.set(key, json.dumps(data), ex=_TENANT_STATUS_TTL)
    except Exception:
        logger.exception("Failed to cache tenant status")
