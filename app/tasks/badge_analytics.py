"""Celery task: periodic badge analytics aggregation (U3, Q6=A).

Runs every ~2 minutes (beat schedule) and rolls new ``badge_events`` into
``badge_analytics_daily`` for every tenant that has events. Idempotent: safe to
run on overlapping windows because the aggregator recomputes and upserts each
affected bucket (see AnalyticsAggregator).
"""

from __future__ import annotations

import asyncio
import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(
    name="app.tasks.badge_analytics.aggregate_badge_analytics",
    bind=True,
    max_retries=0,
)
def aggregate_badge_analytics(self) -> dict:
    """Aggregate analytics for all tenants with badge events."""
    return asyncio.run(_aggregate_all())


async def _aggregate_all() -> dict:
    from sqlalchemy import select

    from app.config import get_settings
    from app.db.session import AsyncSessionLocal
    from app.models.tenant import Tenant
    from app.services.analytics_aggregator import AnalyticsAggregator

    settings = get_settings()
    summary = {"tenants": 0, "buckets": 0}

    # Enumerate tenants from the (non-RLS) tenants table, then let the aggregator
    # scope each tenant via set_tenant_context. This avoids any RLS-bypass toggle
    # and works with a least-privilege DB role. Tenants with no events produce a
    # zero-bucket run, which is cheap.
    async with AsyncSessionLocal() as db:
        tenant_ids = [
            r[0] for r in (await db.execute(select(Tenant.id))).all()
        ]

    for tenant_id in tenant_ids:
        async with AsyncSessionLocal() as db:
            aggregator = AnalyticsAggregator(db=db, settings=settings)
            result = await aggregator.run(tenant_id)
            summary["tenants"] += 1
            summary["buckets"] += result.get("buckets", 0)

    logger.info(
        "Badge analytics aggregation: %d tenants, %d buckets",
        summary["tenants"], summary["buckets"],
    )
    return summary
