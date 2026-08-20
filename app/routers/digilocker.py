"""
DigiLocker publication endpoints.

    POST /api/v1/documents/{credential_id}/digilocker   publish a credential
    GET  /api/v1/documents/{credential_id}/digilocker   publication status
    GET  /api/v1/digilocker/pushes                      tenant publication list
    POST /api/v1/digilocker/pushes/{push_id}/retry      retry a failed push
    GET  /api/v1/digilocker/status                      connector configuration

Before this router existed there was no way for an issuing officer to publish a
credential to DigiLocker at all — the connector was reachable only from the
automatic post-issuance hook, and a failed push had no manual recovery path.

Publication is gated on ``document:upload`` rather than a read permission:
putting a document into a citizen's locker is an issuing act, not a lookup.

Requirements: 12.1, 12.2, 12.4, 12.6
"""

from __future__ import annotations

import logging
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.config import get_settings
from app.dependencies.auth import TokenPayload, get_current_user
from app.rbac.permissions import require_permission
from app.services.audit_service import AuditService, get_audit_service
from app.services.digilocker_connector import (
    DigiLockerConnector,
    get_digilocker_connector,
)
from app.services.document_service import DocumentService, get_document_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["digilocker"])


# --- Request / Response models ---


class PublishRequest(BaseModel):
    doctype: str | None = Field(
        default=None,
        max_length=64,
        description=(
            "DigiLocker document type. Falls back to the configured default "
            "when omitted."
        ),
    )


class PushResponse(BaseModel):
    push_id: str
    credential_id: str
    status: Literal["pending", "success", "failed", "permanently_failed", "retrying"]
    doctype: str | None
    digilocker_uri: str | None
    delivery_mode: str | None
    attempt_count: int
    max_attempts: int
    failure_reason: str | None
    last_attempt_at: str | None
    published_at: str | None
    created_at: str | None
    retryable: bool


class ConnectorStatusResponse(BaseModel):
    mode: Literal["sandbox", "live"]
    configured: bool
    issuer_id: str | None
    default_doctype: str
    max_attempts: int
    note: str


def _push_response(push, max_attempts: int) -> PushResponse:  # noqa: ANN001
    return PushResponse(
        push_id=str(push.id),
        credential_id=str(push.document_id),
        status=push.status,
        doctype=push.doctype,
        digilocker_uri=push.digilocker_uri,
        delivery_mode=push.delivery_mode,
        attempt_count=push.attempt_count,
        max_attempts=max_attempts,
        failure_reason=push.failure_reason,
        last_attempt_at=(
            push.last_attempt_at.isoformat() if push.last_attempt_at else None
        ),
        published_at=push.published_at.isoformat() if push.published_at else None,
        created_at=push.created_at.isoformat() if push.created_at else None,
        # A permanently failed push needs a fresh record, which is what the
        # retry endpoint creates; a successful one must not be re-sent.
        retryable=push.status in ("failed", "permanently_failed", "retrying", "pending"),
    )


# --- Endpoints ---


@router.get(
    "/digilocker/status",
    response_model=ConnectorStatusResponse,
    summary="DigiLocker connector configuration",
)
async def connector_status(
    _user: TokenPayload = Depends(get_current_user),
) -> ConnectorStatusResponse:
    """Report whether publication is live or simulated.

    Surfaced to the UI so an officer is never left guessing whether a
    'published' credential actually reached a citizen's locker.
    """
    settings = get_settings()
    live = settings.digilocker_mode == "live"
    return ConnectorStatusResponse(
        mode=settings.digilocker_mode,
        configured=live,
        issuer_id=settings.digilocker_issuer_id or None,
        default_doctype=settings.digilocker_default_doctype,
        max_attempts=settings.digilocker_max_retries,
        note=(
            "Publishing to the live DigiLocker issuer API."
            if live
            else (
                "Sandbox mode: publications are simulated locally and recorded "
                "with a synthetic URI. Nothing reaches a citizen's DigiLocker "
                "account until digilocker_mode is set to 'live'."
            )
        ),
    )


