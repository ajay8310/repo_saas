"""
Global exception handlers for the FastAPI application.

Provides consistent JSON error responses across all endpoints.
Requirement 8.6: HTTP 422 with field-level error details.
"""

from __future__ import annotations

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


def register_exception_handlers(app: FastAPI) -> None:
    """Attach all global exception handlers to the app."""

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError  # noqa: ARG001
    ) -> JSONResponse:
        """Return HTTP 422 with field-level error details (Req 8.6)."""
        errors = []
        for err in exc.errors():
            loc = err.get("loc", [])
            # Skip the first element if it's 'body' / 'query' / 'path'
            field_path = ".".join(str(part) for part in loc[1:]) if len(loc) > 1 else str(loc)
            errors.append(
                {
                    "field": field_path,
                    "message": err.get("msg", "Validation error"),
                    "rejected_value": err.get("input"),
                    "type": err.get("type", "value_error"),
                }
            )
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "code": "VALIDATION_ERROR",
                "message": "Request validation failed.",
                "errors": errors,
            },
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request, exc: StarletteHTTPException  # noqa: ARG001
    ) -> JSONResponse:
        """Normalize all HTTP exceptions to a consistent JSON shape."""
        detail = exc.detail
        if isinstance(detail, dict):
            content = detail
        else:
            content = {"code": "ERROR", "message": str(detail)}

        return JSONResponse(
            status_code=exc.status_code,
            content=content,
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request, exc: Exception  # noqa: ARG001
    ) -> JSONResponse:
        """Catch-all for unhandled exceptions — never expose internals."""
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "code": "INTERNAL_ERROR",
                "message": "An unexpected error occurred.",
            },
        )
