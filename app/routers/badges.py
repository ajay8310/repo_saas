"""Badge management endpoints (authenticated) — FR-1..FR-6.

Tenant-admin / issuer facing API for badge classes, images, issuance,
bulk issuance, revocation, and the issuer profile. Public hosted-assertion
retrieval lives in ``app.routers.public_badges`` (unauthenticated).
"""

from __future__ import annotations

import base64
from dataclasses import asdict
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field

from app.dependencies.auth import TokenPayload, get_current_user
from app.rbac.permissions import require_permission
from app.services.badge_baker import BadgeImageNotBakeableError
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
from app.services.zip_bulk_service import (
    ZipBulkService,
    ZipBulkServiceUnavailableError,
    ZipBulkValidationError,
    get_zip_bulk_service,
)

# Photos-only bulk-attach reuses the generic ZIP presign; the badge class is
# optional there (attach to all of a recipient's active credentials by default).

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
    custom_template_id: str | None = None
    created_at: str | None


class ImageUploadRequest(BaseModel):
    content_base64: str = Field(..., min_length=1)
    content_type: str = Field(..., pattern=r"^image/(png|svg\+xml)$")


class IssueRequest(BaseModel):
    badge_class_id: str = Field(..., min_length=1)
    beneficiary_id: str = Field(..., min_length=1, max_length=512)
    # Optional student photo supplied at issue-time (U4 Q6). Both must be
    # present together; the photo is attached to the new assertion so the first
    # certificate download already shows it.
    photo_base64: str | None = Field(default=None)
    photo_content_type: str | None = Field(default=None, pattern=r"^image/(png|jpe?g)$")


class IssueResponse(BaseModel):
    assertion_id: str
    badge_class_id: str
    beneficiary_id: str
    issued_at: str
    expires_at: str | None
    status: str
    has_photo: bool = False


class BulkIssueRequest(BaseModel):
    badge_class_id: str = Field(..., min_length=1)
    beneficiary_ids: list[str] = Field(..., min_length=1, max_length=10000)


class BulkIssueResponse(BaseModel):
    job_id: str
    status: str


class BulkIssueZipPresignRequest(BaseModel):
    # Optional: required for the issue flow, omitted for a photos-only upload.
    badge_class_id: str | None = Field(default=None)
    # Size (bytes) of the ZIP the client intends to upload; checked against the cap.
    size_bytes: int = Field(..., ge=1)


class BulkIssueZipPresignResponse(BaseModel):
    upload_url: str
    zip_key: str
    max_bytes: int


class BulkIssueZipRequest(BaseModel):
    badge_class_id: str = Field(..., min_length=1)
    # S3 key of the ZIP the client already uploaded via the presigned PUT URL.
    zip_key: str = Field(..., min_length=1)


class BulkIssueZipResponse(BaseModel):
    job_id: str
    status: str
    total: int
    with_photo: int
    errors: list[dict] = Field(default_factory=list)


class BulkPhotosZipRequest(BaseModel):
    # S3 key of the photos-only ZIP already uploaded via the presigned PUT URL.
    zip_key: str = Field(..., min_length=1)
    # Optional: scope the attach to one badge class; default is all of each
    # recipient's active credentials.
    badge_class_id: str | None = Field(default=None)


class BulkPhotosZipResponse(BaseModel):
    job_id: str
    status: str
    total: int
    errors: list[dict] = Field(default_factory=list)


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


