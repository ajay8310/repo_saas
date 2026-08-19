"""
Privacy endpoints — consent management and data-principal rights (DPDP Act).

    GET    /api/v1/privacy/notice                     public consent notice
    GET    /api/v1/privacy/consents                   my consent history
    POST   /api/v1/privacy/consents                   grant consent
    DELETE /api/v1/privacy/consents/{purpose}         withdraw consent
    GET    /api/v1/privacy/erasure-preview            what erasure would remove
    POST   /api/v1/privacy/requests                   access/correction/erasure
    GET    /api/v1/privacy/requests                   my requests

These are scoped to the calling data principal. A beneficiary can only act on
their own record: ``data_principal_id`` is taken from the token, never from the
request body, so one principal cannot withdraw another's consent or request
erasure of their data.

Requirements: 7.5, 10.4
"""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.config import get_settings
from app.dependencies.auth import TokenPayload, get_current_user
from app.services.consent_service import (
    KNOWN_PURPOSES,
    ConsentError,
    ConsentService,
    get_consent_service,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/privacy", tags=["privacy"])


# --- Request / Response models ---


class GrantConsentRequest(BaseModel):
    purpose: str = Field(..., description="One of the platform's known purposes.")
    scope: list[str] = Field(
        default_factory=list,
        max_length=100,
        description="Credential fields the principal agrees to disclose.",
    )
    document_id: str | None = Field(
        default=None, description="Limit consent to a single credential."
    )


class ConsentResponse(BaseModel):
    consent_id: str
    purpose: str
    legal_basis: str
    state: str
    scope: list[str]
    notice_version: str
    document_id: str | None
    granted_at: str | None
    withdrawn_at: str | None
    expires_at: str | None


class RightsRequestBody(BaseModel):
    request_type: Literal["access", "correction", "erasure"]
    details: dict | None = Field(
        default=None,
        description="For a correction, the fields and values being disputed.",
    )


class RightsRequestResponse(BaseModel):
    request_id: str
    request_type: str
    state: str
    received_at: str
    executable_after: str | None
    completed_at: str | None
    rejection_reason: str | None


class NoticeResponse(BaseModel):
    notice_version: str
    purposes: list[dict]
    grievance_officer_email: str | None
    retention_note: str
    rights: list[str]


_PURPOSE_DESCRIPTIONS: dict[str, str] = {
    "credential_verification": (
        "Disclosing selected credential fields to a verifier you share a "
        "verification link with."
    ),
    "notification_delivery": (
        "Sending you email or SMS about issuance, revocation, and verification "
        "of your credentials."
    ),
    "digilocker_publication": (
        "Publishing your issued credential to your DigiLocker account."
    ),
    "aggregate_analytics": (
        "Counting issuance and verification volumes. Aggregate only; no "
        "individual record is identifiable in the output."
    ),
}


def _consent_response(record) -> ConsentResponse:  # noqa: ANN001
    return ConsentResponse(
        consent_id=str(record.id),
        purpose=record.purpose,
        legal_basis=record.legal_basis,
        state=record.state,
        scope=list(record.scope or []),
        notice_version=record.notice_version,
        document_id=str(record.document_id) if record.document_id else None,
        granted_at=record.granted_at.isoformat() if record.granted_at else None,
        withdrawn_at=record.withdrawn_at.isoformat() if record.withdrawn_at else None,
        expires_at=record.expires_at.isoformat() if record.expires_at else None,
    )


# --- Endpoints ---


@router.get("/notice", response_model=NoticeResponse, summary="Consent notice")
async def get_notice() -> NoticeResponse:
    """Return the current consent notice.

    Public: a data principal must be able to read what they are agreeing to
    before authenticating, and the DPDP Act requires the notice to be available
    in clear terms.
    """
    settings = get_settings()
    return NoticeResponse(
        notice_version=settings.consent_notice_version,
        purposes=[
            {"purpose": p, "description": _PURPOSE_DESCRIPTIONS.get(p, "")}
            for p in sorted(KNOWN_PURPOSES)
        ],
        grievance_officer_email=settings.grievance_officer_email or None,
        retention_note=(
            "Issued credentials are retained for the issuing authority's "
            "statutory retention period and then purged automatically. Audit "
            "records of processing are immutable and retained separately."
        ),
        rights=[
            "Access the personal data held about you",
            "Request correction of inaccurate data",
            "Withdraw consent for any purpose you previously agreed to",
            "Request erasure, subject to statutory retention",
            "Escalate to the grievance officer",
        ],
    )


@router.get(
    "/consents",
    response_model=list[ConsentResponse],
    summary="My consent history",
)
async def list_consents(
    user: TokenPayload = Depends(get_current_user),
    service: ConsentService = Depends(get_consent_service),
) -> list[ConsentResponse]:
    """Return the caller's full consent history, newest first."""
    records = await service.history(
        tenant_id=user.tenant_id, data_principal_id=user.sub
    )
    return [_consent_response(r) for r in records]


@router.post(
    "/consents",
    response_model=ConsentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Grant consent",
)
async def grant_consent(
    body: GrantConsentRequest,
    user: TokenPayload = Depends(get_current_user),
    service: ConsentService = Depends(get_consent_service),
) -> ConsentResponse:
    """Record a consent grant for the calling principal."""
    from uuid import UUID

    document_id = None
    if body.document_id:
        try:
            document_id = UUID(body.document_id)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "VALIDATION_ERROR",
                    "message": "document_id must be a UUID.",
                },
            )

    try:
        record = await service.grant(
            tenant_id=user.tenant_id,
            # Taken from the token, never the body: a principal may only
            # consent on their own behalf.
            data_principal_id=user.sub,
            purpose=body.purpose,
            scope=body.scope,
            document_id=document_id,
            collected_via="api",
        )
    except ConsentError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "INVALID_PURPOSE", "message": str(exc)},
        )

    return _consent_response(record)


