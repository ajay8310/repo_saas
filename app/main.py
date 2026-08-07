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

import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.errors.handlers import register_exception_handlers
from app.routers import auth as auth_router


# ---------------------------------------------------------------------------
# Lifespan (startup / shutdown hooks)
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:  # noqa: ARG001
    """Execute startup tasks before yielding and cleanup on shutdown."""
    # Startup: additional initialisation (DB connection pool, Redis, etc.)
    # will be added in subsequent tasks (1.2, 1.3).
    yield
    # Shutdown: release resources here in later tasks.


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
    # Middleware
    # ------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Module-level ``app`` instance (consumed by Uvicorn)
# ---------------------------------------------------------------------------

app = create_app()