@router.post(
    "/documents/{credential_id}/digilocker",
    response_model=PushResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_permission("document:upload"))],
    summary="Publish a credential to DigiLocker",
)
async def publish_to_digilocker(
    credential_id: UUID,
    # Defaulted rather than Optional-with-None so the OpenAPI document describes
    # a real object; `PublishRequest | None = None` rendered as an untyped body
    # and gave the generated client nothing to work with.
    body: PublishRequest = PublishRequest(),
    user: TokenPayload = Depends(get_current_user),
    connector: DigiLockerConnector = Depends(get_digilocker_connector),
    documents: DocumentService = Depends(get_document_service),
    audit: AuditService = Depends(get_audit_service),
) -> PushResponse:
    """Publish an issued credential to the beneficiary's DigiLocker account.

    Idempotent: a credential already published returns its existing locker
    reference rather than being sent twice.
    """
    settings = get_settings()

    document = await documents.get_document(user.tenant_id, credential_id)
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "Credential not found."},
        )

    # Publishing a revoked credential would put an invalid document in a
    # citizen's locker, where they would reasonably treat it as current.
    if document.status == "revoked":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "DOCUMENT_REVOKED",
                "message": (
                    "This credential is revoked and cannot be published to "
                    "DigiLocker."
                ),
            },
        )

    result = await connector.publish(
        tenant_id=user.tenant_id,
        document_id=credential_id,
        doctype=body.doctype,
    )

    await audit.record(
        tenant_id=user.tenant_id,
        actor_id=user.sub,
        actor_role=user.roles[0] if user.roles else "issuer",
        operation="digilocker:publish",
        resource_type="document",
        resource_id=str(credential_id),
        outcome="success" if result.status == "success" else "failure",
        metadata={
            "push_id": str(result.push_id),
            "status": result.status,
            "delivery_mode": "sandbox" if result.sandbox else "live",
            "attempt_count": result.attempt_count,
        },
    )
    await connector.db.commit()

    push = await connector.get_push_for_document(user.tenant_id, credential_id)
    if push is None:  # pragma: no cover - the publish call just created it
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "PUSH_MISSING", "message": "Push record disappeared."},
        )
    return _push_response(push, settings.digilocker_max_retries)


@router.get(
    "/documents/{credential_id}/digilocker",
    response_model=PushResponse,
    summary="DigiLocker publication status for a credential",
)
async def get_publication_status(
    credential_id: UUID,
    user: TokenPayload = Depends(get_current_user),
    connector: DigiLockerConnector = Depends(get_digilocker_connector),
) -> PushResponse:
    """Return the latest publication attempt for a credential."""
    push = await connector.get_push_for_document(user.tenant_id, credential_id)
    if push is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "NOT_PUBLISHED",
                "message": (
                    "This credential has never been published to DigiLocker."
                ),
            },
        )
    return _push_response(push, get_settings().digilocker_max_retries)


@router.get(
    "/digilocker/pushes",
    response_model=list[PushResponse],
    summary="List DigiLocker publications for the tenant",
)
async def list_publications(
    status_filter: Literal[
        "pending", "success", "failed", "permanently_failed", "retrying"
    ]
    | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user: TokenPayload = Depends(get_current_user),
    connector: DigiLockerConnector = Depends(get_digilocker_connector),
) -> list[PushResponse]:
    """List publication records, newest first, optionally filtered by status."""
    pushes = await connector.list_pushes(
        tenant_id=user.tenant_id, status=status_filter, limit=limit, offset=offset
    )
    max_attempts = get_settings().digilocker_max_retries
    return [_push_response(p, max_attempts) for p in pushes]


@router.post(
    "/digilocker/pushes/{push_id}/retry",
    response_model=PushResponse,
    dependencies=[Depends(require_permission("document:upload"))],
    summary="Retry a failed DigiLocker publication",
)
async def retry_publication(
    push_id: UUID,
    user: TokenPayload = Depends(get_current_user),
    connector: DigiLockerConnector = Depends(get_digilocker_connector),
    audit: AuditService = Depends(get_audit_service),
) -> PushResponse:
    """Retry a publication that failed.

    A push that already exhausted its attempts is retried by resetting it to
    ``pending`` first — otherwise a permanently failed record could never be
    recovered without direct database access, which is the situation an operator
    hits precisely when DigiLocker was down for longer than the retry window.
    """
    pushes = await connector.list_pushes(tenant_id=user.tenant_id, limit=500)
    push = next((p for p in pushes if p.id == push_id), None)

    if push is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "Publication record not found."},
        )

    if push.status == "success":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ALREADY_PUBLISHED",
                "message": (
                    "This credential is already in the citizen's DigiLocker "
                    "account. Re-sending would create a duplicate."
                ),
            },
        )

    if push.status == "permanently_failed":
        push.status = "pending"
        push.attempt_count = 0
        push.failure_reason = None
        await connector.db.commit()

    await connector.attempt_push(push.id, tenant_id=user.tenant_id)
    await connector.db.refresh(push)

    await audit.record(
        tenant_id=user.tenant_id,
        actor_id=user.sub,
        actor_role=user.roles[0] if user.roles else "issuer",
        operation="digilocker:retry",
        resource_type="document",
        resource_id=str(push.document_id),
        outcome="success" if push.status == "success" else "failure",
        metadata={"push_id": str(push.id), "status": push.status},
    )
    await connector.db.commit()

    return _push_response(push, get_settings().digilocker_max_retries)
