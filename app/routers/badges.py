"""Badge management endpoints (authenticated) — FR-1..FR-6.

Tenant-admin / issuer facing API for badge classes, images, issuance,
bulk issuance, revocation, and the issuer profile. Public hosted-assertion
retrieval lives in ``app.routers.public_badges`` (unauthenticated).
"""

from __future__ import annotations

import base64
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field

from app.dependencies.auth import TokenPayload, get_current_user
from app.rbac.permissions import require_permission
from app.services.badge_service import (
    BadgeNotFoundError,
    BadgeService,
    BadgeServiceUnavailableError,
    BadgeValidationError,
    get_badge_service,
)
from app.services.certificate_renderer import TEMPLATE_NAMES
from app.services.certificate_service import (
    CertificateNotFoundError,
    CertificateService,
    CertificateServiceUnavailableError,
    CertificateValidationError,
    get_certificate_service,
)
from app.services.issuance_service import (
    AssertionAlreadyRevokedError,
    AssertionNotFoundError,
    IssuanceService,
    IssuanceValidationError,
    get_issuance_service,
)

router = APIRouter(prefix="/badges", tags=["badges"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class BadgeClassRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    criteria_narrative: str | None = Field(default=None, max_length=5000)
    criteria_url: str | None = Field(default=None, max_length=1024)
    tags: list[str] = Field(default_factory=list)
    alignment: list[dict] = Field(default_factory=list)
    validity_days: int | None = Field(default=None, ge=1)


class BadgeClassUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    criteria_narrative: str | None = Field(default=None, max_length=5000)
    criteria_url: str | None = Field(default=None, max_length=1024)
    tags: list[str] | None = None
    alignment: list[dict] | None = None
    validity_days: int | None = Field(default=None, ge=1)


class BadgeClassResponse(BaseModel):
    id: str
    name: str
    description: str | None
    criteria_narrative: str | None
    criteria_url: str | None
    tags: list[str]
    alignment: list[dict]
    image_s3_key: str | None
    validity_days: int | None
    status: str
    directory_visible: bool
    certificate_template: str
    created_at: str | None


class ImageUploadRequest(BaseModel):
    content_base64: str = Field(..., min_length=1)
    content_type: str = Field(..., pattern=r"^image/(png|svg\+xml)$")


class IssueRequest(BaseModel):
    badge_class_id: str = Field(..., min_length=1)
    beneficiary_id: str = Field(..., min_length=1, max_length=512)


class IssueResponse(BaseModel):
    assertion_id: str
    badge_class_id: str
    beneficiary_id: str
    issued_at: str
    expires_at: str | None
    status: str


class BulkIssueRequest(BaseModel):
    badge_class_id: str = Field(..., min_length=1)
    beneficiary_ids: list[str] = Field(..., min_length=1, max_length=10000)


class BulkIssueResponse(BaseModel):
    job_id: str
    status: str


class RevokeRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=500)


class AssertionResponse(BaseModel):
    assertion_id: str
    badge_class_id: str
    beneficiary_id: str
    status: str
    issued_at: str | None
    expires_at: str | None
    public: bool
    revoked_at: str | None
    revocation_reason: str | None


class VisibilityRequest(BaseModel):
    visible: bool


class IssuerProfileRequest(BaseModel):
    issuer_name: str | None = Field(default=None, max_length=255)
    issuer_url: str | None = Field(default=None, max_length=1024)
    issuer_email: str | None = Field(default=None, max_length=255)


class IssuerProfileResponse(BaseModel):
    issuer_name: str | None
    issuer_url: str | None
    issuer_email: str | None


# ---------------------------------------------------------------------------
# Badge class endpoints (FR-1, FR-2)
# ---------------------------------------------------------------------------


@router.post(
    "/classes",
    response_model=BadgeClassResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("badge:create"))],
)
async def create_badge_class(
    body: BadgeClassRequest,
    user: TokenPayload = Depends(get_current_user),
    service: BadgeService = Depends(get_badge_service),
) -> BadgeClassResponse:
    """Create a badge class (FR-1.1)."""
    try:
        badge = await service.create_badge_class(
            tenant_id=user.tenant_id,
            name=body.name,
            description=body.description,
            criteria_narrative=body.criteria_narrative,
            criteria_url=body.criteria_url,
            tags=body.tags,
            alignment=body.alignment,
            validity_days=body.validity_days,
            actor_id=user.sub,
            actor_role=user.roles[0] if user.roles else "tenant_admin",
        )
    except BadgeValidationError as exc:
        raise HTTPException(status_code=422, detail={"code": "VALIDATION_ERROR", "message": str(exc)})
    return _class_response(badge)


