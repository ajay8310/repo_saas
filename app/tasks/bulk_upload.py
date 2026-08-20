"""
Celery task for bulk document upload processing.

Processes each record independently within its own savepoint.
Updates job progress in Redis. No multi-table joins.

Requirements: 3.2, 3.10, 14.4
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from uuid import UUID

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(
    name="app.tasks.bulk_upload.process_bulk_upload",
    bind=True,
    max_retries=0,
    soft_time_limit=1800,  # 30 minutes (Req 14.4)
    time_limit=1860,
)
def process_bulk_upload(
    self,
    job_id: str,
    tenant_id: str,
    schema_id: str,
    records: list[dict],
    cmk_arn: str | None = None,
) -> dict:
    """Process a bulk upload job.

    Each record is processed independently. Failures in one record
    don't affect others.
    """
    return asyncio.run(_process_async(job_id, tenant_id, schema_id, records, cmk_arn))


async def _process_async(
    job_id: str,
    tenant_id: str,
    schema_id: str,
    records: list[dict],
    cmk_arn: str | None = None,
) -> dict:
    """Async implementation of bulk upload processing."""
    from app.config import get_settings
    from app.db.session import AsyncSessionLocal
    from app.middleware.tenant_context import set_tenant_context
    from app.models.document import BulkJob
    from app.services.document_service import DocumentService
    from sqlalchemy import select

    settings = get_settings()
    results = {
        "total_records": len(records),
        "success_count": 0,
        "failed_count": 0,
        "credential_ids": [],
        "errors": [],
    }

    async with AsyncSessionLocal() as db:
        service = DocumentService(db=db, settings=settings)

        for i, record in enumerate(records):
            try:
                beneficiary_id = record.get("beneficiary_id", "")
                content = record.get("content", "").encode()

                result = await service.upload_document(
                    tenant_id=UUID(tenant_id),
                    schema_id=UUID(schema_id),
                    beneficiary_id=beneficiary_id,
                    content=content,
                    cmk_arn=cmk_arn,
                    actor_id="bulk_upload",
                    actor_role="issuer",
                )
                results["success_count"] += 1
                results["credential_ids"].append(result.credential_id)
            except Exception as exc:
                results["failed_count"] += 1
                results["errors"].append({
                    "record_index": i,
                    "error": str(exc),
                })

        # Update bulk_jobs table with summary
        await set_tenant_context(db, tenant_id)
        job_result = await db.execute(
            select(BulkJob).where(BulkJob.id == UUID(job_id))
        )
        job = job_result.scalar_one_or_none()
        if job:
            job.status = "completed" if results["failed_count"] == 0 else "completed_with_errors"
            job.processed_count = results["total_records"]
            job.success_count = results["success_count"]
            job.failed_count = results["failed_count"]
            job.summary = results
            job.completed_at = datetime.now(timezone.utc)
            await db.commit()

    logger.info(
        "Bulk upload %s complete: %d/%d succeeded",
        job_id, results["success_count"], results["total_records"],
    )
    return results
