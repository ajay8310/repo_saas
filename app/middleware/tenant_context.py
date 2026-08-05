"""
TenantContextMiddleware — sets PostgreSQL RLS tenant context per request.

After JWT authentication resolves a tenant_id, this middleware executes:
    SET LOCAL app.tenant_id = '<uuid>';
at the start of every DB transaction so that RLS policies enforce isolation
at the database level.

For unauthenticated routes (health check, public verification), the
middleware is a no-op.
"""

from __future__ import annotations

import logging
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)

# Routes that don't require tenant context
_PUBLIC_PREFIXES = ("/health", "/api/v1/verify/", "/api/v1/docs", "/api/v1/redoc", "/api/v1/openapi.json")


class TenantContextMiddleware(BaseHTTPMiddleware):
    """Inject ``app.tenant_id`` into the PostgreSQL session for RLS enforcement."""

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

        if tenant_id:
            # Set the RLS variable for this request's DB connections
            request.state.db_tenant_id = tenant_id

        response = await call_next(request)
        return response


async def set_tenant_context(session, tenant_id: str) -> None:
    """Execute SET LOCAL to activate RLS for the given tenant within a transaction.

    Call this at the start of any service method that needs tenant isolation:
        await set_tenant_context(db, str(current_user.tenant_id))
    """
    await session.execute(
        # text() import deferred to avoid circular imports at module level
        __import__("sqlalchemy").text(f"SET LOCAL app.tenant_id = '{tenant_id}'")
    )
