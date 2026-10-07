"""Recipient wallet endpoints (U2 — S7, S9, S10, S11).

Beneficiary-facing API over the earner's own badge assertions. The earner
identity is the authenticated subject (``user.sub``), matching how the documents
router scopes beneficiary access. All routes require the beneficiary wallet
permissions; ownership is additionally enforced in the service layer.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel

from app.dependencies.auth import TokenPayload, get_current_user
from app.rbac.permissions import require_permission
from app.services.certificate_service import (
    CertificateNotFoundError,
    CertificateService,
    get_certificate_service,
)
from app.services.wallet_service import (
    WalletConflictError,
    WalletItem,
    WalletService,
    get_wallet_service,
)

router = APIRouter(prefix="/wallet", tags=["wallet"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class WalletItemResponse(BaseModel):
    assertion_id: str
    badge_class_id: str
    badge_name: str
    badge_description: str | None
    image_s3_key: str | None
    status: str
    issued_at: str | None
    expires_at: str | None
    accepted: bool
    hidden: bool
    public: bool
    revoked_at: str | None
    public_url: str


class PublicRequest(BaseModel):
    public: bool


class HideRequest(BaseModel):
    hidden: bool


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=list[WalletItemResponse],
    dependencies=[Depends(require_permission("badge:wallet_read"))],
)
async def list_wallet(
    include_hidden: bool = False,
    limit: int = 50,
    offset: int = 0,
    user: TokenPayload = Depends(get_current_user),
    service: WalletService = Depends(get_wallet_service),
) -> list[WalletItemResponse]:
    """List the beneficiary's own badges, newest first (S7)."""
    items = await service.list_wallet(
        tenant_id=user.tenant_id,
        beneficiary_id=user.sub,
        include_hidden=include_hidden,
        limit=limit,
        offset=offset,
    )
    return [_response(i) for i in items]


@router.post(
    "/{assertion_id}/public",
    response_model=WalletItemResponse,
    dependencies=[Depends(require_permission("badge:wallet_manage"))],
)
async def set_public(
    assertion_id: UUID,
    body: PublicRequest,
    user: TokenPayload = Depends(get_current_user),
    service: WalletService = Depends(get_wallet_service),
) -> WalletItemResponse:
    """Make a badge public or private (S11). Revoked badges cannot be published."""
    try:
        item = await service.set_public(
            tenant_id=user.tenant_id,
            beneficiary_id=user.sub,
            assertion_id=assertion_id,
            public=body.public,
        )
    except WalletConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "CONFLICT", "message": str(exc)},
        )
    if item is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND"})
    return _response(item)


@router.post(
    "/{assertion_id}/hide",
    response_model=WalletItemResponse,
    dependencies=[Depends(require_permission("badge:wallet_manage"))],
)
async def set_hidden(
    assertion_id: UUID,
    body: HideRequest,
    user: TokenPayload = Depends(get_current_user),
    service: WalletService = Depends(get_wallet_service),
) -> WalletItemResponse:
    """Hide or unhide a badge in the wallet (S9)."""
    item = await service.set_hidden(
        tenant_id=user.tenant_id,
        beneficiary_id=user.sub,
        assertion_id=assertion_id,
        hidden=body.hidden,
    )
    if item is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND"})
    return _response(item)


@router.delete(
    "/{assertion_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    dependencies=[Depends(require_permission("badge:wallet_manage"))],
)
async def delete_from_wallet(
    assertion_id: UUID,
    user: TokenPayload = Depends(get_current_user),
    service: WalletService = Depends(get_wallet_service),
) -> Response:
    """Remove a badge from the wallet (S10, soft delist — stays verifiable)."""
    ok = await service.delete_from_wallet(
        tenant_id=user.tenant_id,
        beneficiary_id=user.sub,
        assertion_id=assertion_id,
    )
    if not ok:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND"})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{assertion_id}/certificate",
    response_class=Response,
    dependencies=[Depends(require_permission("badge:wallet_certificate"))],
)
async def download_wallet_certificate(
    assertion_id: UUID,
    user: TokenPayload = Depends(get_current_user),
    cert_service: CertificateService = Depends(get_certificate_service),
) -> Response:
    """Download the earner's own certificate PDF (U4 Q4 earner, ownership-checked).

    ``require_owner`` restricts the render to the authenticated beneficiary, so a
    beneficiary can only download their own certificate.
    """
    try:
        cert = await cert_service.build_certificate(
            tenant_id=user.tenant_id,
            assertion_id=assertion_id,
            actor_id=user.sub,
            actor_role="beneficiary",
            require_owner=user.sub,
        )
    except CertificateNotFoundError:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND"})
    return Response(
        content=cert.content,
        media_type=cert.media_type,
        headers={"Content-Disposition": f'attachment; filename="{cert.filename}"'},
    )


def _response(item: WalletItem) -> WalletItemResponse:
    return WalletItemResponse(**item.__dict__)
