"""
Maintenance and retention tasks.

Three gaps in the original schema are covered here.

``refresh_storage_usage``
    ``check_quota_before_insert()`` compares usage against
    ``tenant_storage_usage``, a materialized view that nothing ever refreshed.
    An empty view makes ``v_current_use`` NULL, ``NULL >= v_quota`` false, and
    storage quota enforcement silently inert.

``ensure_audit_partitions``
    001 bootstrapped a handful of monthly partitions and a default catch-all,
    noting that "new ones should be created by a periodic maintenance job".
    That job did not exist, so all rows past the bootstrapped window fall into
    ``audit_logs_default`` and the partitioning buys nothing.

``purge_expired_data``
    ``tenants.retention_years`` was settable but never enforced, and
    ``audit_log_retention_years`` was never read at all.  DPDP storage
    limitation requires personal data not be kept past its purpose, so this
    applies both.

Requirements: 3.7, 10.4, 7.5
"""

from __future__ import annotations

import asyncio
import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="app.tasks.retention.refresh_storage_usage")
def refresh_storage_usage() -> bool:
    """Refresh the storage-usage view the quota trigger reads."""
    return asyncio.run(_refresh_storage_usage_async())


async def _refresh_storage_usage_async() -> bool:
    from sqlalchemy import text

    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        try:
            # CONCURRENTLY needs the unique index 001 created and avoids
            # blocking uploads while the view rebuilds.
            await db.execute(
                text("REFRESH MATERIALIZED VIEW CONCURRENTLY tenant_storage_usage")
            )
            await db.commit()
            return True
        except Exception:
            logger.exception("Failed to refresh tenant_storage_usage")
            await db.rollback()
            return False


@shared_task(name="app.tasks.retention.ensure_audit_partitions")
def ensure_audit_partitions(months_ahead: int = 3) -> list[str]:
    """Pre-create monthly audit_logs partitions."""
    return asyncio.run(_ensure_partitions_async(months_ahead))


async def _ensure_partitions_async(months_ahead: int) -> list[str]:
    from datetime import date

    from sqlalchemy import text

    from app.db.session import AsyncSessionLocal

    created: list[str] = []
    today = date.today()

    async with AsyncSessionLocal() as db:
        for offset in range(months_ahead + 1):
            year = today.year + (today.month - 1 + offset) // 12
            month = (today.month - 1 + offset) % 12 + 1
            start = date(year, month, 1)
            end = date(year + (month // 12), month % 12 + 1, 1)
            name = f"audit_logs_{year}_{month:02d}"

            try:
                await db.execute(
                    text(
                        f"CREATE TABLE IF NOT EXISTS {name} PARTITION OF audit_logs "
                        f"FOR VALUES FROM ('{start.isoformat()}') "
                        f"TO ('{end.isoformat()}')"
                    )
                )
                await db.commit()
                created.append(name)
            except Exception:
                # Most likely the range overlaps audit_logs_default, which has
                # to be detached before a real partition can take its rows.
                logger.exception("Could not create audit partition %s", name)
                await db.rollback()

    return created


@shared_task(name="app.tasks.retention.purge_expired_data")
def purge_expired_data(dry_run: bool = False) -> dict:
    """Drop data past its tenant-configured retention window."""
    return asyncio.run(_purge_async(dry_run))


async def _purge_async(dry_run: bool) -> dict:
    from sqlalchemy import select, text

    from app.config import get_settings
    from app.db.session import AsyncSessionLocal
    from app.models.tenant import Tenant

    settings = get_settings()
    summary: dict[str, object] = {"dry_run": dry_run, "tenants": [], "audit_partitions": []}

    async with AsyncSessionLocal() as db:
        tenants = (
            await db.execute(select(Tenant.id, Tenant.retention_years))
        ).all()

        for tenant_id, retention_years in tenants:
            # Documents are the only tenant-scoped store with a retention
            # clock; verification tokens and webhook events expire on their own
            # much shorter schedules.
            stmt = text(
                """
                DELETE FROM documents
                 WHERE tenant_id = :tenant_id
                   AND created_at < now() - (:years * INTERVAL '1 year')
                """
            )
            count_stmt = text(
                """
                SELECT count(*) FROM documents
                 WHERE tenant_id = :tenant_id
                   AND created_at < now() - (:years * INTERVAL '1 year')
                """
            )
            params = {"tenant_id": str(tenant_id), "years": retention_years}

            try:
                affected = (await db.execute(count_stmt, params)).scalar() or 0
                if affected and not dry_run:
                    await db.execute(stmt, params)
                    await db.commit()
                if affected:
                    summary["tenants"].append(
                        {
                            "tenant_id": str(tenant_id),
                            "retention_years": retention_years,
                            "documents_removed": affected,
                        }
                    )
            except Exception:
                logger.exception("Retention purge failed for tenant %s", tenant_id)
                await db.rollback()

        # Audit logs are immutable (a trigger blocks UPDATE and DELETE), so
        # expiry has to happen by dropping whole partitions rather than by
        # deleting rows.
        try:
            partitions = (
                await db.execute(
                    text(
                        """
                        SELECT c.relname
                          FROM pg_class c
                          JOIN pg_inherits i ON i.inhrelid = c.oid
                          JOIN pg_class p ON p.oid = i.inhparent
                         WHERE p.relname = 'audit_logs'
                           AND c.relname ~ '^audit_logs_[0-9]{4}_[0-9]{2}$'
                        """
                    )
                )
            ).scalars().all()

            cutoff_year = _retention_cutoff_year(settings.audit_log_retention_years)
            for name in partitions:
                year, month = int(name[-7:-3]), int(name[-2:])
                if (year, month) < cutoff_year:
                    if not dry_run:
                        await db.execute(text(f"DROP TABLE IF EXISTS {name}"))
                        await db.commit()
                    summary["audit_partitions"].append(name)
        except Exception:
            logger.exception("Audit partition retention sweep failed")
            await db.rollback()

    logger.info("Retention purge summary: %s", summary)
    return summary


def _retention_cutoff_year(retention_years: int) -> tuple[int, int]:
    """Return the (year, month) before which audit partitions may be dropped."""
    from datetime import date

    today = date.today()
    return (today.year - retention_years, today.month)
