"""Badge analytics aggregation (U3 — S15, BR-A1..A5, Q6=A).

Rolls ``badge_events`` up into ``badge_analytics_daily`` per
(tenant, day, badge_class), plus a tenant-wide row (badge_class_id = NULL) that
equals the sum of the per-class rows for each metric (BR-A3).

Idempotent (BR-A2): counts for a (tenant, day, class) bucket are computed from
the events themselves and written with an upsert on the UNIQUE key, so
re-running over the same events yields the same rollup — ``aggregate(aggregate
(x)) == aggregate(x)``. To keep re-runs cheap, a per-run watermark (max event
``created_at`` seen) is stored in Redis and only buckets touched since the
previous watermark are recomputed; a cold Redis simply reprocesses a bounded
window, which is safe because the write is a full recompute-and-upsert of each
affected bucket, not an increment.

Events are never mutated (BR-A1); this only reads them.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.middleware.tenant_context import set_tenant_context
from app.models.badge import BadgeAnalyticsDaily, BadgeEvent

logger = logging.getLogger(__name__)

_WATERMARK_KEY = "badge_analytics:watermark"
# How far back to recompute when there's no watermark (cold start / Redis loss).
_COLD_START_WINDOW = timedelta(days=30)

_COUNT_COLUMNS = {
    "issued": "issued_count",
    "accepted": "accepted_count",
    "published": "published_count",
    "shared": "shared_count",
    "verified": "verified_count",
    "viewed": "viewed_count",
}


class AnalyticsAggregator:
    def __init__(self, db: AsyncSession, settings: Settings) -> None:
        self.db = db
        self.settings = settings

    async def run(self, tenant_id: UUID) -> dict:
        """Recompute affected daily buckets for one tenant. Returns a summary."""
        await set_tenant_context(self.db, str(tenant_id))

        since = await self._read_watermark(tenant_id)
        now = datetime.now(UTC)

        # Which (day, class) buckets were touched since the watermark?
        touched = await self._touched_buckets(tenant_id, since)
        if not touched:
            await self._write_watermark(tenant_id, now)
            return {"tenant_id": str(tenant_id), "buckets": 0}

        per_class_totals: dict[datetime, dict] = defaultdict(_zero_metrics)

        for day, class_id in touched:
            counts, channels = await self._bucket_counts(tenant_id, day, class_id)
            await self._upsert(tenant_id, day, class_id, counts, channels)
            # Accumulate into the tenant-wide (class=NULL) row for that day.
            agg = per_class_totals[day]
            for col, val in counts.items():
                agg[col] += val
            for ch, c in channels.items():
                agg["channel_breakdown"][ch] = agg["channel_breakdown"].get(ch, 0) + c

        # Tenant-wide rows must equal the SUM across *all* classes for the day,
        # not just the touched ones — recompute from scratch per affected day.
        for day in {d for d, _ in touched}:
            counts, channels = await self._bucket_counts(tenant_id, day, None, tenant_wide=True)
            await self._upsert(tenant_id, day, None, counts, channels)

        await self._write_watermark(tenant_id, now)
        return {"tenant_id": str(tenant_id), "buckets": len(touched)}

    # ------------------------------------------------------------------
    # Event queries
    # ------------------------------------------------------------------

    async def _touched_buckets(
        self, tenant_id: UUID, since: datetime | None
    ) -> list[tuple[datetime, UUID | None]]:
        day = func.date_trunc("day", BadgeEvent.created_at)
        stmt = select(day, BadgeEvent.badge_class_id).where(
            BadgeEvent.tenant_id == tenant_id
        )
        if since is not None:
            stmt = stmt.where(BadgeEvent.created_at > since)
        stmt = stmt.group_by(day, BadgeEvent.badge_class_id)
        rows = (await self.db.execute(stmt)).all()
        return [(r[0], r[1]) for r in rows]

    async def _bucket_counts(
        self,
        tenant_id: UUID,
        day: datetime,
        class_id: UUID | None,
        tenant_wide: bool = False,
    ) -> tuple[dict, dict]:
        """Count events by type for a (day[, class]) bucket."""
        day_start = day
        day_end = day + timedelta(days=1)
        stmt = select(BadgeEvent.event_type, BadgeEvent.channel, func.count()).where(
            BadgeEvent.tenant_id == tenant_id,
            BadgeEvent.created_at >= day_start,
            BadgeEvent.created_at < day_end,
        )
        if not tenant_wide:
            if class_id is None:
                stmt = stmt.where(BadgeEvent.badge_class_id.is_(None))
            else:
                stmt = stmt.where(BadgeEvent.badge_class_id == class_id)
        stmt = stmt.group_by(BadgeEvent.event_type, BadgeEvent.channel)

        counts = {col: 0 for col in _COUNT_COLUMNS.values()}
        channels: dict[str, int] = {}
        for event_type, channel, n in (await self.db.execute(stmt)).all():
            col = _COUNT_COLUMNS.get(event_type)
            if col:
                counts[col] += n
            if event_type == "shared" and channel:
                channels[channel] = channels.get(channel, 0) + n
        return counts, channels

    # ------------------------------------------------------------------
    # Upsert
    # ------------------------------------------------------------------

    async def _upsert(
        self,
        tenant_id: UUID,
        day: datetime,
        class_id: UUID | None,
        counts: dict,
        channels: dict,
    ) -> None:
        """Upsert a daily row, overwriting counts (idempotent recompute).

        NULL class_id doesn't match a plain ON CONFLICT target, so the two
        partial unique indexes are used as the conflict arbiters.
        """
        values = {
            "tenant_id": tenant_id,
            "day": day,
            "badge_class_id": class_id,
            "channel_breakdown": channels,
            "updated_at": datetime.now(UTC),
            **counts,
        }
        stmt = pg_insert(BadgeAnalyticsDaily).values(**values)
        update_cols = {c: stmt.excluded[c] for c in [*counts.keys(), "channel_breakdown", "updated_at"]}
        index_where = (
            BadgeAnalyticsDaily.badge_class_id.is_(None)
            if class_id is None
            else BadgeAnalyticsDaily.badge_class_id.isnot(None)
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=(
                [BadgeAnalyticsDaily.tenant_id, BadgeAnalyticsDaily.day]
                if class_id is None
                else [
                    BadgeAnalyticsDaily.tenant_id,
                    BadgeAnalyticsDaily.day,
                    BadgeAnalyticsDaily.badge_class_id,
                ]
            ),
            index_where=index_where,
            set_=update_cols,
        )
        await self.db.execute(stmt)
        await self.db.commit()

    # ------------------------------------------------------------------
    # Watermark (Redis)
    # ------------------------------------------------------------------

    async def _read_watermark(self, tenant_id: UUID) -> datetime | None:
        try:
            from app.db.redis import get_redis_client

            raw = await get_redis_client().get(f"{_WATERMARK_KEY}:{tenant_id}")
            if raw:
                return datetime.fromisoformat(raw)
        except Exception:
            logger.debug("No analytics watermark; cold start", exc_info=True)
        return datetime.now(UTC) - _COLD_START_WINDOW

    async def _write_watermark(self, tenant_id: UUID, ts: datetime) -> None:
        try:
            from app.db.redis import get_redis_client

            await get_redis_client().set(f"{_WATERMARK_KEY}:{tenant_id}", ts.isoformat())
        except Exception:
            logger.debug("Could not persist analytics watermark", exc_info=True)


def _zero_metrics() -> dict:
    d = {col: 0 for col in _COUNT_COLUMNS.values()}
    d["channel_breakdown"] = {}
    return d
