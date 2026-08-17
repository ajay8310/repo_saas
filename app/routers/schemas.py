"""
Schema management endpoints.

Requirements: 2.1-2.7
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.dependencies.auth import TokenPayload, get_current_user
from app.rbac.permissions import require_permission
from app.services.schema_service import (
    SchemaBreakingChangeError,
    SchemaInactiveError,
    SchemaNotFoundError,
    SchemaService,
    SchemaValidationError,
    get_schema_service,
)

router = APIRouter(prefix="/schemas", tags=["schemas"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class FieldDefinition(BaseModel):
    name: str = Field(..., min_length=1)
    type: str = Field(...)
    required: bool
    allowed_values: list[str] | None = None


class CreateSchemaRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    field_definitions: list[FieldDefinition]


class UpdateSchemaRequest(BaseModel):
    field_definitions: list[FieldDefinition]


class SchemaResponse(BaseModel):
    id: str
    name: str
    version: int
    status: str
    field_definitions: list[dict[str, Any]]
    created_at: str


class SchemaVersionResponse(BaseModel):
    id: str
    version: int
    field_definitions: list[dict[str, Any]]
    created_at: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=SchemaResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("schema:create"))],
)
async def create_schema(
    body: CreateSchemaRequest,
    user: TokenPayload = Depends(get_current_user),
    service: SchemaService = Depends(get_schema_service),
) -> SchemaResponse:
    """Create a new document schema (Req 2.1, 2.2)."""
    try:
        schema = await service.create_schema(
            tenant_id=user.tenant_id,
            name=body.name,
            field_definitions=[f.model_dump() for f in body.field_definitions],
        )
    except SchemaValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "SCHEMA_INVALID", "errors": exc.errors},
        ) from exc

    return _schema_response(schema)


@router.get("/{schema_id}", response_model=SchemaResponse)
async def get_schema(
    schema_id: UUID,
    user: TokenPayload = Depends(get_current_user),
    service: SchemaService = Depends(get_schema_service),
) -> SchemaResponse:
    schema = await service.get_schema(user.tenant_id, schema_id)
    if schema is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND"})
    return _schema_response(schema)


@router.get("", response_model=list[SchemaResponse])
async def list_schemas(
    user: TokenPayload = Depends(get_current_user),
    service: SchemaService = Depends(get_schema_service),
) -> list[SchemaResponse]:
    schemas = await service.list_schemas(user.tenant_id)
    return [_schema_response(s) for s in schemas]


@router.patch(
    "/{schema_id}",
    response_model=SchemaResponse,
    dependencies=[Depends(require_permission("schema:update"))],
)
async def update_schema(
    schema_id: UUID,
    body: UpdateSchemaRequest,
    user: TokenPayload = Depends(get_current_user),
    service: SchemaService = Depends(get_schema_service),
) -> SchemaResponse:
    """Update schema field definitions (Req 2.3, 2.4)."""
    try:
        schema = await service.update_schema(
            tenant_id=user.tenant_id,
            schema_id=schema_id,
            field_definitions=[f.model_dump() for f in body.field_definitions],
        )
    except SchemaNotFoundError as exc:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND"}) from exc
    except SchemaInactiveError as exc:
        raise HTTPException(
            status_code=409, detail={"code": "SCHEMA_DEACTIVATED"}
        ) from exc
    except SchemaBreakingChangeError as exc:
        # Req 2.3 — reject and report the conflicting document IDs.
        raise HTTPException(
            status_code=409,
            detail={
                "code": "SCHEMA_BREAKING_CHANGE",
                "message": str(exc),
                "breaking_changes": exc.breaking_changes,
                "conflicting_credential_ids": exc.conflicting_credential_ids,
            },
        ) from exc
    except SchemaValidationError as exc:
        raise HTTPException(
            status_code=422, detail={"code": "SCHEMA_INVALID", "errors": exc.errors}
        ) from exc
    return _schema_response(schema)


@router.delete(
    "/{schema_id}",
    response_model=SchemaResponse,
    dependencies=[Depends(require_permission("schema:delete"))],
)
async def deactivate_schema(
    schema_id: UUID,
    user: TokenPayload = Depends(get_current_user),
    service: SchemaService = Depends(get_schema_service),
) -> SchemaResponse:
    """Deactivate a schema (Req 2.5)."""
    try:
        schema = await service.deactivate_schema(user.tenant_id, schema_id)
    except SchemaNotFoundError as exc:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND"}) from exc
    return _schema_response(schema)


@router.get("/{schema_id}/versions", response_model=list[SchemaVersionResponse])
async def get_schema_versions(
    schema_id: UUID,
    user: TokenPayload = Depends(get_current_user),
    service: SchemaService = Depends(get_schema_service),
) -> list[SchemaVersionResponse]:
    """Get version history (Req 2.4)."""
    versions = await service.get_versions(user.tenant_id, schema_id)
    return [
        SchemaVersionResponse(
            id=str(v.id), version=v.version,
            field_definitions=v.field_definitions,
            created_at=v.created_at.isoformat(),
        )
        for v in versions
    ]


@router.get("/{schema_id}/export")
async def export_schema(
    schema_id: UUID,
    user: TokenPayload = Depends(get_current_user),
    service: SchemaService = Depends(get_schema_service),
) -> dict:
    """Export schema as JSON (Req 2.7)."""
    try:
        return await service.export_schema(user.tenant_id, schema_id)
    except SchemaNotFoundError as exc:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND"}) from exc


def _schema_response(schema) -> SchemaResponse:
    return SchemaResponse(
        id=str(schema.id), name=schema.name, version=schema.version,
        status=schema.status, field_definitions=schema.field_definitions,
        created_at=schema.created_at.isoformat(),
    )
