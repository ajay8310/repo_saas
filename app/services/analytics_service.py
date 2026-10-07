"""Issuer analytics read models (U3 — S15, BR-A4).

Tenant-scoped reads over ``badge_analytics_daily``:

* ``overview`` — totals per metric across a date range (tenant-wide rows).
* ``by_badge`` — totals per metric for one badge class across a range.
* ``ranking`` — badge classes ranked by a chosen metric.

All queries run under RLS, so a tenant only ever sees its own rollup (BR-A4).
Reads use the pre-aggregated daily table, never the raw event stream, so the
dashboard stays fast regardless of event volume.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.session import get_db
from app.middleware.tenant_context import set_tenant_context
from app.models.badge import BadgeAnalyticsDaily, BadgeClass

logger = logging.getLogger(__name__)

_METRICS = (
    "issued_count",
    "accepted_count",
    "published_count",
    "shared_count",
    "verified_count",
    "viewed_count",
)
_RANKABLE = frozenset(_METRICS)


@dataclass(frozen=True, slots=True)
class AnalyticsOverview:
    from_day: str
    to_day: str
    totals: dict
    channel_breakdown: dict = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class BadgeAnalytics:
    badge_class_id: str
    totals: dict
    channel_breakdown: dict = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class BadgeRank:
    badge_class_id: str
    badge_name: str
    value: int


class AnalyticsService:
    def __init__(self, db: AsyncSession, settings: Settings) -> None:
        self.db = db
        self.settings = settings

    async def overview(
        self, tenant_id: UUID, days: int = 30
    ) -> AnalyticsOverview:
        """Tenant-wide totals per metric over the last *days* (BR-A3 rows)."""
        start = self._range_start(days)
        await set_tenant_context(self.db, str(tenant_id))

        cols = [func.coalesce(func.sum(getattr(BadgeAnalyticsDaily, m)), 0) for m in _METRICS]
        stmt = select(*cols).where(
            BadgeAnalyticsDaily.badge_class_id.is_(None),
            BadgeAnalyticsDaily.day >= start,
        )
        row = (await self.db.execute(stmt)).one()
        totals = {m: int(v) for m, v in zip(_METRICS, row, strict=True)}
        channels = await self._channel_totals(tenant_id, start, class_id=None)
        return AnalyticsOverview(
            from_day=start.date().isoformat(),
            to_day=datetime.now(UTC).date().isoformat(),
            totals=totals,
            channel_breakdown=channels,
        )

    async def by_badge(
        self, tenant_id: UUID, badge_class_id: UUID, days: int = 30
    ) -> BadgeAnalytics:
        """Per-metric totals for one badge class."""
        start = self._range_start(days)
        await set_tenant_context(self.db, str(tenant_id))

        cols = [func.coalesce(func.sum(getattr(BadgeAnalyticsDaily, m)), 0) for m in _METRICS]
        stmt = select(*cols).where(
            BadgeAnalyticsDaily.badge_class_id == badge_class_id,
            BadgeAnalyticsDaily.day >= start,
        )
        row = (await self.db.execute(stmt)).one()
        totals = {m: int(v) for m, v in zip(_METRICS, row, strict=True)}
        channels = await self._channel_totals(tenant_id, start, class_id=badge_class_id)
        return BadgeAnalytics(
            badge_class_id=str(badge_class_id),
            totals=totals,
            channel_breakdown=channels,
        )

    async def ranking(
        self, tenant_id: UUID, metric: str = "issued_count", days: int = 30, limit: int = 10
    ) -> list[BadgeRank]:
        """Rank badge classes by a metric over the range (desc)."""
        if metric not in _RANKABLE:
            raise ValueError(f"unrankable metric: {metric}")
        start = self._range_start(days)
        await set_tenant_context(self.db, str(tenant_id))

        total = func.coalesce(func.sum(getattr(BadgeAnalyticsDaily, metric)), 0).label("value")
        stmt = (
            select(BadgeAnalyticsDaily.badge_class_id, BadgeClass.name, total)
            .join(BadgeClass, BadgeClass.id == BadgeAnalyticsDaily.badge_class_id)
            .where(
                BadgeAnalyticsDaily.badge_class_id.isnot(None),
                BadgeAnalyticsDaily.day >= start,
            )
            .group_by(BadgeAnalyticsDaily.badge_class_id, BadgeClass.name)
            .order_by(total.desc())
            .limit(limit)
        )
        return [
            BadgeRank(badge_class_id=str(cid), badge_name=name, value=int(val))
            for cid, name, val in (await self.db.execute(stmt)).all()
        ]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _range_start(self, days: int) -> datetime:
        days = max(1, min(days, 366))
        return datetime.now(UTC) - timedelta(days=days)

    async def _channel_totals(
        self, tenant_id: UUID, start: datetime, class_id: UUID | None
    ) -> dict:
        """Sum channel_breakdown JSON across the range (in Python; small set)."""
        stmt = select(BadgeAnalyticsDaily.channel_breakdown).where(
            BadgeAnalyticsDaily.day >= start,
        )
        stmt = stmt.where(
            BadgeAnalyticsDaily.badge_class_id.is_(None)
            if class_id is None
            else BadgeAnalyticsDaily.badge_class_id == class_id
        )
        out: dict[str, int] = {}
        for (breakdown,) in (await self.db.execute(stmt)).all():
            for ch, n in (breakdown or {}).items():
                out[ch] = out.get(ch, 0) + int(n)
        return out


async def get_analytics_service(db: AsyncSession = Depends(get_db)) -> AnalyticsService:
    return AnalyticsService(db=db, settings=get_settings())
