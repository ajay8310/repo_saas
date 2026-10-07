"""Celery task for bulk badge issuance (FR-5).

Issues one assertion per beneficiary independently: a failure for one recipient
never aborts the rest, mirroring ``app.tasks.bulk_upload``. Per-record issuing
delegates to :meth:`IssuanceService.issue`, so the same validation, audit,
event, and notification path used for single issuance applies to every record.
"""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(
    name="app.tasks.badge_bulk.bulk_issue_badges",
    bind=True,
    max_retries=0,
    soft_time_limit=1800,
    time_limit=1860,
)
def bulk_issue_badges(
    self,
    job_id: str,
    tenant_id: str,
    badge_class_id: str,
    beneficiary_ids: list[str],
    actor_id: str = "bulk_issue",
) -> dict:
    """Issue a badge to each beneficiary in the list, independently."""
    return asyncio.run(
        _bulk_issue_async(job_id, tenant_id, badge_class_id, beneficiary_ids, actor_id)
    )


async def _bulk_issue_async(
    job_id: str,
    tenant_id: str,
    badge_class_id: str,
    beneficiary_ids: list[str],
    actor_id: str,
) -> dict:
    """Async implementation of bulk badge issuance."""
    from app.config import get_settings
    from app.db.session import AsyncSessionLocal
    from app.services.issuance_service import IssuanceService

    settings = get_settings()
    results: dict = {
        "job_id": job_id,
        "total": len(beneficiary_ids),
        "success_count": 0,
        "failed_count": 0,
        "assertion_ids": [],
        "errors": [],
    }

    async with AsyncSessionLocal() as db:
        service = IssuanceService(db=db, settings=settings)
        for i, beneficiary_id in enumerate(beneficiary_ids):
            try:
                result = await service.issue(
                    tenant_id=UUID(tenant_id),
                    badge_class_id=UUID(badge_class_id),
                    beneficiary_id=beneficiary_id,
                    actor_id=actor_id,
                    actor_role="issuer",
                    # Suppress per-record notifications for very large batches;
                    # a single digest is preferable, left to U2/U3.
                    notify=len(beneficiary_ids) <= 100,
                )
                results["success_count"] += 1
                results["assertion_ids"].append(result.assertion_id)
            except Exception as exc:  # noqa: BLE001 - record and continue
                results["failed_count"] += 1
                results["errors"].append({"record_index": i, "error": str(exc)})

    logger.info(
        "Bulk badge issue %s complete: %d/%d succeeded",
        job_id, results["success_count"], results["total"],
    )
    return results