@router.get("/classes", response_model=list[BadgeClassResponse])
async def list_badge_classes(
    limit: int = 20,
    offset: int = 0,
    user: TokenPayload = Depends(get_current_user),
    service: BadgeService = Depends(get_badge_service),
    _: TokenPayload = Depends(require_permission("badge:read")),
) -> list[BadgeClassResponse]:
    """List badge classes for the tenant (FR-1.4)."""
    classes = await service.list_badge_classes(user.tenant_id, limit, offset)
    return [_class_response(c) for c in classes]


@router.get("/classes/{badge_class_id}", response_model=BadgeClassResponse)
async def get_badge_class(
    badge_class_id: UUID,
    user: TokenPayload = Depends(get_current_user),
    service: BadgeService = Depends(get_badge_service),
    _: TokenPayload = Depends(require_permission("badge:read")),
) -> BadgeClassResponse:
    """Fetch a single badge class (FR-1.4)."""
    badge = await service.get_badge_class(user.tenant_id, badge_class_id)
    if badge is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND"})
    return _class_response(badge)


@router.patch(
    "/classes/{badge_class_id}",
    response_model=BadgeClassResponse,
    dependencies=[Depends(require_permission("badge:update"))],
)
async def update_badge_class(
    badge_class_id: UUID,
    body: BadgeClassUpdateRequest,
    user: TokenPayload = Depends(get_current_user),
    service: BadgeService = Depends(get_badge_service),
) -> BadgeClassResponse:
    """Update mutable fields of a badge class (FR-1.2)."""
    try:
        badge = await service.update_badge_class(
            tenant_id=user.tenant_id,
            badge_class_id=badge_class_id,
            actor_id=user.sub,
            **body.model_dump(exclude_unset=True),
        )
    except BadgeNotFoundError:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND"})
    except BadgeValidationError as exc:
        raise HTTPException(status_code=422, detail={"code": "VALIDATION_ERROR", "message": str(exc)})
    return _class_response(badge)


@router.post(
    "/classes/{badge_class_id}/deactivate",
    response_model=BadgeClassResponse,
    dependencies=[Depends(require_permission("badge:deactivate"))],
)
async def deactivate_badge_class(
    badge_class_id: UUID,
    user: TokenPayload = Depends(get_current_user),
    service: BadgeService = Depends(get_badge_service),
) -> BadgeClassResponse:
    """Deactivate a badge class (FR-1.3)."""
    try:
        badge = await service.deactivate_badge_class(
            user.tenant_id, badge_class_id, actor_id=user.sub
        )
    except BadgeNotFoundError:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND"})
    return _class_response(badge)


@router.post(
    "/classes/{badge_class_id}/image",
    response_model=BadgeClassResponse,
    dependencies=[Depends(require_permission("badge:update"))],
)
async def upload_badge_image(
    badge_class_id: UUID,
    body: ImageUploadRequest,
    user: TokenPayload = Depends(get_current_user),
    service: BadgeService = Depends(get_badge_service),
) -> BadgeClassResponse:
    """Upload and attach a badge image (FR-2.1, FR-2.2)."""
    try:
        content = base64.b64decode(body.content_base64)
    except Exception:
        raise HTTPException(status_code=422, detail={"code": "INVALID_CONTENT"})
    try:
        badge = await service.attach_image(
            tenant_id=user.tenant_id,
            badge_class_id=badge_class_id,
            content=content,
            content_type=body.content_type,
            actor_id=user.sub,
        )
    except BadgeNotFoundError:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND"})
    except BadgeValidationError as exc:
        raise HTTPException(status_code=422, detail={"code": "VALIDATION_ERROR", "message": str(exc)})
    except BadgeServiceUnavailableError as exc:
        raise HTTPException(status_code=503, detail={"code": "SERVICE_UNAVAILABLE", "message": str(exc)})
    return _class_response(badge)


@router.post(
    "/classes/{badge_class_id}/visibility",
    response_model=BadgeClassResponse,
    dependencies=[Depends(require_permission("badge:publish"))],
)
async def set_visibility(
    badge_class_id: UUID,
    body: VisibilityRequest,
    user: TokenPayload = Depends(get_current_user),
    service: BadgeService = Depends(get_badge_service),
) -> BadgeClassResponse:
    """Toggle public directory visibility of a badge class."""
    try:
        badge = await service.set_directory_visibility(
            user.tenant_id, badge_class_id, body.visible, actor_id=user.sub
        )
    except BadgeNotFoundError:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND"})
    except BadgeValidationError as exc:
        raise HTTPException(status_code=422, detail={"code": "VALIDATION_ERROR", "message": str(exc)})
    return _class_response(badge)


# ---------------------------------------------------------------------------
# Issuance endpoints (FR-4, FR-5, FR-6)
# ---------------------------------------------------------------------------


