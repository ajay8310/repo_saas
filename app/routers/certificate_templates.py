"""Certificate template designer endpoints (authenticated, U5).

Issuer/admin-facing CRUD for custom certificate templates, asset upload
(institution logo + background), server-side PDF preview, and assignment to a
badge class. Guarded by the new ``badge:template_manage`` permission (reads use
``badge:read``). All operations are tenant-scoped via the service layer.
"""

from __future__ import annotations

import base64
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field

from app.dependencies.auth import TokenPayload, get_current_user
from app.rbac.permissions import require_permission
from app.services.certificate_template_service import (
    CertificateTemplateService,
    TemplateInUseError,
    TemplateNotFoundError,
    TemplateServiceUnavailableError,
    TemplateValidationError,
    get_certificate_template_service,
)

router = APIRouter(prefix="/certificate-templates", tags=["certificate-templates"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class TemplateCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    orientation: str = Field(default="portrait", pattern=r"^(portrait|landscape)$")
    layout: dict = Field(default_factory=dict)


class TemplateUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    orientation: str | None = Field(default=None, pattern=r"^(portrait|landscape)$")
    layout: dict | None = None


class AssetUploadRequest(BaseModel):
    kind: str = Field(..., pattern=r"^(logo|background)$")
    content_base64: str = Field(..., min_length=1)
    content_type: str = Field(..., pattern=r"^image/(png|jpe?g)$")


class InlinePreviewRequest(BaseModel):
    layout: dict = Field(default_factory=dict)
    logo_s3_key: str | None = None
    background_s3_key: str | None = None


class AssignRequest(BaseModel):
    badge_class_id: UUID
    custom_template_id: UUID | None = None


class TemplateResponse(BaseModel):
    id: str
    name: str
    orientation: str
    layout: dict
    logo_s3_key: str | None
    background_s3_key: str | None
    version: int
    status: str
    created_at: str | None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=TemplateResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("badge:template_manage"))],
)
async def create_template(
    body: TemplateCreateRequest,
    user: TokenPayload = Depends(get_current_user),
    service: CertificateTemplateService = Depends(get_certificate_template_service),
) -> TemplateResponse:
    """Create a new certificate template (FR-U5-1)."""
    try:
        tpl = await service.create(
            tenant_id=user.tenant_id,
            name=body.name,
            orientation=body.orientation,
            layout=body.layout,
            actor_id=user.sub,
            actor_role=user.roles[0] if user.roles else "issuer",
        )
    except TemplateValidationError as exc:
        raise HTTPException(status_code=422, detail={"code": "VALIDATION_ERROR", "message": str(exc)})
    return _response(tpl)


@router.get(
    "",
    response_model=list[TemplateResponse],
    dependencies=[Depends(require_permission("badge:read"))],
)
async def list_templates(
    user: TokenPayload = Depends(get_current_user),
    service: CertificateTemplateService = Depends(get_certificate_template_service),
) -> list[TemplateResponse]:
    """List this tenant's certificate templates (FR-U5-11)."""
    rows = await service.list(user.tenant_id)
    return [_response(t) for t in rows]


@router.get(
    "/{template_id}",
    response_model=TemplateResponse,
    dependencies=[Depends(require_permission("badge:read"))],
)
async def get_template(
    template_id: UUID,
    user: TokenPayload = Depends(get_current_user),
    service: CertificateTemplateService = Depends(get_certificate_template_service),
) -> TemplateResponse:
    tpl = await service.get(user.tenant_id, template_id)
    if tpl is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND"})
    return _response(tpl)


@router.put(
    "/{template_id}",
    response_model=TemplateResponse,
    dependencies=[Depends(require_permission("badge:template_manage"))],
)
async def update_template(
    template_id: UUID,
    body: TemplateUpdateRequest,
    user: TokenPayload = Depends(get_current_user),
    service: CertificateTemplateService = Depends(get_certificate_template_service),
) -> TemplateResponse:
    """Update a template's name/orientation/layout; bumps version (FR-U5-13)."""
    try:
        tpl = await service.update(
            tenant_id=user.tenant_id,
            template_id=template_id,
            name=body.name,
            orientation=body.orientation,
            layout=body.layout,
            actor_id=user.sub,
            actor_role=user.roles[0] if user.roles else "issuer",
        )
    except TemplateNotFoundError:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND"})
    except TemplateValidationError as exc:
        raise HTTPException(status_code=422, detail={"code": "VALIDATION_ERROR", "message": str(exc)})
    return _response(tpl)


