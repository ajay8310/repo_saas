"""
Webhook management endpoints.

Requirements: 8.7-8.9
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.dependencies.auth import TokenPayload, get_current_user
from app.rbac.permissions import require_permission
from app.services.webhook_service import WebhookService, get_webhook_service

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


class RegisterWebhookRequest(BaseModel):
    url: str = Field(..., min_length=1, max_length=2048)
    secret: str = Field(..., min_length=16, max_length=255)
    event_types: list[str] = Field(default_factory=list)


class WebhookResponse(BaseModel):
    id: str
    url: str
    event_types: list
    status: str
    created_at: str


@router.post(
    "",
    response_model=WebhookResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("webhook:create"))],
)
async def register_webhook(
    body: RegisterWebhookRequest,
    user: TokenPayload = Depends(get_current_user),
    service: WebhookService = Depends(get_webhook_service),
) -> WebhookResponse:
    """Register a new webhook."""
    wh = await service.register_webhook(
        tenant_id=user.tenant_id,
        url=body.url,
        secret=body.secret,
        event_types=body.event_types,
    )
    return WebhookResponse(
        id=str(wh.id), url=wh.url, event_types=wh.event_types,
        status=wh.status, created_at=wh.created_at.isoformat(),
    )


@router.get("", response_model=list[WebhookResponse])
async def list_webhooks(
    user: TokenPayload = Depends(get_current_user),
    service: WebhookService = Depends(get_webhook_service),
) -> list[WebhookResponse]:
    """List all webhooks for the tenant."""
    webhooks = await service.list_webhooks(user.tenant_id)
    return [
        WebhookResponse(
            id=str(wh.id), url=wh.url, event_types=wh.event_types,
            status=wh.status, created_at=wh.created_at.isoformat(),
        )
        for wh in webhooks
    ]


@router.delete(
    "/{webhook_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("webhook:delete"))],
)
async def delete_webhook(
    webhook_id: UUID,
    user: TokenPayload = Depends(get_current_user),
    service: WebhookService = Depends(get_webhook_service),
) -> None:
    """Disable a webhook."""
    deleted = await service.delete_webhook(user.tenant_id, webhook_id)
    if not deleted:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND"})