@router.post(
    "/issue",
    response_model=IssueResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("badge:issue"))],
)
async def issue_badge(
    body: IssueRequest,
    user: TokenPayload = Depends(get_current_user),
    service: IssuanceService = Depends(get_issuance_service),
) -> IssueResponse:
    """Issue a single badge to a beneficiary (FR-4.1)."""
    try:
        result = await service.issue(
            tenant_id=user.tenant_id,
            badge_class_id=UUID(body.badge_class_id),
            beneficiary_id=body.beneficiary_id,
            actor_id=user.sub,
            actor_role=user.roles[0] if user.roles else "issuer",
        )
    except IssuanceValidationError as exc:
        raise HTTPException(status_code=422, detail={"code": "VALIDATION_ERROR", "message": str(exc)})
    return IssueResponse(**result.__dict__)


@router.post(
    "/bulk-issue",
    response_model=BulkIssueResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_permission("badge:bulk_issue"))],
)
async def bulk_issue(
    body: BulkIssueRequest,
    user: TokenPayload = Depends(get_current_user),
    service: IssuanceService = Depends(get_issuance_service),
) -> BulkIssueResponse:
    """Enqueue a bulk badge issuance job (FR-5.1)."""
    try:
        job_id = await service.bulk_issue_enqueue(
            tenant_id=user.tenant_id,
            badge_class_id=UUID(body.badge_class_id),
            beneficiary_ids=body.beneficiary_ids,
            actor_id=user.sub,
        )
    except IssuanceValidationError as exc:
        raise HTTPException(status_code=422, detail={"code": "VALIDATION_ERROR", "message": str(exc)})
    return BulkIssueResponse(job_id=job_id, status="pending")


@router.post(
    "/assertions/{assertion_id}/revoke",
    response_model=AssertionResponse,
    dependencies=[Depends(require_permission("badge:revoke"))],
)
async def revoke_assertion(
    assertion_id: UUID,
    body: RevokeRequest,
    user: TokenPayload = Depends(get_current_user),
    service: IssuanceService = Depends(get_issuance_service),
) -> AssertionResponse:
    """Revoke a badge assertion (FR-6.1). OB-compliant: stays resolvable."""
    try:
        assertion = await service.revoke(
            user.tenant_id, assertion_id, body.reason, actor_id=user.sub
        )
    except AssertionNotFoundError:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND"})
    except AssertionAlreadyRevokedError:
        raise HTTPException(status_code=409, detail={"code": "ALREADY_REVOKED"})
    except IssuanceValidationError as exc:
        raise HTTPException(status_code=422, detail={"code": "VALIDATION_ERROR", "message": str(exc)})
    return _assertion_response(assertion)


@router.get("/assertions/{assertion_id}", response_model=AssertionResponse)
async def get_assertion(
    assertion_id: UUID,
    user: TokenPayload = Depends(get_current_user),
    service: IssuanceService = Depends(get_issuance_service),
    _: TokenPayload = Depends(require_permission("badge:read")),
) -> AssertionResponse:
    """Fetch a single assertion (internal, authenticated view)."""
    assertion = await service.get_assertion(user.tenant_id, assertion_id)
    if assertion is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND"})
    return _assertion_response(assertion)


# ---------------------------------------------------------------------------
# Issuer profile (FR-3)
# ---------------------------------------------------------------------------


@router.get("/issuer-profile", response_model=IssuerProfileResponse)
async def get_issuer_profile(
    user: TokenPayload = Depends(get_current_user),
    service: BadgeService = Depends(get_badge_service),
    _: TokenPayload = Depends(require_permission("badge:read")),
) -> IssuerProfileResponse:
    """Read the tenant's Open Badges issuer profile (FR-3)."""
    profile = await service.get_issuer_profile(user.tenant_id)
    return IssuerProfileResponse(**profile.__dict__)


@router.put(
    "/issuer-profile",
    response_model=IssuerProfileResponse,
    dependencies=[Depends(require_permission("badge:issuer_profile"))],
)
async def set_issuer_profile(
    body: IssuerProfileRequest,
    user: TokenPayload = Depends(get_current_user),
    service: BadgeService = Depends(get_badge_service),
) -> IssuerProfileResponse:
    """Update the tenant's Open Badges issuer profile (FR-3.1)."""
    try:
        profile = await service.set_issuer_profile(
            tenant_id=user.tenant_id,
            issuer_name=body.issuer_name,
            issuer_url=body.issuer_url,
            issuer_email=body.issuer_email,
            actor_id=user.sub,
        )
    except BadgeNotFoundError:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND"})
    return IssuerProfileResponse(**profile.__dict__)


# ---------------------------------------------------------------------------
# Certificates & templates (U4)
# ---------------------------------------------------------------------------


