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


@shared_task(
    name="app.tasks.badge_bulk.bulk_issue_badges_with_photos",
    bind=True,
    max_retries=0,
    soft_time_limit=1800,
    time_limit=1860,
)
def bulk_issue_badges_with_photos(
    self,
    job_id: str,
    tenant_id: str,
    badge_class_id: str,
    recipients: list[dict],
    actor_id: str = "bulk_issue",
) -> dict:
    """Issue a badge to each recipient and attach their staged photo (ZIP bulk).

    ``recipients`` is a list of ``{"beneficiary_id", "photo_key", "photo_content_type"}``
    produced by :class:`app.services.zip_bulk_service.ZipBulkService`. Each
    record is issued independently; a failure for one never aborts the rest.
    """
    return asyncio.run(
        _bulk_issue_photos_async(job_id, tenant_id, badge_class_id, recipients, actor_id)
    )


async def _bulk_issue_photos_async(
    job_id: str,
    tenant_id: str,
    badge_class_id: str,
    recipients: list[dict],
    actor_id: str,
) -> dict:
    """Async implementation of ZIP bulk badge issuance with photos."""
    from app.config import get_settings
    from app.db.session import AsyncSessionLocal
    from app.services.certificate_service import (
        CertificateService,
        CertificateValidationError,
    )
    from app.services.issuance_service import IssuanceService

    settings = get_settings()
    results: dict = {
        "job_id": job_id,
        "total": len(recipients),
        "success_count": 0,
        "failed_count": 0,
        "photo_attached_count": 0,
        "photo_failed_count": 0,
        "assertion_ids": [],
        "errors": [],
    }

    async with AsyncSessionLocal() as db:
        issuance = IssuanceService(db=db, settings=settings)
        cert = CertificateService(db=db, settings=settings)
        notify_each = len(recipients) <= 100
        for i, rec in enumerate(recipients):
            beneficiary_id = rec.get("beneficiary_id", "")
            photo_key = rec.get("photo_key")
            photo_content_type = rec.get("photo_content_type")
            try:
                result = await issuance.issue(
                    tenant_id=UUID(tenant_id),
                    badge_class_id=UUID(badge_class_id),
                    beneficiary_id=beneficiary_id,
                    actor_id=actor_id,
                    actor_role="issuer",
                    notify=notify_each,
                )
                results["success_count"] += 1
                results["assertion_ids"].append(result.assertion_id)
            except Exception as exc:  # noqa: BLE001 - record and continue
                results["failed_count"] += 1
                results["errors"].append({"record_index": i, "error": str(exc)})
                continue

            # Best-effort photo attach: a photo failure never fails the badge.
            if photo_key and photo_content_type:
                try:
                    content = _fetch_staged(settings, photo_key)
                    if content is None:
                        raise CertificateValidationError("staged photo could not be read")
                    await cert.upload_recipient_photo(
                        tenant_id=UUID(tenant_id),
                        assertion_id=UUID(result.assertion_id),
                        content=content,
                        content_type=photo_content_type,
                        actor_id=actor_id,
                        actor_role="issuer",
                    )
                    results["photo_attached_count"] += 1
                except Exception as exc:  # noqa: BLE001 - record and continue
                    results["photo_failed_count"] += 1
                    results["errors"].append(
                        {"record_index": i, "error": f"photo attach failed: {exc}"}
                    )

    # Best-effort cleanup of the per-job staging prefix.
    _cleanup_staging(tenant_id, job_id)

    logger.info(
        "Bulk badge issue+photos %s complete: %d/%d issued, %d photos attached",
        job_id, results["success_count"], results["total"], results["photo_attached_count"],
    )
    return results


@shared_task(
    name="app.tasks.badge_bulk.bulk_attach_photos",
    bind=True,
    max_retries=0,
    soft_time_limit=1800,
    time_limit=1860,
)
def bulk_attach_photos(
    self,
    job_id: str,
    tenant_id: str,
    photos: list[dict],
    actor_id: str = "bulk_photo",
    badge_class_id: str | None = None,
) -> dict:
    """Attach staged photos to recipients' already-issued credentials (later upload).

    ``photos`` is a list of ``{"beneficiary_id", "photo_key", "photo_content_type"}``.
    Each photo is matched to the recipient's existing active assertion(s) by email
    and attached via the single-issue photo path. When ``badge_class_id`` is set,
    only that class's assertions are targeted. Independent per-record failures.
    """
    return asyncio.run(
        _bulk_attach_photos_async(job_id, tenant_id, photos, actor_id, badge_class_id)
    )