@router.delete(
    "/consents/{purpose}",
    response_model=ConsentResponse,
    summary="Withdraw consent",
)
async def withdraw_consent(
    purpose: str,
    user: TokenPayload = Depends(get_current_user),
    service: ConsentService = Depends(get_consent_service),
) -> ConsentResponse:
    """Withdraw consent for *purpose*.

    Recorded as a new event rather than deleting the grant, so the audit trail
    still shows what was authorised while it was in force.
    """
    record = await service.withdraw(
        tenant_id=user.tenant_id,
        data_principal_id=user.sub,
        purpose=purpose,
    )
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "NO_ACTIVE_CONSENT",
                "message": f"No active consent found for purpose {purpose!r}.",
            },
        )
    return _consent_response(record)


@router.get("/erasure-preview", summary="What erasure would and would not remove")
async def erasure_preview(
    user: TokenPayload = Depends(get_current_user),
    service: ConsentService = Depends(get_consent_service),
) -> dict:
    """Explain the scope and limits of erasure before a request is made.

    Surfacing the statutory-retention and immutable-audit limits up front is
    more honest than accepting a request the platform cannot fully satisfy.
    """
    return await service.describe_erasure_limits(
        tenant_id=user.tenant_id, data_principal_id=user.sub
    )


@router.post(
    "/requests",
    response_model=RightsRequestResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit an access, correction, or erasure request",
)
async def submit_request(
    body: RightsRequestBody,
    user: TokenPayload = Depends(get_current_user),
    service: ConsentService = Depends(get_consent_service),
) -> RightsRequestResponse:
    """Record a data-principal rights request.

    Returns 202: erasure spans object storage and per-tenant keys and is carried
    out by a worker after the grace period, so claiming completion here would be
    untrue.
    """
    try:
        request = await service.submit_request(
            tenant_id=user.tenant_id,
            data_principal_id=user.sub,
            request_type=body.request_type,
            details=body.details,
        )
    except ConsentError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "VALIDATION_ERROR", "message": str(exc)},
        )

    executable_after = (
        service.erasure_deadline(request.received_at).isoformat()
        if body.request_type == "erasure"
        else None
    )

    return RightsRequestResponse(
        request_id=str(request.id),
        request_type=request.request_type,
        state=request.state,
        received_at=request.received_at.isoformat(),
        executable_after=executable_after,
        completed_at=None,
        rejection_reason=None,
    )


@router.get(
    "/requests",
    response_model=list[RightsRequestResponse],
    summary="My rights requests",
)
async def list_requests(
    user: TokenPayload = Depends(get_current_user),
    service: ConsentService = Depends(get_consent_service),
) -> list[RightsRequestResponse]:
    """List the caller's rights requests and their status."""
    requests = await service.list_requests(
        tenant_id=user.tenant_id, data_principal_id=user.sub
    )
    return [
        RightsRequestResponse(
            request_id=str(r.id),
            request_type=r.request_type,
            state=r.state,
            received_at=r.received_at.isoformat(),
            executable_after=(
                service.erasure_deadline(r.received_at).isoformat()
                if r.request_type == "erasure"
                else None
            ),
            completed_at=r.completed_at.isoformat() if r.completed_at else None,
            rejection_reason=r.rejection_reason,
        )
        for r in requests
    ]