@router.delete(
    "/{template_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    dependencies=[Depends(require_permission("badge:template_manage"))],
)
async def delete_template(
    template_id: UUID,
    user: TokenPayload = Depends(get_current_user),
    service: CertificateTemplateService = Depends(get_certificate_template_service),
) -> Response:
    """Archive a template (blocked with 409 if assigned to a badge class)."""
    try:
        await service.delete(
            tenant_id=user.tenant_id,
            template_id=template_id,
            actor_id=user.sub,
            actor_role=user.roles[0] if user.roles else "issuer",
        )
    except TemplateNotFoundError:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND"})
    except TemplateInUseError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "CONFLICT", "message": str(exc)},
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{template_id}/assets",
    dependencies=[Depends(require_permission("badge:template_manage"))],
)
async def upload_asset(
    template_id: UUID,
    body: AssetUploadRequest,
    user: TokenPayload = Depends(get_current_user),
    service: CertificateTemplateService = Depends(get_certificate_template_service),
) -> dict:
    """Upload the institution logo or a background image (FR-U5-6, FR-U5-7)."""
    try:
        content = base64.b64decode(body.content_base64)
    except Exception:
        raise HTTPException(status_code=422, detail={"code": "INVALID_CONTENT"})
    try:
        s3_key = await service.upload_asset(
            tenant_id=user.tenant_id,
            template_id=template_id,
            kind=body.kind,
            content=content,
            content_type=body.content_type,
            actor_id=user.sub,
            actor_role=user.roles[0] if user.roles else "issuer",
        )
    except TemplateNotFoundError:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND"})
    except TemplateValidationError as exc:
        raise HTTPException(status_code=422, detail={"code": "VALIDATION_ERROR", "message": str(exc)})
    except TemplateServiceUnavailableError as exc:
        raise HTTPException(status_code=503, detail={"code": "SERVICE_UNAVAILABLE", "message": str(exc)})
    return {"status": "ok", "kind": body.kind, "s3_key": s3_key}


@router.post(
    "/preview",
    dependencies=[Depends(require_permission("badge:template_manage"))],
)
async def preview_inline(
    body: InlinePreviewRequest,
    user: TokenPayload = Depends(get_current_user),
    service: CertificateTemplateService = Depends(get_certificate_template_service),
) -> Response:
    """Render an unsaved layout to a sample PDF for the live designer (FR-U5-8)."""
    preview = await service.render_preview(
        tenant_id=user.tenant_id,
        layout=body.layout,
        logo_s3_key=body.logo_s3_key,
        background_s3_key=body.background_s3_key,
    )
    return Response(
        content=preview.content,
        media_type=preview.media_type,
        headers={"Content-Disposition": f'inline; filename="{preview.filename}"'},
    )


@router.post(
    "/{template_id}/preview",
    dependencies=[Depends(require_permission("badge:template_manage"))],
)
async def preview_saved(
    template_id: UUID,
    user: TokenPayload = Depends(get_current_user),
    service: CertificateTemplateService = Depends(get_certificate_template_service),
) -> Response:
    """Render a saved template to a sample PDF (FR-U5-8)."""
    try:
        preview = await service.render_preview_of(user.tenant_id, template_id)
    except TemplateNotFoundError:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND"})
    return Response(
        content=preview.content,
        media_type=preview.media_type,
        headers={"Content-Disposition": f'inline; filename="{preview.filename}"'},
    )


@router.post(
    "/assign",
    dependencies=[Depends(require_permission("badge:template_manage"))],
)
async def assign_template(
    body: AssignRequest,
    user: TokenPayload = Depends(get_current_user),
    service: CertificateTemplateService = Depends(get_certificate_template_service),
) -> dict:
    """Assign (or clear) a custom template on a badge class (FR-U5-9)."""
    try:
        badge = await service.assign_to_class(
            tenant_id=user.tenant_id,
            badge_class_id=body.badge_class_id,
            template_id=body.custom_template_id,
            actor_id=user.sub,
            actor_role=user.roles[0] if user.roles else "issuer",
        )
    except TemplateNotFoundError:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND"})
    return {
        "status": "ok",
        "badge_class_id": str(badge.id),
        "custom_template_id": str(badge.custom_template_id) if badge.custom_template_id else None,
    }


# ---------------------------------------------------------------------------
# Serializer
# ---------------------------------------------------------------------------


def _response(tpl) -> TemplateResponse:
    return TemplateResponse(
        id=str(tpl.id),
        name=tpl.name,
        orientation=tpl.orientation,
        layout=tpl.layout or {},
        logo_s3_key=tpl.logo_s3_key,
        background_s3_key=tpl.background_s3_key,
        version=tpl.version,
        status=tpl.status,
        created_at=tpl.created_at.isoformat() if tpl.created_at else None,
    )
