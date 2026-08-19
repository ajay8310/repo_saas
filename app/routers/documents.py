"""
Document endpoints — upload, list, retrieve, download, revoke, bulk.

Requirements: 3.1-3.11, 4.1-4.9, 6.1-6.7
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.dependencies.auth import TokenPayload, get_current_user
from app.rbac.permissions import require_permission
from app.tasks.dispatch import enqueue_bulk_upload
from app.services.document_service import (
    DocumentAlreadyRevokedError,
    DocumentNotFoundError,
    DocumentService,
    DocumentValidationError,
    ServiceUnavailableError,
    get_document_service,
)

router = APIRouter(prefix="/documents", tags=["documents"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class UploadDocumentRequest(BaseModel):
    schema_id: str = Field(..., min_length=1)
    beneficiary_id: str = Field(..., min_length=1, max_length=512)
    content_base64: str = Field(..., min_length=1, description="Base64-encoded document content")
    cmk_arn: str = Field(..., min_length=1, description="Tenant CMK ARN for encryption")


class UploadResponse(BaseModel):
    credential_id: str
    status: str


class DocumentResponse(BaseModel):
    credential_id: str
    schema_id: str
    schema_version: int
    beneficiary_id: str
    status: str
    issued_at: str | None
    revoked_at: str | None
    revocation_reason: str | None


class RevokeRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=500)


class BulkRevokeRequest(BaseModel):
    credential_ids: list[str] = Field(..., min_length=1, max_length=1000)
    reason: str = Field(..., min_length=1, max_length=500)


class BulkUploadRequest(BaseModel):
    schema_id: str = Field(...)
    cmk_arn: str = Field(...)
    records: list[dict] = Field(..., min_length=1, max_length=10000)


class BulkJobResponse(BaseModel):
    job_id: str
    status: str


class BulkJobStatusResponse(BaseModel):
    job_id: str
    status: str
    total_records: int
    processed_count: int
    success_count: int
    failed_count: int
    summary: dict | None
    created_at: str | None
    completed_at: str | None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=UploadResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("document:upload"))],
)
async def upload_document(
    body: UploadDocumentRequest,
    user: TokenPayload = Depends(get_current_user),
    service: DocumentService = Depends(get_document_service),
) -> UploadResponse:
    """Upload a single document (Req 3.1)."""
    import base64
    try:
        content = base64.b64decode(body.content_base64)
    except Exception:
        raise HTTPException(status_code=422, detail={"code": "INVALID_CONTENT"})

    try:
        result = await service.upload_document(
            tenant_id=user.tenant_id,
            schema_id=UUID(body.schema_id),
            beneficiary_id=body.beneficiary_id,
            content=content,
            cmk_arn=body.cmk_arn,
        )
    except DocumentValidationError as exc:
        raise HTTPException(status_code=422, detail={"code": "VALIDATION_ERROR", "message": str(exc)})
    except ServiceUnavailableError as exc:
        raise HTTPException(status_code=503, detail={"code": "SERVICE_UNAVAILABLE", "message": str(exc)})

    return UploadResponse(credential_id=result.credential_id, status=result.status)


@router.get("", response_model=list[DocumentResponse])
async def list_documents(
    limit: int = 20,
    offset: int = 0,
    user: TokenPayload = Depends(get_current_user),
    service: DocumentService = Depends(get_document_service),
) -> list[DocumentResponse]:
    """List documents for tenant (Req 4.1)."""
    if "beneficiary" in user.roles:
        docs = await service.list_documents_for_beneficiary(
            user.tenant_id, user.sub, limit, offset
        )
    else:
        docs = await service.list_documents(user.tenant_id, limit, offset)
    return [_doc_response(d) for d in docs]


@router.get("/{credential_id}", response_model=DocumentResponse)
async def get_document(
    credential_id: UUID,
    user: TokenPayload = Depends(get_current_user),
    service: DocumentService = Depends(get_document_service),
) -> DocumentResponse:
    """Retrieve document metadata (Req 4.2, 4.3)."""
    if "beneficiary" in user.roles:
        doc = await service.get_document_for_beneficiary(
            user.tenant_id, credential_id, user.sub
        )
    else:
        doc = await service.get_document(user.tenant_id, credential_id)

    if doc is None:
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN"})
    return _doc_response(doc)


@router.get("/{credential_id}/download")
async def download_document(
    credential_id: UUID,
    format: Literal["raw", "pdf", "jsonld"] = Query(
        default="pdf",
        description="Output format: signed PDF with QR (default), JSON-LD, or raw bytes.",
    ),
    user: TokenPayload = Depends(get_current_user),
    service: DocumentService = Depends(get_document_service),
) -> Response:
    """Download a document as a signed PDF, JSON-LD, or raw bytes (Req 4.7).

    PDF and JSON-LD embed the credential ID, a QR code pointing at the public
    verification URL, and an RS256 proof over the credential payload.
    """
    try:
        rendered = await service.download_document(
            tenant_id=user.tenant_id,
            credential_id=credential_id,
            output_format=format,
            actor_id=user.sub,
            actor_role=user.roles[0] if user.roles else "beneficiary",
        )
    except DocumentNotFoundError:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND"})
    except DocumentValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "VALIDATION_ERROR", "message": str(exc)},
        )
    except ServiceUnavailableError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "SERVICE_UNAVAILABLE", "message": str(exc)},
        )

    return Response(
        content=rendered.content,
        media_type=rendered.media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{rendered.filename}"',
            "X-Credential-Id": str(credential_id),
        },
    )


@router.post(
    "/{credential_id}/revoke",
    response_model=DocumentResponse,
    dependencies=[Depends(require_permission("document:revoke"))],
)
async def revoke_document(
    credential_id: UUID,
    body: RevokeRequest,
    user: TokenPayload = Depends(get_current_user),
    service: DocumentService = Depends(get_document_service),
) -> DocumentResponse:
    """Revoke a document (Req 6.1, 6.2)."""
    try:
        doc = await service.revoke_document(user.tenant_id, credential_id, body.reason)
    except DocumentNotFoundError:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND"})
    except DocumentAlreadyRevokedError:
        raise HTTPException(status_code=409, detail={"code": "ALREADY_REVOKED"})
    except DocumentValidationError as exc:
        raise HTTPException(status_code=422, detail={"code": "VALIDATION_ERROR", "message": str(exc)})
    return _doc_response(doc)


@router.post(
    "/bulk-revoke",
    dependencies=[Depends(require_permission("document:bulk_revoke"))],
)
async def bulk_revoke(
    body: BulkRevokeRequest,
    user: TokenPayload = Depends(get_current_user),
    service: DocumentService = Depends(get_document_service),
) -> list[dict]:
    """Bulk revoke documents (Req 6.6, 6.7)."""
    ids = [UUID(cid) for cid in body.credential_ids]
    return await service.bulk_revoke(user.tenant_id, ids, body.reason)


@router.post(
    "/bulk",
    response_model=BulkJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_permission("document:bulk_upload"))],
)
async def bulk_upload(
    body: BulkUploadRequest,
    user: TokenPayload = Depends(get_current_user),
    service: DocumentService = Depends(get_document_service),
) -> BulkJobResponse:
    """Initiate bulk upload (Req 3.8, 3.9). Returns job_id for tracking."""
    from app.models.document import BulkJob
    from app.middleware.tenant_context import set_tenant_context
    import uuid as uuid_mod

    await set_tenant_context(service.db, str(user.tenant_id))

    job = BulkJob(
        tenant_id=user.tenant_id,
        status="pending",
        total_records=len(body.records),
    )
    service.db.add(job)
    await service.db.commit()
    await service.db.refresh(job)

    # Hand the batch to the worker.  This used to be a commented-out line, so
    # the endpoint returned a job_id that never left 'pending'.
    enqueued = enqueue_bulk_upload(
        job_id=str(job.id),
        tenant_id=str(user.tenant_id),
        schema_id=body.schema_id,
        cmk_arn=body.cmk_arn,
        records=body.records,
    )
    if not enqueued:
        # No broker reachable. Say so rather than reporting an accepted job
        # that will never be processed.
        job.status = "failed"
        job.summary = {
            "error": "QUEUE_UNAVAILABLE",
            "message": "Bulk upload could not be queued; no worker broker reachable.",
        }
        await service.db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "QUEUE_UNAVAILABLE",
                "message": (
                    "Bulk upload requires the background worker, which is "
                    "currently unreachable. No records were processed."
                ),
            },
        )

    return BulkJobResponse(job_id=str(job.id), status="pending")


@router.get(
    "/bulk/{job_id}",
    response_model=BulkJobStatusResponse,
    dependencies=[Depends(require_permission("document:bulk_upload"))],
)
async def get_bulk_job(
    job_id: UUID,
    user: TokenPayload = Depends(get_current_user),
    service: DocumentService = Depends(get_document_service),
) -> BulkJobStatusResponse:
    """Report progress for a bulk upload job (Req 3.8, 3.9).

    Without this a caller received a job_id from POST /documents/bulk with no
    way to discover the outcome.
    """
    from app.middleware.tenant_context import set_tenant_context
    from app.models.document import BulkJob

    await set_tenant_context(service.db, str(user.tenant_id))
    result = await service.db.execute(select(BulkJob).where(BulkJob.id == job_id))
    job = result.scalar_one_or_none()

    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "Bulk job not found."},
        )

    return BulkJobStatusResponse(
        job_id=str(job.id),
        status=job.status,
        total_records=job.total_records,
        processed_count=job.processed_count,
        success_count=job.success_count,
        failed_count=job.failed_count,
        summary=job.summary,
        created_at=job.created_at.isoformat() if job.created_at else None,
        completed_at=job.completed_at.isoformat() if job.completed_at else None,
    )


def _doc_response(doc) -> DocumentResponse:
    return DocumentResponse(
        credential_id=str(doc.id),
        schema_id=str(doc.schema_id),
        schema_version=doc.schema_version,
        beneficiary_id=doc.beneficiary_id,
        status=doc.status,
        issued_at=doc.created_at.isoformat() if doc.created_at else None,
        revoked_at=doc.revoked_at.isoformat() if doc.revoked_at else None,
        revocation_reason=doc.revocation_reason,
    )
