"""
Notification service — pluggable delivery via AWS SES (email) and SNS (SMS).

Checks beneficiary preferences before sending.
No joins — preference lookup by (tenant_id, beneficiary_id).

Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

import boto3
from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.session import get_db
from app.middleware.tenant_context import set_tenant_context
from app.models.notification import NotificationPreference

logger = logging.getLogger(__name__)


class NotificationService:
    """Event-driven notification delivery with pluggable adapters.

    Checks preferences before sending. No joins.
    """

    def __init__(self, db: AsyncSession, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self._ses = self._create_ses_client()
        self._sns = self._create_sns_client()

    def _create_ses_client(self):
        kwargs: dict = {"region_name": self.settings.aws_region}
        if self.settings.ses_endpoint_url:
            kwargs["endpoint_url"] = self.settings.ses_endpoint_url
        if self.settings.aws_access_key_id:
            kwargs["aws_access_key_id"] = self.settings.aws_access_key_id
            kwargs["aws_secret_access_key"] = self.settings.aws_secret_access_key
        return boto3.client("ses", **kwargs)

    def _create_sns_client(self):
        kwargs: dict = {"region_name": self.settings.aws_region}
        if self.settings.sns_endpoint_url:
            kwargs["endpoint_url"] = self.settings.sns_endpoint_url
        if self.settings.aws_access_key_id:
            kwargs["aws_access_key_id"] = self.settings.aws_access_key_id
            kwargs["aws_secret_access_key"] = self.settings.aws_secret_access_key
        return boto3.client("sns", **kwargs)

    async def notify(
        self,
        tenant_id: UUID,
        beneficiary_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> bool:
        """Send notification if beneficiary has the event type enabled.

        Returns True if sent, False if skipped due to preferences.
        Single-table lookup for preferences — no joins.
        """
        await set_tenant_context(self.db, str(tenant_id))

        # Lookup preferences (no join — single table by tenant_id + beneficiary_id)
        result = await self.db.execute(
            select(NotificationPreference).where(
                NotificationPreference.beneficiary_id == beneficiary_id,
            )
        )
        pref = result.scalar_one_or_none()

        if pref is None:
            logger.info("No notification preferences for %s — skipping", beneficiary_id)
            return False

        # Check if event type is enabled
        if event_type == "issuance" and not pref.notify_on_issuance:
            return False
        if event_type == "revocation" and not pref.notify_on_revocation:
            return False
        if event_type == "verification" and not pref.notify_on_verification:
            return False

        # Dispatch based on preferred channel
        if pref.preferred_channel == "email" and pref.contact_email:
            return await self._send_email(pref.contact_email, event_type, payload)
        elif pref.preferred_channel == "sms" and pref.contact_phone:
            return await self._send_sms(pref.contact_phone, event_type, payload)

        logger.warning("No contact info for %s on channel %s", beneficiary_id, pref.preferred_channel)
        return False

    async def _send_email(self, to_email: str, event_type: str, payload: dict) -> bool:
        """Send email via AWS SES."""
        try:
            self._ses.send_email(
                Source=self.settings.ses_from_email,
                Destination={"ToAddresses": [to_email]},
                Message={
                    "Subject": {"Data": f"Notification: {event_type}"},
                    "Body": {"Text": {"Data": str(payload)}},
                },
            )
            logger.info("Email sent to %s for event %s", to_email, event_type)
            return True
        except Exception as exc:
            logger.error("SES send failed: %s", exc)
            return False

    async def _send_sms(self, phone: str, event_type: str, payload: dict) -> bool:
        """Send SMS via AWS SNS."""
        try:
            self._sns.publish(
                PhoneNumber=phone,
                Message=f"[Repo SaaS] {event_type}: {payload.get('message', '')}",
            )
            logger.info("SMS sent to %s for event %s", phone, event_type)
            return True
        except Exception as exc:
            logger.error("SNS send failed: %s", exc)
            return False

    async def get_preferences(
        self, tenant_id: UUID, beneficiary_id: str
    ) -> NotificationPreference | None:
        """Get notification preferences. No joins."""
        await set_tenant_context(self.db, str(tenant_id))
        result = await self.db.execute(
            select(NotificationPreference).where(
                NotificationPreference.beneficiary_id == beneficiary_id,
            )
        )
        return result.scalar_one_or_none()

    async def update_preferences(
        self,
        tenant_id: UUID,
        beneficiary_id: str,
        notify_on_issuance: bool | None = None,
        notify_on_revocation: bool | None = None,
        notify_on_verification: bool | None = None,
        preferred_channel: str | None = None,
        contact_email: str | None = None,
        contact_phone: str | None = None,
    ) -> NotificationPreference:
        """Update notification preferences. Creates if not exists. No joins.

        For the contact fields, ``None`` means "leave unchanged" while an empty
        string means "clear it". Without that distinction a beneficiary could
        set a contact address but never remove one.

        Contact details matter: ``notify()`` skips delivery entirely when the
        preferred channel has no corresponding contact value on file.
        """
        await set_tenant_context(self.db, str(tenant_id))
        result = await self.db.execute(
            select(NotificationPreference).where(
                NotificationPreference.beneficiary_id == beneficiary_id,
            )
        )
        pref = result.scalar_one_or_none()

        if pref is None:
            pref = NotificationPreference(
                tenant_id=tenant_id,
                beneficiary_id=beneficiary_id,
            )
            self.db.add(pref)

        if notify_on_issuance is not None:
            pref.notify_on_issuance = notify_on_issuance
        if notify_on_revocation is not None:
            pref.notify_on_revocation = notify_on_revocation
        if notify_on_verification is not None:
            pref.notify_on_verification = notify_on_verification
        if preferred_channel is not None:
            pref.preferred_channel = preferred_channel
        if contact_email is not None:
            pref.contact_email = contact_email.strip() or None
        if contact_phone is not None:
            pref.contact_phone = contact_phone.strip() or None

        await self.db.commit()
        await self.db.refresh(pref)
        return pref

    @staticmethod
    def delivery_blocked_reason(pref: NotificationPreference) -> str | None:
        """Explain why delivery would be skipped, or None if it can proceed.

        Mirrors the dispatch conditions in ``notify()`` so callers and the API
        can surface the problem instead of silently dropping notifications.
        """
        if pref.preferred_channel == "email" and not pref.contact_email:
            return "No contact email on file — email notifications will be skipped."
        if pref.preferred_channel == "sms" and not pref.contact_phone:
            return "No contact phone on file — SMS notifications will be skipped."
        return None


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------


async def get_notification_service(
    db: AsyncSession = Depends(get_db),
) -> NotificationService:
    return NotificationService(db=db, settings=get_settings())
