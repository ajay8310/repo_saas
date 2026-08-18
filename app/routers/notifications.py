"""
Notification preference endpoints for beneficiaries.

Exposes the contact fields alongside the event toggles. Without them a
beneficiary could enable events that ``notify()`` would silently skip, because
dispatch requires a contact value matching the preferred channel.

Requirements: 11.4
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator

from app.dependencies.auth import TokenPayload, get_current_user
from app.models.notification import NotificationPreference
from app.services.notification_service import (
    NotificationService,
    get_notification_service,
)

router = APIRouter(prefix="/beneficiaries/me", tags=["notifications"])

# Permissive E.164-style check — digits with optional leading +.
_PHONE_RE = re.compile(r"^\+?[0-9]{7,15}$")


class PreferencesResponse(BaseModel):
    notify_on_issuance: bool
    notify_on_revocation: bool
    notify_on_verification: bool
    preferred_channel: str
    contact_email: str | None = None
    contact_phone: str | None = None
    delivery_blocked_reason: str | None = Field(
        default=None,
        description=(
            "Set when the preferred channel has no matching contact value, "
            "meaning notifications would be skipped."
        ),
    )


class UpdatePreferencesRequest(BaseModel):
    """Partial update. Omitted fields are left unchanged.

    For the contact fields an empty string explicitly clears the stored value.
    """

    notify_on_issuance: bool | None = None
    notify_on_revocation: bool | None = None
    notify_on_verification: bool | None = None
    preferred_channel: str | None = Field(default=None, pattern="^(email|sms)$")
    contact_email: str | None = Field(default=None, max_length=255)
    contact_phone: str | None = Field(default=None, max_length=32)

    @field_validator("contact_email")
    @classmethod
    def validate_email(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return v  # None = unchanged, "" = clear
        candidate = v.strip()
        if "@" not in candidate or candidate.startswith("@") or candidate.endswith("@"):
            raise ValueError("contact_email must be a valid email address")
        return candidate

    @field_validator("contact_phone")
    @classmethod
    def validate_phone(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return v
        candidate = v.strip().replace(" ", "").replace("-", "")
        if not _PHONE_RE.match(candidate):
            raise ValueError(
                "contact_phone must be 7-15 digits, optionally prefixed with +"
            )
        return candidate


def _to_response(pref: NotificationPreference) -> PreferencesResponse:
    return PreferencesResponse(
        notify_on_issuance=pref.notify_on_issuance,
        notify_on_revocation=pref.notify_on_revocation,
        notify_on_verification=pref.notify_on_verification,
        preferred_channel=pref.preferred_channel,
        contact_email=pref.contact_email,
        contact_phone=pref.contact_phone,
        delivery_blocked_reason=NotificationService.delivery_blocked_reason(pref),
    )


@router.get("/notification-preferences", response_model=PreferencesResponse)
async def get_preferences(
    user: TokenPayload = Depends(get_current_user),
    service: NotificationService = Depends(get_notification_service),
) -> PreferencesResponse:
    """Get current notification preferences (Req 11.4).

    Returns opt-in defaults when the beneficiary has no stored row yet. Note
    that ``notify()`` skips beneficiaries with no row at all, so these defaults
    describe intent rather than current delivery behaviour.
    """
    pref = await service.get_preferences(user.tenant_id, user.sub)
    if pref is None:
        return PreferencesResponse(
            notify_on_issuance=True,
            notify_on_revocation=True,
            notify_on_verification=True,
            preferred_channel="email",
            delivery_blocked_reason=(
                "No preferences saved yet — save them to start receiving "
                "notifications."
            ),
        )
    return _to_response(pref)


@router.patch("/notification-preferences", response_model=PreferencesResponse)
async def update_preferences(
    body: UpdatePreferencesRequest,
    user: TokenPayload = Depends(get_current_user),
    service: NotificationService = Depends(get_notification_service),
) -> PreferencesResponse:
    """Update notification preferences (Req 11.4)."""
    pref = await service.update_preferences(
        tenant_id=user.tenant_id,
        beneficiary_id=user.sub,
        notify_on_issuance=body.notify_on_issuance,
        notify_on_revocation=body.notify_on_revocation,
        notify_on_verification=body.notify_on_verification,
        preferred_channel=body.preferred_channel,
        contact_email=body.contact_email,
        contact_phone=body.contact_phone,
    )
    return _to_response(pref)
