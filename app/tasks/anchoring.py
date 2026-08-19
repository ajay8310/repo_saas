"""
Celery tasks for ledger anchoring.

Anchoring is deliberately asynchronous: publishing to a ledger can take seconds
to minutes and may fail transiently, and none of that should delay or fail a
credential issuance. The commitment is recorded synchronously at issuance, so a
ledger outage delays the proof without ever losing it.

Requirements: 10.2, 10.3
"""

from __future__ import annotations

import asyncio
import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="app.tasks.anchoring.anchor_pending_batch")
def anchor_pending_batch() -> dict:
    """Anchor outstanding commitments for every tenant, then retry failures."""
    return asyncio.run(_anchor_all_async())


async def _anchor_all_async() -> dict:
    from sqlalchemy import select

    from app.config import get_settings
    from app.db.session import AsyncSessionLocal
    from app.models.tenant import Tenant
    from app.services.anchoring.service import AnchoringService

    settings = get_settings()
    batches = 0
    leaves = 0
    republished = 0

    async with AsyncSessionLocal() as db:
        tenant_ids = (
            await db.execute(select(Tenant.id).where(Tenant.status == "active"))
        ).scalars().all()

    for tenant_id in tenant_ids:
        # A fresh session per tenant keeps one tenant's failure from poisoning
        # the transaction for the rest.
        async with AsyncSessionLocal() as db:
            service = AnchoringService(db=db, settings=settings)
            try:
                batch = await service.anchor_pending(tenant_id)
                if batch is not None:
                    batches += 1
                    leaves += batch.leaf_count
            except Exception:
                logger.exception("Anchoring failed for tenant %s", tenant_id)

    async with AsyncSessionLocal() as db:
        service = AnchoringService(db=db, settings=settings)
        try:
            republished = await service.retry_pending_batches()
        except Exception:
            logger.exception("Retrying pending anchor batches failed")

    if batches or republished:
        logger.info(
            "Anchoring sweep: %d new batches (%d leaves), %d republished",
            batches, leaves, republished,
        )
    return {"batches": batches, "leaves": leaves, "republished": republished}
