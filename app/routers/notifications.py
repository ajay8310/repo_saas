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