class TemplateRequest(BaseModel):
    certificate_template: str = Field(..., pattern=r"^(classic|modern|elegant|minimal)$")


class PhotoUploadRequest(BaseModel):
    content_base64: str = Field(..., min_length=1)
    content_type: str = Field(..., pattern=r"^image/(png|jpe?g)$")


@router.get("/certificate-templates", response_model=list[str])
async def list_certificate_templates(
    _: TokenPayload = Depends(require_permission("badge:read")),
) -> list[str]:
    """List the built-in certificate template names (FR — U4 Q1)."""
    return list(TEMPLATE_NAMES)


@router.put(
    "/classes/{badge_class_id}/template",
    response_model=BadgeClassResponse,
    dependencies=[Depends(require_permission("badge:update"))],
)
async def set_certificate_template(
    badge_class_id: UUID,
    body: TemplateRequest,
    user: TokenPayload = Depends(get_current_user),
    service: BadgeService = Depends(get_badge_service),
) -> BadgeClassResponse:
    """Choose the certificate template for a badge class (U4 Q2)."""
    try:
        badge = await service.update_badge_class(
            tenant_id=user.tenant_id,
            badge_class_id=badge_class_id,
            actor_id=user.sub,
            certificate_template=body.certificate_template,
        )
    except BadgeNotFoundError:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND"})
    except BadgeValidationError as exc:
        raise HTTPException(status_code=422, detail={"code": "VALIDATION_ERROR", "message": str(exc)})
    return _class_response(badge)


@router.post(
    "/assertions/{assertion_id}/photo",
    dependencies=[Depends(require_permission("badge:update"))],
)
async def upload_recipient_photo(
    assertion_id: UUID,
    body: PhotoUploadRequest,
    user: TokenPayload = Depends(get_current_user),
    service: CertificateService = Depends(get_certificate_service),
) -> dict:
    """Upload the recipient (student) photo for an assertion (U4 Q6)."""
    import base64

    try:
        content = base64.b64decode(body.content_base64)
    except Exception:
        raise HTTPException(status_code=422, detail={"code": "INVALID_CONTENT"})
    try:
        s3_key = await service.upload_recipient_photo(
            tenant_id=user.tenant_id,
            assertion_id=assertion_id,
            content=content,
            content_type=body.content_type,
            actor_id=user.sub,
            actor_role=user.roles[0] if user.roles else "issuer",
        )
    except CertificateNotFoundError:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND"})
    except CertificateValidationError as exc:
        raise HTTPException(status_code=422, detail={"code": "VALIDATION_ERROR", "message": str(exc)})
    except CertificateServiceUnavailableError as exc:
        raise HTTPException(status_code=503, detail={"code": "SERVICE_UNAVAILABLE", "message": str(exc)})
    return {"status": "ok", "photo_key": s3_key}


@router.get(
    "/assertions/{assertion_id}/certificate",
    dependencies=[Depends(require_permission("badge:certificate"))],
)
async def download_certificate(
    assertion_id: UUID,
    user: TokenPayload = Depends(get_current_user),
    service: CertificateService = Depends(get_certificate_service),
) -> Response:
    """Download the issuer-signed certificate PDF for an assertion (U4 Q4 issuer)."""
    try:
        cert = await service.build_certificate(
            tenant_id=user.tenant_id,
            assertion_id=assertion_id,
            actor_id=user.sub,
            actor_role=user.roles[0] if user.roles else "issuer",
        )
    except CertificateNotFoundError:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND"})
    return Response(
        content=cert.content,
        media_type=cert.media_type,
        headers={"Content-Disposition": f'attachment; filename="{cert.filename}"'},
    )


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------


def _class_response(badge) -> BadgeClassResponse:
    return BadgeClassResponse(
        id=str(badge.id),
        name=badge.name,
        description=badge.description,
        criteria_narrative=badge.criteria_narrative,
        criteria_url=badge.criteria_url,
        tags=badge.tags or [],
        alignment=badge.alignment or [],
        image_s3_key=badge.image_s3_key,
        validity_days=badge.validity_days,
        status=badge.status,
        directory_visible=badge.directory_visible,
        certificate_template=getattr(badge, "certificate_template", "classic"),
        created_at=badge.created_at.isoformat() if badge.created_at else None,
    )


def _assertion_response(a) -> AssertionResponse:
    return AssertionResponse(
        assertion_id=str(a.id),
        badge_class_id=str(a.badge_class_id),
        beneficiary_id=a.beneficiary_id,
        status=a.status,
        issued_at=a.issued_at.isoformat() if a.issued_at else None,
        expires_at=a.expires_at.isoformat() if a.expires_at else None,
        public=a.public,
        revoked_at=a.revoked_at.isoformat() if a.revoked_at else None,
        revocation_reason=a.revocation_reason,
    )
