"""
Verification endpoints — token generation, consumption, public check.

Requirements: 5.1-5.10, 6.3
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.dependencies.auth import TokenPayload, get_current_user
from app.rbac.permissions import require_permission
from app.services.verification_service import (
    VerificationError,
    VerificationService,
    get_verification_service,
)

router = APIRouter(tags=["verification"])


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class GenerateTokenRequest(BaseModel):
    document_id: str = Field(...)
    consented_fields: list[str] = Field(default_factory=list)
    expiry_hours: int | None = Field(default=None, ge=1, le=168)


class TokenResponse(BaseModel):
    token: str
    expires_at: str


class VerifyResponse(BaseModel):
    valid: bool
    status: str
    issuer_name: str | None = None
    issued_at: str | None = None
    fields: dict | None = None
    revoked_at: str | None = None


# ---------------------------------------------------------------------------
# Authenticated endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/verifications/tokens",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("verification:create"))],
)
async def generate_token(
    body: GenerateTokenRequest,
    user: TokenPayload = Depends(get_current_user),
    service: VerificationService = Depends(get_verification_service),
) -> TokenResponse:
    """Generate a verification token (Req 5.1)."""
    try:
        result = await service.generate_token(
            tenant_id=user.tenant_id,
            document_id=UUID(body.document_id),
            beneficiary_id=user.sub,
            consented_fields=body.consented_fields,
            expiry_hours=body.expiry_hours,
        )
    except VerificationError as exc:
        raise HTTPException(status_code=400, detail={"code": "VERIFICATION_ERROR", "message": str(exc)})

    return TokenResponse(token=result.token, expires_at=result.expires_at.isoformat())


# ---------------------------------------------------------------------------
# Public endpoints (no auth required)
# ---------------------------------------------------------------------------


@router.get("/verify/{credential_id}")
async def verify_public(
    credential_id: UUID,
    service: VerificationService = Depends(get_verification_service),
) -> dict:
    """Public verification — returns only validity status (Req 5.6, 5.10)."""
    return await service.verify_credential_public(credential_id)


@router.get("/verifications/{token}")
async def consume_token(
    token: str,
    service: VerificationService = Depends(get_verification_service),
) -> VerifyResponse:
    """Consume a verification token (Req 5.2-5.5)."""
    result = await service.consume_token(token)
    return VerifyResponse(
        valid=result.valid,
        status=result.status,
        issuer_name=result.issuer_name,
        issued_at=result.issued_at,
        fields=result.fields,
        revoked_at=result.revoked_at,
    )