class AssertionListItem(BaseModel):
    """A row for the issuer Documents list (assertion + badge-class summary, U6)."""

    assertion_id: str
    badge_class_id: str
    badge_name: str
    beneficiary_id: str
    status: str
    issued_at: str | None
    expires_at: str | None
    public: bool
    revoked_at: str | None
    has_photo: bool = False


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
    cert_service: CertificateService = Depends(get_certificate_service),
) -> IssueResponse:
    """Issue a single badge to a beneficiary (FR-4.1), optionally with a photo.

    When ``photo_base64`` + ``photo_content_type`` are supplied, the student
    photo is attached to the freshly issued assertion via the same validated,
    malware-scanned, encrypted path as the standalone photo endpoint, so the
    first certificate download already carries the photo.
    """
    if (body.photo_base64 is None) != (body.photo_content_type is None):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "VALIDATION_ERROR",
                "message": "photo_base64 and photo_content_type must be provided together",
            },
        )

    actor_role = user.roles[0] if user.roles else "issuer"
    try:
        result = await service.issue(
            tenant_id=user.tenant_id,
            badge_class_id=UUID(body.badge_class_id),
            beneficiary_id=body.beneficiary_id,
            actor_id=user.sub,
            actor_role=actor_role,
        )
    except IssuanceValidationError as exc:
        raise HTTPException(status_code=422, detail={"code": "VALIDATION_ERROR", "message": str(exc)})

    has_photo = False
    if body.photo_base64 is not None and body.photo_content_type is not None:
        try:
            content = base64.b64decode(body.photo_base64)
        except Exception:
            raise HTTPException(status_code=422, detail={"code": "INVALID_CONTENT"})
        try:
            await cert_service.upload_recipient_photo(
                tenant_id=user.tenant_id,
                assertion_id=UUID(result.assertion_id),
                content=content,
                content_type=body.photo_content_type,
                actor_id=user.sub,
                actor_role=actor_role,
            )
            has_photo = True
        except CertificateValidationError as exc:
            # The badge is already issued; surface the photo problem without
            # losing the assertion. The issuer can retry via the Documents page.
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "PHOTO_REJECTED",
                    "message": str(exc),
                    "assertion_id": result.assertion_id,
                },
            )
        except CertificateServiceUnavailableError as exc:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "SERVICE_UNAVAILABLE",
                    "message": str(exc),
                    "assertion_id": result.assertion_id,
                },
            )

    return IssueResponse(**asdict(result), has_photo=has_photo)


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
    "/bulk-issue-zip/presign",
    response_model=BulkIssueZipPresignResponse,
    dependencies=[Depends(require_permission("badge:bulk_issue"))],
)
async def bulk_issue_zip_presign(
    body: BulkIssueZipPresignRequest,
    user: TokenPayload = Depends(get_current_user),
    issuance: IssuanceService = Depends(get_issuance_service),
    zip_service: ZipBulkService = Depends(get_zip_bulk_service),
) -> BulkIssueZipPresignResponse:
    """Issue a presigned PUT URL for a direct-to-S3 bulk ZIP upload (<= 100 MB).

    The browser PUTs the raw ``.zip`` to the returned URL, then calls
    ``/bulk-issue-zip`` (issue flow) or ``/bulk-photos-zip`` (photos-only) with
    the returned ``zip_key``. The size cap is enforced here (before a URL is
    granted) and again when the object is read. ``badge_class_id`` is validated
    when supplied (issue flow); it is omitted for a photos-only upload.
    """
    if body.badge_class_id:
        try:
            await issuance.ensure_class_issuable(user.tenant_id, UUID(body.badge_class_id))
        except IssuanceValidationError as exc:
            raise HTTPException(status_code=422, detail={"code": "VALIDATION_ERROR", "message": str(exc)})

    try:
        url, key = zip_service.presign_upload(user.tenant_id, body.size_bytes)
    except ZipBulkValidationError as exc:
        raise HTTPException(status_code=422, detail={"code": "VALIDATION_ERROR", "message": str(exc)})
    except ZipBulkServiceUnavailableError as exc:
        raise HTTPException(status_code=503, detail={"code": "SERVICE_UNAVAILABLE", "message": str(exc)})

    return BulkIssueZipPresignResponse(
        upload_url=url, zip_key=key, max_bytes=zip_service.settings.bulk_zip_max_bytes
    )


