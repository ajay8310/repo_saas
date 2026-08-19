"""
FastAPI application factory.

This module creates the ``app`` instance consumed by Uvicorn.  It wires up:
  - CORS middleware
  - Global exception handlers (registered in app/errors/)
  - API v1 router
  - Health-check endpoint (GET /health)

Usage (development):
    uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

Usage (production via Docker):
    uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.errors.handlers import register_exception_handlers
from app.logging_config import configure_logging
from app.routers import anchoring as anchoring_router
from app.routers import auth as auth_router
from app.routers import digilocker as digilocker_router
from app.routers import privacy as privacy_router
from app.routers import tenants as tenants_router
from app.routers import schemas as schemas_router
from app.routers import documents as documents_router
from app.routers import verification as verification_router
from app.routers import search as search_router
from app.routers import notifications as notifications_router
from app.routers import webhooks as webhooks_router
from app.routers import audit as audit_router


# ---------------------------------------------------------------------------
# Lifespan (startup / shutdown hooks)
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:  # noqa: ARG001
    """Configure logging on startup and release pooled resources on shutdown."""
    settings = get_settings()

    configure_logging(
        level=settings.log_level,
        # Human-readable locally, structured everywhere else.
        json_output=settings.environment != "development",
    )
    logger = logging.getLogger(__name__)
    logger.info(
        "Starting %s (environment=%s, vault=%s, anchor=%s)",
        settings.app_name,
        settings.environment,
        settings.vault_provider,
        settings.anchor_provider,
    )

    yield

    # Dispose pooled connections so a reload or shutdown does not leave
    # PostgreSQL and Redis sessions dangling.
    try:
        from app.db.session import engine

        await engine.dispose()
    except Exception:  # noqa: BLE001 - shutdown must not raise
        logger.warning("Failed to dispose the database engine cleanly", exc_info=True)

    try:
        from app.db.redis import close_redis_client

        await close_redis_client()
    except Exception:  # noqa: BLE001
        logger.debug("No Redis client to close", exc_info=True)

    logger.info("Shutdown complete")


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

def create_app() -> FastAPI:
    """Construct and configure the FastAPI application.

    Splitting construction into a factory function makes it easy to create
    multiple instances in tests with different settings.
    """
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        description=(
            "Generic Multi-Tenant SaaS Document and Credential Repository Platform. "
            "OpenAPI 3.0 specification — Requirement 8.5."
        ),
        version="1.0.0",
        openapi_url=f"{settings.api_v1_prefix}/openapi.json",
        docs_url=f"{settings.api_v1_prefix}/docs",
        redoc_url=f"{settings.api_v1_prefix}/redoc",
        debug=settings.debug,
        lifespan=lifespan,
    )

    # ------------------------------------------------------------------
    # Middleware (order matters: last registered = first to execute)
    # ------------------------------------------------------------------
    from app.middleware.rate_limit import RateLimitMiddleware
    from app.middleware.tenant_context import TenantContextMiddleware

    # Rate limiter runs after tenant context is established
    app.add_middleware(
        RateLimitMiddleware,
        default_limit=settings.rate_limit_default_requests,
        window_seconds=settings.rate_limit_window_seconds,
    )

    # Tenant context middleware sets RLS and checks tenant status
    app.add_middleware(TenantContextMiddleware)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=settings.cors_allow_methods,
        allow_headers=settings.cors_allow_headers,
    )

    # ------------------------------------------------------------------
    # Exception handlers
    # ------------------------------------------------------------------
    register_exception_handlers(app)

    # ------------------------------------------------------------------
    # Routers
    # ------------------------------------------------------------------
    _register_routes(app, settings)

    return app


def _register_routes(app: FastAPI, settings) -> None:  # noqa: ANN001
    """Attach all API routers to the application."""

    # Health check — intentionally outside the versioned prefix so that
    # load balancers and Kubernetes liveness probes can reach it without
    # authentication.
    @app.get(
        "/health",
        summary="Platform health check",
        response_description="Service is healthy",
        tags=["observability"],
        # Exclude from OpenAPI auth requirements
        include_in_schema=True,
    )
    async def health_check() -> JSONResponse:
        """Return a 200 OK with basic service metadata.

        Requirement 8.1: versioned REST API for all core operations.
        This endpoint serves as the liveness probe and smoke-test anchor.
        """
        return JSONResponse(
            status_code=200,
            content={
                "status": "ok",
                "service": settings.app_name,
                "environment": settings.environment,
                "timestamp": int(time.time()),
            },
        )

    # Versioned API routers
    app.include_router(auth_router.router, prefix=settings.api_v1_prefix)
    app.include_router(tenants_router.router, prefix=settings.api_v1_prefix)
    app.include_router(schemas_router.router, prefix=settings.api_v1_prefix)
    app.include_router(documents_router.router, prefix=settings.api_v1_prefix)
    app.include_router(verification_router.router, prefix=settings.api_v1_prefix)
    app.include_router(search_router.router, prefix=settings.api_v1_prefix)
    app.include_router(notifications_router.router, prefix=settings.api_v1_prefix)
    app.include_router(webhooks_router.router, prefix=settings.api_v1_prefix)
    app.include_router(audit_router.router, prefix=settings.api_v1_prefix)
    app.include_router(anchoring_router.router, prefix=settings.api_v1_prefix)
    app.include_router(privacy_router.router, prefix=settings.api_v1_prefix)
    app.include_router(digilocker_router.router, prefix=settings.api_v1_prefix)


# ---------------------------------------------------------------------------
# Module-level ``app`` instance (consumed by Uvicorn)
# ---------------------------------------------------------------------------

app = create_app()
