"""
Authentication endpoints.

- POST /api/v1/auth/token — OAuth 2.0 client credentials flow
- POST /api/v1/auth/otp/request — request OTP for beneficiary login
- POST /api/v1/auth/otp/verify — verify OTP and receive JWT
- POST /api/v1/auth/mfa/challenge — initiate MFA for admin accounts
- POST /api/v1/auth/mfa/verify — complete MFA verification
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.session import get_db
from app.services.auth_service import AuthService, get_auth_service

router = APIRouter(prefix="/auth", tags=["authentication"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class TokenRequest(BaseModel):
    grant_type: str = Field(..., pattern="^client_credentials$")
    client_id: str = Field(..., min_length=1, max_length=128)
    client_secret: str = Field(..., min_length=1, max_length=255)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int


class OTPRequestBody(BaseModel):
    email: str = Field(..., max_length=255)
    tenant_namespace: str = Field(..., max_length=63)


class OTPVerifyBody(BaseModel):
    email: str = Field(..., max_length=255)
    code: str = Field(..., min_length=4, max_length=8)
    tenant_namespace: str = Field(..., max_length=63)


class MFAChallengeRequest(BaseModel):
    user_id: str = Field(..., min_length=1)


class MFAVerifyRequest(BaseModel):
    user_id: str = Field(..., min_length=1)
    totp_code: str = Field(..., min_length=6, max_length=6)


class DevTokenRequest(BaseModel):
    """Request a real RS256 token for a demo role (development only)."""

    role: Literal[
        "super_admin", "tenant_admin", "issuer", "beneficiary", "verifier"
    ] = "issuer"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/token", response_model=TokenResponse)
async def issue_token(
    body: TokenRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> TokenResponse:
    """Issue a JWT via OAuth 2.0 client credentials flow (Req 8.2, 8.3)."""
    result = await auth_service.authenticate_client(body.client_id, body.client_secret)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "INVALID_CREDENTIALS", "message": "Invalid client_id or client_secret."},
        )
    return TokenResponse(
        access_token=result.access_token,
        expires_in=result.expires_in,
    )


@router.post("/otp/request", status_code=status.HTTP_202_ACCEPTED)
async def request_otp(
    body: OTPRequestBody,
    auth_service: AuthService = Depends(get_auth_service),
) -> dict:
    """Send a one-time password to the beneficiary's registered contact (Req 4.5)."""
    await auth_service.send_otp(body.email, body.tenant_namespace)
    return {"message": "If an account exists, an OTP has been sent."}


@router.post("/otp/verify", response_model=TokenResponse)
async def verify_otp(
    body: OTPVerifyBody,
    auth_service: AuthService = Depends(get_auth_service),
) -> TokenResponse:
    """Verify OTP and issue a JWT for the beneficiary (Req 4.6)."""
    result = await auth_service.verify_otp(body.email, body.code, body.tenant_namespace)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "INVALID_OTP", "message": "OTP is invalid, expired, or already used."},
        )
    return TokenResponse(
        access_token=result.access_token,
        expires_in=result.expires_in,
    )


@router.post("/mfa/challenge", status_code=status.HTTP_202_ACCEPTED)
async def mfa_challenge(
    body: MFAChallengeRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> dict:
    """Initiate MFA challenge for admin account (Req 13.3)."""
    await auth_service.initiate_mfa(body.user_id)
    return {"message": "MFA challenge initiated. Submit TOTP within 5 minutes."}


@router.post("/mfa/verify", response_model=TokenResponse)
async def mfa_verify(
    body: MFAVerifyRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> TokenResponse:
    """Verify TOTP code and complete admin authentication (Req 13.3)."""
    result = await auth_service.verify_mfa(body.user_id, body.totp_code)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "MFA_FAILED", "message": "TOTP code is invalid or expired."},
        )
    return TokenResponse(
        access_token=result.access_token,
        expires_in=result.expires_in,
    )


# Subjects for each demo role. The beneficiary matches the earner used by the
# demo issuance flow so a beneficiary login sees the badges issued to them.
_DEMO_SUBJECTS: dict[str, str] = {
    "super_admin": "platform.admin@reposaas.io",
    "tenant_admin": "admin@demo-edu.example.gov",
    "issuer": "registrar@demo-edu.example.gov",
    "beneficiary": "jane.learner@example.com",
    "verifier": "hr@employer.com",
}


class DevTokenResponse(TokenResponse):
    tenant_id: str
    sub: str
    roles: list[str]


@router.post("/dev-token", response_model=DevTokenResponse)
async def issue_dev_token(
    body: DevTokenRequest,
    auth_service: AuthService = Depends(get_auth_service),
    db: AsyncSession = Depends(get_db),
) -> DevTokenResponse:
    """Mint a REAL RS256 token for a demo role (development only).

    Guarded to ``environment == "development"`` so it can never issue tokens in
    staging/production. Ensures a seeded demo tenant exists and signs a genuine
    token with the platform key, so the browser demo exercises live auth and
    real badge/certificate/analytics data instead of a client-side stub.
    """
    settings = get_settings()
    if settings.environment != "development":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "Not available."},
        )

    from app.models.tenant import Tenant

    tenant = (await db.execute(select(Tenant).limit(1))).scalar_one_or_none()
    if tenant is None:
        tenant = Tenant(
            namespace="demo-edu",
            name="Demo University",
            domain="demo-edu.example.gov",
            contact_email="registrar@demo-edu.example.gov",
            status="active",
            issuer_name="Demo University",
            issuer_url="https://demo-edu.example.gov",
            issuer_email="badges@demo-edu.example.gov",
        )
        db.add(tenant)
        await db.commit()
        await db.refresh(tenant)

    # tenant_admin also carries issuer rights so one admin login can drive the
    # whole badge console.
    roles = [body.role]
    if body.role == "tenant_admin":
        roles = ["tenant_admin", "issuer"]

    result = auth_service._issue_jwt(  # noqa: SLF001 - intentional dev reuse
        sub=_DEMO_SUBJECTS[body.role],
        tenant_id=tenant.id,
        roles=roles,
    )
    return DevTokenResponse(
        access_token=result.access_token,
        expires_in=result.expires_in,
        tenant_id=str(tenant.id),
        sub=_DEMO_SUBJECTS[body.role],
        roles=roles,
    )