@router.post(
    "/bulk-issue-zip",
    response_model=BulkIssueZipResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_permission("badge:bulk_issue"))],
)
async def bulk_issue_zip(
    body: BulkIssueZipRequest,
    user: TokenPayload = Depends(get_current_user),
    issuance: IssuanceService = Depends(get_issuance_service),
    zip_service: ZipBulkService = Depends(get_zip_bulk_service),
) -> BulkIssueZipResponse:
    """Bulk-issue badges from an uploaded ZIP of recipients + photos (ZIP flow).

    The client first uploads the ZIP to S3 via a presigned PUT URL (see
    ``/bulk-issue-zip/presign``) and passes the resulting ``zip_key`` here. The
    ZIP carries a ``recipients.csv``/``recipients.json`` manifest plus photo
    images matched per recipient; a one-row manifest + one photo is the single
    upload case. The server reads the ZIP from S3 (re-checking the 100 MB cap),
    validates + stages inline, enqueues the issuance + photo-attach Celery job,
    and deletes the uploaded ZIP. Returns the job id and a parse summary.
    """
    # Fail fast if the badge class is missing/inactive before reading anything.
    try:
        await issuance.ensure_class_issuable(user.tenant_id, UUID(body.badge_class_id))
    except IssuanceValidationError as exc:
        raise HTTPException(status_code=422, detail={"code": "VALIDATION_ERROR", "message": str(exc)})

    try:
        plan = zip_service.parse_and_stage_from_key(user.tenant_id, body.zip_key)
    except ZipBulkValidationError as exc:
        raise HTTPException(status_code=422, detail={"code": "VALIDATION_ERROR", "message": str(exc)})
    except ZipBulkServiceUnavailableError as exc:
        raise HTTPException(status_code=503, detail={"code": "SERVICE_UNAVAILABLE", "message": str(exc)})

    recipients = [
        {
            "beneficiary_id": r.beneficiary_id,
            "photo_key": r.photo_key,
            "photo_content_type": r.photo_content_type,
        }
        for r in plan.recipients
    ]
    with_photo = sum(1 for r in plan.recipients if r.photo_key)

    from app.tasks.badge_bulk import bulk_issue_badges_with_photos

    bulk_issue_badges_with_photos.delay(
        job_id=plan.job_id,
        tenant_id=str(user.tenant_id),
        badge_class_id=body.badge_class_id,
        recipients=recipients,
        actor_id=user.sub,
    )
    return BulkIssueZipResponse(
        job_id=plan.job_id,
        status="pending",
        total=plan.total,
        with_photo=with_photo,
        errors=plan.errors,
    )


@router.post(
    "/bulk-photos-zip",
    response_model=BulkPhotosZipResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_permission("badge:update"))],
)
async def bulk_photos_zip(
    body: BulkPhotosZipRequest,
    user: TokenPayload = Depends(get_current_user),
    issuance: IssuanceService = Depends(get_issuance_service),
    zip_service: ZipBulkService = Depends(get_zip_bulk_service),
) -> BulkPhotosZipResponse:
    """Attach a ZIP of photos to already-issued credentials (later upload).

    Decouples photos from issuance: credentials issued earlier can have their
    student photos uploaded now. The client first uploads the photos-only ZIP
    via the presigned PUT URL (``/bulk-issue-zip/presign`` with no badge class),
    then passes the ``zip_key`` here. Each image is matched to the recipient's
    existing active credential(s) by email (image filename stem or an optional
    ``photos.csv``/``photos.json`` map). Matching + attaching run in a Celery
    job. Returns the job id and how many photos were parsed; recipients with no
    issued credential yet are reported as job errors.
    """
    if body.badge_class_id:
        try:
            await issuance.ensure_class_issuable(user.tenant_id, UUID(body.badge_class_id))
        except IssuanceValidationError as exc:
            raise HTTPException(status_code=422, detail={"code": "VALIDATION_ERROR", "message": str(exc)})

    try:
        plan = zip_service.parse_photos_from_key(user.tenant_id, body.zip_key)
    except ZipBulkValidationError as exc:
        raise HTTPException(status_code=422, detail={"code": "VALIDATION_ERROR", "message": str(exc)})
    except ZipBulkServiceUnavailableError as exc:
        raise HTTPException(status_code=503, detail={"code": "SERVICE_UNAVAILABLE", "message": str(exc)})

    photos = [
        {
            "beneficiary_id": p.beneficiary_id,
            "photo_key": p.photo_key,
            "photo_content_type": p.photo_content_type,
        }
        for p in plan.photos
    ]

    from app.tasks.badge_bulk import bulk_attach_photos

    bulk_attach_photos.delay(
        job_id=plan.job_id,
        tenant_id=str(user.tenant_id),
        photos=photos,
        actor_id=user.sub,
        badge_class_id=body.badge_class_id,
    )
    return BulkPhotosZipResponse(
        job_id=plan.job_id,
        status="pending",
        total=plan.total,
        errors=plan.errors,
    )


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


