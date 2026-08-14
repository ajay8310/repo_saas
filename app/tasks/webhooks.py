"""
Celery tasks for webhook event delivery with exponential backoff.

First retry: 5-10s. Each subsequent retry doubles. Max 3 retries.

Requirements: 8.8, 8.9
"""

from __future__ import annotations

import asyncio
import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(
    name="app.tasks.webhooks.deliver_webhook_event",
    bind=True,
    max_retries=3,
    default_retry_delay=5,
)
def deliver_webhook_event(self, event_id: str) -> bool:
    """Deliver a webhook event with retry and exponential backoff.

    Retries: 5s, 10s, 20s (doubles each time).
    """
    try:
        return asyncio.run(_deliver_async(event_id))
    except Exception as exc:
        # Exponential backoff: 5 * 2^retry
        countdown = 5 * (2 ** self.request.retries)
        logger.warning(
            "Webhook delivery failed (attempt %d), retrying in %ds: %s",
            self.request.retries + 1, countdown, exc,
        )
        raise self.retry(exc=exc, countdown=countdown)


async def _deliver_async(event_id: str) -> bool:
    """Async webhook delivery."""
    from uuid import UUID

    from app.db.session import AsyncSessionLocal
    from app.services.webhook_service import WebhookService

    async with AsyncSessionLocal() as db:
        service = WebhookService(db=db)
        return await service.deliver_event(UUID(event_id))
