"""
Webhook service — HMAC-signed event delivery with retry.

Queries webhooks by tenant_id (single table). No joins.
Webhook events stored in webhook_events (single table insert).

Requirements: 8.7, 8.8, 8.9
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.session import get_db
from app.middleware.tenant_context import set_tenant_context
from app.models.webhook import Webhook, WebhookEvent
from app.services.vault import VaultError, get_vault_service

logger = logging.getLogger(__name__)


class WebhookService:
    """Manages webhook registration and event delivery. No joins."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.settings = get_settings()

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def register_webhook(
        self,
        tenant_id: UUID,
        url: str,
        secret: str,
        event_types: list[str],
    ) -> Webhook:
        """Register a new webhook for a tenant."""
        await set_tenant_context(self.db, str(tenant_id))
        secret_hash = hashlib.sha256(secret.encode()).hexdigest()

        # Seal the secret so deliver_event can sign with the value the receiver
        # actually holds.  The hash stays for audit but cannot be used to sign.
        vault = get_vault_service()
        secret_sealed = vault.seal(secret, tenant_id=str(tenant_id))

        webhook = Webhook(
            tenant_id=tenant_id,
            url=url,
            secret_hash=secret_hash,
            secret_sealed=secret_sealed,
            event_types=event_types,
            status="active",
        )
        self.db.add(webhook)
        await self.db.commit()
        await self.db.refresh(webhook)
        return webhook

    async def list_webhooks(self, tenant_id: UUID) -> list[Webhook]:
        """List all webhooks for a tenant. No joins."""
        await set_tenant_context(self.db, str(tenant_id))
        result = await self.db.execute(
            select(Webhook).order_by(Webhook.created_at.desc())
        )
        return list(result.scalars().all())

    async def delete_webhook(self, tenant_id: UUID, webhook_id: UUID) -> bool:
        """Delete (disable) a webhook. No joins."""
        await set_tenant_context(self.db, str(tenant_id))
        result = await self.db.execute(
            select(Webhook).where(Webhook.id == webhook_id)
        )
        webhook = result.scalar_one_or_none()
        if webhook is None:
            return False
        webhook.status = "disabled"
        await self.db.commit()
        return True

    # ------------------------------------------------------------------
    # Event Dispatch
    # ------------------------------------------------------------------

    async def dispatch_event(
        self,
        tenant_id: UUID,
        event_type: str,
        payload: dict[str, Any],
    ) -> list[UUID]:
        """Record an event for every matching active webhook.

        Returns the created event ids so the caller can enqueue delivery. This
        previously returned a bare count, which left callers no way to hand the
        events to the worker — and nothing else delivered them, so every event
        stayed 'pending' indefinitely.

        The ``webhook_secret`` parameter is gone: it was never read, and the
        signing secret is now recovered per-webhook from the vault at delivery.
        """
        await set_tenant_context(self.db, str(tenant_id))

        result = await self.db.execute(
            select(Webhook).where(Webhook.status == "active")
        )
        webhooks = result.scalars().all()

        events: list[WebhookEvent] = []
        for wh in webhooks:
            # Check if webhook subscribes to this event type
            if wh.event_types and event_type not in wh.event_types:
                continue

            event = WebhookEvent(
                tenant_id=tenant_id,
                webhook_id=wh.id,
                event_type=event_type,
                payload=payload,
                status="pending",
            )
            self.db.add(event)
            events.append(event)

        await self.db.commit()

        for event in events:
            await self.db.refresh(event)
        return [event.id for event in events]

    async def deliver_event(self, event_id: UUID) -> bool:
        """Attempt to deliver a single webhook event.

        Computes HMAC-SHA256 signature and sends POST.
        On failure, schedules retry with exponential backoff.
        """
        result = await self.db.execute(
            select(WebhookEvent).where(WebhookEvent.id == event_id)
        )
        event = result.scalar_one_or_none()
        if event is None:
            return False

        # Fetch webhook URL (single table query by ID)
        wh_result = await self.db.execute(
            select(Webhook).where(Webhook.id == event.webhook_id)
        )
        webhook = wh_result.scalar_one_or_none()
        if webhook is None:
            event.status = "undelivered"
            await self.db.commit()
            return False

        # Recover the signing secret.  Signing with secret_hash (as this used
        # to) produced a signature no receiver could reproduce.
        try:
            secret = get_vault_service().open_text(
                webhook.secret_sealed, tenant_id=str(event.tenant_id)
            )
        except VaultError as exc:
            logger.error(
                "Cannot sign webhook event %s: vault unavailable (%s)", event_id, exc
            )
            secret = None

        if not secret:
            # Refuse to send an unverifiable signature.  A receiver validating
            # signatures would reject it anyway, and one that ignores them would
            # be accepting unauthenticated data.
            logger.error(
                "Webhook %s has no recoverable signing secret; marking event %s "
                "undelivered. Re-register the webhook to restore delivery.",
                webhook.id,
                event_id,
            )
            event.status = "undelivered"
            await self.db.commit()
            return False

        # Serialize payload and compute HMAC signature
        payload_bytes = json.dumps(event.payload, default=str).encode()
        signature = hmac.new(
            secret.encode(),
            payload_bytes,
            hashlib.sha256,
        ).hexdigest()

        # Attempt delivery
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    webhook.url,
                    content=payload_bytes,
                    headers={
                        "Content-Type": "application/json",
                        "X-Webhook-Signature": f"sha256={signature}",
                    },
                )
            if 200 <= response.status_code < 300:
                event.status = "delivered"
                event.attempt_count += 1
                await self.db.commit()
                return True
        except Exception as exc:
            logger.warning("Webhook delivery failed for event %s: %s", event_id, exc)

        # Delivery failed — schedule retry
        event.attempt_count += 1
        max_retries = self.settings.webhook_max_retries

        if event.attempt_count >= max_retries:
            event.status = "undelivered"
        else:
            event.status = "retrying"
            # Exponential backoff: base_delay * 2^attempt
            base_delay = self.settings.webhook_first_retry_delay_seconds
            delay = base_delay * (2 ** (event.attempt_count - 1))
            event.next_retry_at = datetime.now(UTC) + timedelta(seconds=delay)

        await self.db.commit()
        return False


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------


async def get_webhook_service(db: AsyncSession = Depends(get_db)) -> WebhookService:
    return WebhookService(db=db)
