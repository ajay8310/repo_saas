"""Issuer badge analytics endpoints (U3 — S15, authenticated).

Tenant-scoped dashboard reads over the daily rollup. All routes require the
``badge:analytics`` permission (issuer / tenant_admin / super_admin).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from app.dependencies.auth import TokenPayload, get_current_user
from app.rbac.permissions import require_permission
from app.services.analytics_service import AnalyticsService, get_analytics_service

router = APIRouter(prefix="/badge-analytics", tags=["badge-analytics"])


@router.get(
    "/overview",
    dependencies=[Depends(require_permission("badge:analytics"))],
)
async def analytics_overview(
    days: int = 30,
    user: TokenPayload = Depends(get_current_user),
    service: AnalyticsService = Depends(get_analytics_service),
) -> dict:
    """Tenant-wide totals per metric over the last *days* (S15)."""
    overview = await service.overview(user.tenant_id, days=days)
    return {
        "from_day": overview.from_day,
        "to_day": overview.to_day,
        "totals": overview.totals,
        "channel_breakdown": overview.channel_breakdown,
    }


@router.get(
    "/by-badge/{badge_class_id}",
    dependencies=[Depends(require_permission("badge:analytics"))],
)
async def analytics_by_badge(
    badge_class_id: UUID,
    days: int = 30,
    user: TokenPayload = Depends(get_current_user),
    service: AnalyticsService = Depends(get_analytics_service),
) -> dict:
    """Per-metric totals for a single badge class (S15)."""
    data = await service.by_badge(user.tenant_id, badge_class_id, days=days)
    return {
        "badge_class_id": data.badge_class_id,
        "totals": data.totals,
        "channel_breakdown": data.channel_breakdown,
    }


@router.get(
    "/ranking",
    dependencies=[Depends(require_permission("badge:analytics"))],
)
async def analytics_ranking(
    metric: str = "issued_count",
    days: int = 30,
    limit: int = 10,
    user: TokenPayload = Depends(get_current_user),
    service: AnalyticsService = Depends(get_analytics_service),
) -> list[dict]:
    """Rank badge classes by a metric over the range (S15)."""
    try:
        ranks = await service.ranking(user.tenant_id, metric=metric, days=days, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "VALIDATION_ERROR", "message": str(exc)})
    return [{"badge_class_id": r.badge_class_id, "badge_name": r.badge_name, "value": r.value} for r in ranks]
