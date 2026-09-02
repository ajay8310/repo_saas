"""
Tenant management endpoints.

- POST /api/v1/admin/tenants — create a new tenant (Super_Admin)
- POST /api/v1/admin/tenants/{id}/approve — approve a pending tenant
- POST /api/v1/admin/tenants/{id}/suspend — suspend a tenant
- POST /api/v1/admin/tenants/{id}/deactivate — deactivate a tenant
- POST /api/v1/admin/tenants/{id}/reactivate — reactivate a suspended tenant
- PATCH /api/v1/admin/tenants/{id} — update tenant config
- POST /api/v1/admin/tenants/{id}/rotate-key — rotate API credentials
- GET /api/v1/admin/tenants/{id} — get tenant details

Requirements: 1.1–1.9, 13.4, 13.9
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.rbac.permissions import require_permission
from app.services.tenant_service import (
    TenantConflictError,
    TenantNotFoundError,
    TenantService,
    TenantTransitionError,
    get_tenant_service,
)

router = APIRouter(prefix="/admin/tenants", tags=["tenant-management"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class CreateTenantRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    namespace: str = Field(..., min_length=1, max_length=63, pattern=r"^[a-z][a-z0-9_-]*$")
    domain: str = Field(..., min_length=1, max_length=255)
    contact_email: str = Field(..., max_length=255)


class TenantCredentialsResponse(BaseModel):
    tenant_id: str
    namespace: str
    client_id: str
    client_secret: str


class TenantResponse(BaseModel):
    id: str
    namespace: str
    name: str
    domain: str
    contact_email: str
    status: str
    storage_quota_bytes: int
    rate_limit_per_hour: int
    retention_years: int
    created_at: datetime
    updated_at: datetime


class UpdateTenantConfigRequest(BaseModel):
    storage_quota_bytes: int | None = Field(
        default=None, ge=1_048_576, le=10_995_116_277_760,
        description="Storage quota in bytes (1 MB to 10 TB)",
    )
    rate_limit_per_hour: int | None = Field(
        default=None, ge=1, le=1_000_000,
        description="Maximum requests per hour (1 to 1,000,000)",
    )
    retention_years: int | None = Field(
        default=None, ge=1, le=99,
        description="Data retention period in years (1 to 99)",
    )


class RotateKeyRequest(BaseModel):
    grace_hours: int = Field(default=24, ge=1, le=168, description="Grace period in hours")


class RotatedCredentialsResponse(BaseModel):
    new_client_id: str
    new_client_secret: str
    grace_until: datetime


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=TenantCredentialsResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("tenant:create"))],
)
async def create_tenant(
    body: CreateTenantRequest,
    service: TenantService = Depends(get_tenant_service),
) -> TenantCredentialsResponse:
    """Create a new tenant with API credentials (Req 1.1, 1.2)."""
    try:
        result = await service.create_tenant(
            name=body.name,
            namespace=body.namespace,
            domain=body.domain,
            contact_email=body.contact_email,
        )
    except TenantConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "DOMAIN_CONFLICT",
                "message": str(exc),
                "field": exc.field,
            },
        ) from exc

    return TenantCredentialsResponse(
        tenant_id=result.tenant_id,
        namespace=result.namespace,
        client_id=result.client_id,
        client_secret=result.client_secret,
    )


@router.post(
    "/{tenant_id}/approve",
    response_model=TenantResponse,
    dependencies=[Depends(require_permission("tenant:approve"))],
)
async def approve_tenant(
    tenant_id: UUID,
    service: TenantService = Depends(get_tenant_service),
) -> TenantResponse:
    """Approve a pending tenant (Req 1.4)."""
    try:
        tenant = await service.approve_tenant(tenant_id)
    except TenantNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": str(exc)},
        ) from exc
    except TenantTransitionError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "INVALID_TRANSITION", "message": str(exc)},
        ) from exc

    return _tenant_to_response(tenant)


@router.post(
    "/{tenant_id}/suspend",
    response_model=TenantResponse,
    dependencies=[Depends(require_permission("tenant:suspend"))],
)
async def suspend_tenant(
    tenant_id: UUID,
    service: TenantService = Depends(get_tenant_service),
) -> TenantResponse:
    """Suspend a tenant — deny all API access (Req 1.5)."""
    try:
        tenant = await service.suspend_tenant(tenant_id)
    except TenantNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": str(exc)},
        ) from exc
    except TenantTransitionError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "INVALID_TRANSITION", "message": str(exc)},
        ) from exc

    return _tenant_to_response(tenant)


@router.post(
    "/{tenant_id}/deactivate",
    response_model=TenantResponse,
    dependencies=[Depends(require_permission("tenant:deactivate"))],
)
async def deactivate_tenant(
    tenant_id: UUID,
    service: TenantService = Depends(get_tenant_service),
) -> TenantResponse:
    """Deactivate a tenant — read-only archive state (Req 1.6)."""
    try:
        tenant = await service.deactivate_tenant(tenant_id)
    except TenantNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": str(exc)},
        ) from exc
    except TenantTransitionError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "INVALID_TRANSITION", "message": str(exc)},
        ) from exc

    return _tenant_to_response(tenant)


@router.post(
    "/{tenant_id}/reactivate",
    response_model=TenantResponse,
    dependencies=[Depends(require_permission("tenant:approve"))],
)
async def reactivate_tenant(
    tenant_id: UUID,
    service: TenantService = Depends(get_tenant_service),
) -> TenantResponse:
    """Reactivate a suspended tenant."""
    try:
        tenant = await service.reactivate_tenant(tenant_id)
    except TenantNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": str(exc)},
        ) from exc
    except TenantTransitionError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "INVALID_TRANSITION", "message": str(exc)},
        ) from exc

    return _tenant_to_response(tenant)


@router.patch(
    "/{tenant_id}",
    response_model=TenantResponse,
    dependencies=[Depends(require_permission("tenant:update"))],
)
async def update_tenant_config(
    tenant_id: UUID,
    body: UpdateTenantConfigRequest,
    service: TenantService = Depends(get_tenant_service),
) -> TenantResponse:
    """Update per-tenant storage quota, rate limit, and retention (Req 1.7)."""
    try:
        tenant = await service.update_tenant_config(
            tenant_id=tenant_id,
            storage_quota_bytes=body.storage_quota_bytes,
            rate_limit_per_hour=body.rate_limit_per_hour,
            retention_years=body.retention_years,
        )
    except TenantNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": str(exc)},
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "VALIDATION_ERROR", "message": str(exc)},
        ) from exc

    return _tenant_to_response(tenant)


@router.post(
    "/{tenant_id}/rotate-key",
    response_model=RotatedCredentialsResponse,
    dependencies=[Depends(require_permission("tenant:rotate_key"))],
)
async def rotate_api_key(
    tenant_id: UUID,
    body: RotateKeyRequest = RotateKeyRequest(),
    service: TenantService = Depends(get_tenant_service),
) -> RotatedCredentialsResponse:
    """Rotate API credentials with grace period (Req 13.4, 13.9)."""
    try:
        result = await service.rotate_api_key(
            tenant_id=tenant_id,
            grace_hours=body.grace_hours,
        )
    except TenantNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": str(exc)},
        ) from exc

    return RotatedCredentialsResponse(
        new_client_id=result.new_client_id,
        new_client_secret=result.new_client_secret,
        grace_until=result.grace_until,
    )


@router.get(
    "/{tenant_id}",
    response_model=TenantResponse,
    dependencies=[Depends(require_permission("tenant:read"))],
)
async def get_tenant(
    tenant_id: UUID,
    service: TenantService = Depends(get_tenant_service),
) -> TenantResponse:
    """Get tenant details."""
    try:
        tenant = await service.get_tenant(tenant_id)
    except TenantNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": str(exc)},
        ) from exc

    return _tenant_to_response(tenant)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tenant_to_response(tenant) -> TenantResponse:
    return TenantResponse(
        id=str(tenant.id),
        namespace=tenant.namespace,
        name=tenant.name,
        domain=tenant.domain,
        contact_email=tenant.contact_email,
        status=tenant.status,
        storage_quota_bytes=tenant.storage_quota_bytes,
        rate_limit_per_hour=tenant.rate_limit_per_hour,
        retention_years=tenant.retention_years,
        created_at=tenant.created_at,
        updated_at=tenant.updated_at,
    )
