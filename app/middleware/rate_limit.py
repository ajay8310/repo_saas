"""
Rate limiting middleware — enforces per-tenant request quotas.

Applies to all authenticated requests. Returns HTTP 429 with Retry-After
header when the tenant's quota is exceeded.

Requirements: 1.9, 8.4
"""

from __future__ import annotations

import logging

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.db.redis import get_redis_client
from app.services.rate_limiter import RateLimiterService

logger = logging.getLogger(__name__)

# Routes exempt from rate limiting
_EXEMPT_PREFIXES = ("/health", "/api/v1/docs", "/api/v1/redoc", "/api/v1/openapi.json")


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Enforce per-tenant rate limits using Redis sliding-window counters."""

    def __init__(self, app, default_limit: int, window_seconds: int) -> None:
        super().__init__(app)
        self.default_limit = default_limit
        self.window_seconds = window_seconds

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        path = request.url.path

        # Skip rate limiting for exempt routes
        if any(path.startswith(prefix) for prefix in _EXEMPT_PREFIXES):
            return await call_next(request)

        # Rate limiting requires a tenant_id (set by auth dependency)
        tenant_id: str | None = getattr(request.state, "tenant_id", None)
        if not tenant_id:
            # No tenant context = unauthenticated request; let auth handle it
            return await call_next(request)

        # Check per-tenant rate limit override (set by tenant status middleware)
        tenant_limit: int | None = getattr(request.state, "tenant_rate_limit", None)

        try:
            redis = get_redis_client()
            limiter = RateLimiterService(
                redis=redis,
                default_limit=self.default_limit,
                window_seconds=self.window_seconds,
            )
            result = await limiter.check(tenant_id, tenant_limit)
        except Exception:
            # If Redis is down, fail open (allow the request) and log
            logger.exception("Rate limiter Redis error — failing open")
            return await call_next(request)

        if not result.allowed:
            logger.warning(
                "Rate limit exceeded: tenant_id=%s limit=%d retry_after=%d",
                tenant_id,
                result.limit,
                result.retry_after,
            )
            return JSONResponse(
                status_code=429,
                content={
                    "code": "RATE_LIMIT_EXCEEDED",
                    "message": "Request rate limit exceeded for this tenant.",
                },
                headers={
                    "Retry-After": str(result.retry_after),
                    "X-RateLimit-Limit": str(result.limit),
                    "X-RateLimit-Remaining": "0",
                },
            )

        # Add rate limit headers to successful responses
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(result.limit)
        response.headers["X-RateLimit-Remaining"] = str(result.remaining)
        return response