async def _bulk_attach_photos_async(
    job_id: str,
    tenant_id: str,
    photos: list[dict],
    actor_id: str,
    badge_class_id: str | None,
) -> dict:
    from app.config import get_settings
    from app.db.session import AsyncSessionLocal
    from app.services.issuance_service import IssuanceService

    settings = get_settings()
    results: dict = {
        "job_id": job_id,
        "total": len(photos),
        "matched_count": 0,
        "unmatched_count": 0,
        "attached_count": 0,
        "failed_count": 0,
        "errors": [],
    }
    class_uuid = UUID(badge_class_id) if badge_class_id else None

    async with AsyncSessionLocal() as db:
        issuance = IssuanceService(db=db, settings=settings)
        for i, rec in enumerate(photos):
            beneficiary_id = rec.get("beneficiary_id", "")
            photo_key = rec.get("photo_key")
            photo_content_type = rec.get("photo_content_type")
            if not photo_key or not photo_content_type:
                continue
            try:
                assertions = await issuance.list_assertions_for_beneficiary(
                    tenant_id=UUID(tenant_id),
                    beneficiary_id=beneficiary_id,
                    active_only=True,
                    badge_class_id=class_uuid,
                )
            except Exception as exc:  # noqa: BLE001
                results["failed_count"] += 1
                results["errors"].append({"record_index": i, "beneficiary_id": beneficiary_id,
                                          "error": f"lookup failed: {exc}"})
                continue

            if not assertions:
                results["unmatched_count"] += 1
                results["errors"].append(
                    {"record_index": i, "beneficiary_id": beneficiary_id,
                     "error": "no issued credential for this recipient yet"}
                )
                continue

            results["matched_count"] += 1
            content = _fetch_staged(settings, photo_key)
            if content is None:
                results["failed_count"] += 1
                results["errors"].append({"record_index": i, "beneficiary_id": beneficiary_id,
                                          "error": "staged photo could not be read"})
                continue
            # Attach to every matching assertion (same face across certificates).
            for a in assertions:
                err = await _attach_with_retry(
                    settings, UUID(tenant_id), a.id, content, photo_content_type, actor_id
                )
                if err is None:
                    results["attached_count"] += 1
                else:
                    results["failed_count"] += 1
                    results["errors"].append(
                        {"record_index": i, "beneficiary_id": beneficiary_id,
                         "assertion_id": str(a.id), "error": f"attach failed: {err}"}
                    )

    _cleanup_staging(tenant_id, job_id)
    logger.info(
        "Bulk photo attach %s complete: %d photos, %d matched, %d attached, %d unmatched",
        job_id, results["total"], results["matched_count"],
        results["attached_count"], results["unmatched_count"],
    )
    return results


async def _attach_with_retry(
    settings,
    tenant_id: UUID,
    assertion_id: UUID,
    content: bytes,
    content_type: str,
    actor_id: str,
    attempts: int = 3,
) -> str | None:
    """Attach one photo, retrying transient failures. Returns None on success.

    Each attempt uses a fresh DB session + CertificateService so a failed
    transaction (or a flaky scanner/S3 call under the prefork worker) never
    poisons the next try. Transient ``CertificateServiceUnavailableError`` is
    retried with short backoff; validation / not-found errors fail immediately.
    """
    import asyncio as _asyncio

    from app.db.session import AsyncSessionLocal
    from app.services.certificate_service import (
        CertificateNotFoundError,
        CertificateService,
        CertificateServiceUnavailableError,
        CertificateValidationError,
    )

    last_err: str = "unknown error"
    for attempt in range(1, attempts + 1):
        try:
            async with AsyncSessionLocal() as db:
                cert = CertificateService(db=db, settings=settings)
                await cert.upload_recipient_photo(
                    tenant_id=tenant_id,
                    assertion_id=assertion_id,
                    content=content,
                    content_type=content_type,
                    actor_id=actor_id,
                    actor_role="issuer",
                )
            return None
        except (CertificateValidationError, CertificateNotFoundError) as exc:
            # Permanent — do not retry.
            return str(exc)
        except CertificateServiceUnavailableError as exc:
            last_err = str(exc)
        except Exception as exc:  # noqa: BLE001 - treat unknown as transient-ish
            last_err = str(exc)
        if attempt < attempts:
            await _asyncio.sleep(0.5 * attempt)
    return last_err


def _s3_client(settings):
    import boto3

    kwargs: dict = {"region_name": settings.aws_region}
    if settings.s3_endpoint_url:
        kwargs["endpoint_url"] = settings.s3_endpoint_url
    if settings.aws_access_key_id:
        kwargs["aws_access_key_id"] = settings.aws_access_key_id
        kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
    return boto3.client("s3", **kwargs)


def _fetch_staged(settings, key: str) -> bytes | None:
    try:
        resp = _s3_client(settings).get_object(Bucket=settings.s3_bucket_name, Key=key)
        return resp["Body"].read()
    except Exception:
        logger.warning("Could not fetch staged bulk photo %s", key, exc_info=True)
        return None


def _cleanup_staging(tenant_id: str, job_id: str) -> None:
    from app.config import get_settings

    settings = get_settings()
    prefix = f"{settings.badge_image_prefix}/{tenant_id}/_bulk_staging/{job_id}/"
    try:
        s3 = _s3_client(settings)
        resp = s3.list_objects_v2(Bucket=settings.s3_bucket_name, Prefix=prefix)
        objs = [{"Key": o["Key"]} for o in resp.get("Contents", [])]
        if objs:
            s3.delete_objects(Bucket=settings.s3_bucket_name, Delete={"Objects": objs})
    except Exception:
        logger.debug("Staging cleanup skipped for %s", prefix, exc_info=True)
