"""
Celery tasks for async notification delivery with retry.

Retry policy: up to 3 retries at 30s, 60s, 120s exponential backoff.

Requirements: 11.1, 11.5, 11.6
"""

from __future__ import annotations

import asyncio
import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(
    name="app.tasks.notifications.send_notification",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
)
def send_notification(
    self,
    tenant_id: str,
    beneficiary_id: str,
    event_type: str,
    payload: dict,
) -> bool:
    """Send a notification to a beneficiary with retry.

    Retries with exponential backoff: 30s, 60s, 120s.
    """
    try:
        return asyncio.run(
            _send_async(tenant_id, beneficiary_id, event_type, payload)
        )
    except Exception as exc:
        # Calculate backoff: 30 * 2^retry_number
        countdown = 30 * (2 ** self.request.retries)
        logger.warning(
            "Notification failed (attempt %d), retrying in %ds: %s",
            self.request.retries + 1, countdown, exc,
        )
        raise self.retry(exc=exc, countdown=countdown)


async def _send_async(
    tenant_id: str, beneficiary_id: str, event_type: str, payload: dict
) -> bool:
    """Async notification delivery."""
    from uuid import UUID

    from app.config import get_settings
    from app.db.session import AsyncSessionLocal
    from app.services.notification_service import NotificationService

    settings = get_settings()
    async with AsyncSessionLocal() as db:
        service = NotificationService(db=db, settings=settings)
        return await service.notify(
            tenant_id=UUID(tenant_id),
            beneficiary_id=beneficiary_id,
            event_type=event_type,
            payload=payload,
        )
