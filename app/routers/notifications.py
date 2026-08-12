"""
Notification preference endpoints for beneficiaries.

Requirements: 11.4
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.dependencies.auth import TokenPayload, get_current_user
from app.services.notification_service import (
    NotificationService,
    get_notification_service,
)

router = APIRouter(prefix="/beneficiaries/me", tags=["notifications"])


class PreferencesResponse(BaseModel):
    notify_on_issuance: bool
    notify_on_revocation: bool
    notify_on_verification: bool
    preferred_channel: str


class UpdatePreferencesRequest(BaseModel):
    notify_on_issuance: bool | None = None
    notify_on_revocation: bool | None = None
    notify_on_verification: bool | None = None
    preferred_channel: str | None = Field(default=None, pattern="^(email|sms)$")


@router.get("/notification-preferences", response_model=PreferencesResponse)
async def get_preferences(
    user: TokenPayload = Depends(get_current_user),
    service: NotificationService = Depends(get_notification_service),
) -> PreferencesResponse:
    """Get current notification preferences."""
    pref = await service.get_preferences(user.tenant_id, user.sub)
    if pref is None:
        return PreferencesResponse(
            notify_on_issuance=True,
            notify_on_revocation=True,
            notify_on_verification=True,
            preferred_channel="email",
        )
    return PreferencesResponse(
        notify_on_issuance=pref.notify_on_issuance,
        notify_on_revocation=pref.notify_on_revocation,
        notify_on_verification=pref.notify_on_verification,
        preferred_channel=pref.preferred_channel,
    )


@router.patch("/notification-preferences", response_model=PreferencesResponse)
async def update_preferences(
    body: UpdatePreferencesRequest,
    user: TokenPayload = Depends(get_current_user),
    service: NotificationService = Depends(get_notification_service),
) -> PreferencesResponse:
    """Update notification preferences."""
    pref = await service.update_preferences(
        tenant_id=user.tenant_id,
        beneficiary_id=user.sub,
        notify_on_issuance=body.notify_on_issuance,
        notify_on_revocation=body.notify_on_revocation,
        notify_on_verification=body.notify_on_verification,
        preferred_channel=body.preferred_channel,
    )
    return PreferencesResponse(
        notify_on_issuance=pref.notify_on_issuance,
        notify_on_revocation=pref.notify_on_revocation,
        notify_on_verification=pref.notify_on_verification,
        preferred_channel=pref.preferred_channel,
    )