@router.get("/assertions", response_model=list[AssertionListItem])
async def list_assertions(
    status_filter: str | None = None,
    limit: int = 50,
    offset: int = 0,
    user: TokenPayload = Depends(get_current_user),
    service: IssuanceService = Depends(get_issuance_service),
    badge_service: BadgeService = Depends(get_badge_service),
    _: TokenPayload = Depends(require_permission("badge:read")),
) -> list[AssertionListItem]:
    """List all issued assertions for the tenant, newest first (U6).

    Powers the issuer Documents page. Badge-class names are resolved with a
    single keyed lookup (no join), mirroring the wallet list.
    """
    assertions = await service.list_assertions(
        tenant_id=user.tenant_id, status=status_filter, limit=limit, offset=offset
    )
    if not assertions:
        return []
    class_ids = {a.badge_class_id for a in assertions}
    names: dict = {}
    for cid in class_ids:
        bc = await badge_service.get_badge_class(user.tenant_id, cid)
        names[cid] = bc.name if bc else "Unknown Badge"
    return [
        AssertionListItem(
            assertion_id=str(a.id),
            badge_class_id=str(a.badge_class_id),
            badge_name=names.get(a.badge_class_id, "Unknown Badge"),
            beneficiary_id=a.beneficiary_id,
            status=a.status,
            issued_at=a.issued_at.isoformat() if a.issued_at else None,
            expires_at=a.expires_at.isoformat() if a.expires_at else None,
            public=a.public,
            revoked_at=a.revoked_at.isoformat() if a.revoked_at else None,
            has_photo=bool(a.recipient_photo_s3_key),
        )
        for a in assertions
    ]


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
    return IssuerProfileResponse(**asdict(profile))


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
    return IssuerProfileResponse(**asdict(profile))


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


@router.get(
    "/assertions/{assertion_id}/badge.json",
    dependencies=[Depends(require_permission("badge:certificate"))],
)
async def download_badge_json(
    assertion_id: UUID,
    user: TokenPayload = Depends(get_current_user),
    service: CertificateService = Depends(get_certificate_service),
) -> Response:
    """Download the Open Badges 2.0 assertion JSON for an assertion (U6)."""
    try:
        badge = await service.build_badge_json(
            tenant_id=user.tenant_id,
            assertion_id=assertion_id,
            actor_id=user.sub,
            actor_role=user.roles[0] if user.roles else "issuer",
        )
    except CertificateNotFoundError:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND"})
    return Response(
        content=badge.content,
        media_type=badge.media_type,
        headers={"Content-Disposition": f'attachment; filename="{badge.filename}"'},
    )


@router.get(
    "/assertions/{assertion_id}/badge.png",
    dependencies=[Depends(require_permission("badge:certificate"))],
)
async def download_badge_png(
    assertion_id: UUID,
    user: TokenPayload = Depends(get_current_user),
    service: CertificateService = Depends(get_certificate_service),
) -> Response:
    """Download a baked Open Badges PNG for an assertion (U6).

    422 when the badge class has no image or the image is not a PNG (e.g. SVG);
    the JSON download still works in that case.
    """
    try:
        badge = await service.build_badge_png(
            tenant_id=user.tenant_id,
            assertion_id=assertion_id,
            actor_id=user.sub,
            actor_role=user.roles[0] if user.roles else "issuer",
        )
    except CertificateNotFoundError:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND"})
    except BadgeImageNotBakeableError as exc:
        raise HTTPException(
            status_code=422, detail={"code": "NOT_BAKEABLE", "message": str(exc)}
        )
    return Response(
        content=badge.content,
        media_type=badge.media_type,
        headers={"Content-Disposition": f'attachment; filename="{badge.filename}"'},
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
        custom_template_id=(
            str(badge.custom_template_id)
            if getattr(badge, "custom_template_id", None)
            else None
        ),
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
