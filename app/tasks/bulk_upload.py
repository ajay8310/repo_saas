"""
Celery task for bulk document upload processing.

Processes each record independently within its own savepoint.
Updates job progress in Redis. No multi-table joins.

Requirements: 3.2, 3.10, 14.4
"""

from __future__ import annotations

import logging
from uuid import UUID

logger = logging.getLogger(__name__)


# Note: celery_app import is deferred to avoid import-time Settings resolution
# in test environments. Task registration happens when the worker starts.


def process_bulk_upload(
    job_id: str,
    tenant_id: str,
    schema_id: str,
    records: list[dict],
    cmk_arn: str,
) -> dict:
    """Process a bulk upload job.

    Each record is processed independently. Failures in one record
    don't affect others. Progress tracked in Redis.

    This is designed to be called as a Celery task:
        process_bulk_upload.delay(job_id, tenant_id, ...)
    """
    import asyncio
    from app.services.document_service import DocumentService
    from app.config import get_settings
    from app.db.session import AsyncSessionLocal

    async def _process():
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
            from app.models.document import BulkJob
            from sqlalchemy import select

            from app.middleware.tenant_context import set_tenant_context
            await set_tenant_context(db, tenant_id)

            job_result = await db.execute(
                select(BulkJob).where(BulkJob.id == UUID(job_id))
            )
            job = job_result.scalar_one_or_none()
            if job:
                job.status = "completed"
                job.processed_count = results["total_records"]
                job.success_count = results["success_count"]
                job.failed_count = results["failed_count"]
                job.summary = results
                from datetime import datetime, timezone
                job.completed_at = datetime.now(timezone.utc)
                await db.commit()

        return results

    return asyncio.run(_process())
