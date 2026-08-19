"""
Celery tasks for DigiLocker delivery.

Two entry points:

``attempt_digilocker_push``
    Pushes one issued credential.  Enqueued right after issuance.

``sweep_digilocker_retries``
    Periodic scan that picks up rows left in ``pending`` or ``retrying``.
    Without this, a push that failed its first attempt was never retried:
    ``attempt_push`` had no call site anywhere in the codebase, so rows
    accumulated in ``pending`` indefinitely.

Requirements: 12.1, 12.2, 12.3
"""

from __future__ import annotations

import asyncio
import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(
    name="app.tasks.digilocker.attempt_digilocker_push",
    bind=True,
    max_retries=0,  # Retries are tracked in digilocker_pushes, not by Celery,
    # so a broker restart cannot lose the attempt count.
)
def attempt_digilocker_push(self, push_id: str) -> bool:  # noqa: ARG001
    """Attempt a single DigiLocker push."""
    return asyncio.run(_attempt_async(push_id))


async def _attempt_async(push_id: str) -> bool:
    from uuid import UUID

    from app.db.session import AsyncSessionLocal
    from app.services.digilocker_connector import DigiLockerConnector
    from app.config import get_settings

    async with AsyncSessionLocal() as db:
        connector = DigiLockerConnector(db=db, settings=get_settings())
        return await connector.attempt_push(UUID(push_id))


@shared_task(name="app.tasks.digilocker.sweep_digilocker_retries")
def sweep_digilocker_retries() -> dict:
    """Retry pushes that are pending or awaiting another attempt."""
    return asyncio.run(_sweep_async())


async def _sweep_async() -> dict:
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import select

    from app.config import get_settings
    from app.db.session import AsyncSessionLocal
    from app.models.digilocker import DigiLockerPush
    from app.services.digilocker_connector import DigiLockerConnector

    settings = get_settings()
    # Respect the configured minimum gap between attempts so a permanently
    # broken endpoint is not hammered once per sweep.
    cutoff = datetime.now(timezone.utc) - timedelta(
        seconds=settings.digilocker_retry_interval_seconds
    )

    attempted = 0
    succeeded = 0

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(DigiLockerPush.id, DigiLockerPush.tenant_id)
            .where(
                DigiLockerPush.status.in_(("pending", "retrying")),
                DigiLockerPush.attempt_count < settings.digilocker_max_retries,
                (DigiLockerPush.last_attempt_at.is_(None))
                | (DigiLockerPush.last_attempt_at < cutoff),
            )
            .limit(500)
        )
        rows = result.all()

    for push_id, tenant_id in rows:
        async with AsyncSessionLocal() as db:
            connector = DigiLockerConnector(db=db, settings=settings)
            try:
                if await connector.attempt_push(push_id, tenant_id=tenant_id):
                    succeeded += 1
            except Exception:
                logger.exception("DigiLocker sweep failed for push %s", push_id)
            attempted += 1

    if attempted:
        logger.info(
            "DigiLocker sweep: %d attempted, %d succeeded", attempted, succeeded
        )
    return {"attempted": attempted, "succeeded": succeeded}
