"""
Celery application instance with lazy configuration.

Uses a factory function to avoid import-time Settings resolution.
The worker process calls get_celery_app() at startup.
"""

from __future__ import annotations

from functools import lru_cache

from celery import Celery


@lru_cache(maxsize=1)
def get_celery_app() -> Celery:
    """Create and configure the Celery app on first use.

    Deferred so that importing this module doesn't trigger Settings validation
    (which would fail in test environments without env vars).
    """
    from app.config import get_settings

    settings = get_settings()

    app = Celery(
        "repo_saas",
        broker=settings.celery_broker_url,
        backend=settings.celery_result_backend,
    )

    app.conf.update(
        task_serializer=settings.celery_task_serializer,
        result_serializer=settings.celery_result_serializer,
        timezone=settings.celery_timezone,
        accept_content=["json"],
        task_track_started=True,
        worker_prefetch_multiplier=1,
        # Task autodiscovery
        include=[
            "app.tasks.bulk_upload",
            "app.tasks.notifications",
            "app.tasks.webhooks",
            "app.tasks.anomaly_detection",
            "app.tasks.digilocker",
            "app.tasks.retention",
            "app.tasks.anchoring",
        ],
        # Beat schedule for periodic tasks
        beat_schedule={
            "anomaly-detection-sweep": {
                "task": "app.tasks.anomaly_detection.run_anomaly_sweep",
                "schedule": 60.0,  # Every 60 seconds (Req 10.6)
            },
            # Retries DigiLocker pushes left pending/retrying. Previously
            # attempt_push had no caller at all, so failed pushes were never
            # retried (Req 12.2).
            "digilocker-retry-sweep": {
                "task": "app.tasks.digilocker.sweep_digilocker_retries",
                "schedule": 300.0,
            },
            # Refreshes the storage-usage view the quota trigger reads. It was
            # never refreshed, leaving quota enforcement permanently inert
            # (Req 3.7).
            "refresh-storage-usage": {
                "task": "app.tasks.retention.refresh_storage_usage",
                "schedule": 300.0,
            },
            # Creates next month's audit partition ahead of time. 001 only
            # bootstrapped a few months (Req 10.4).
            "audit-partition-maintenance": {
                "task": "app.tasks.retention.ensure_audit_partitions",
                "schedule": 86400.0,
            },
            # Applies tenants.retention_years / audit_log_retention_years.
            "retention-purge": {
                "task": "app.tasks.retention.purge_expired_data",
                "schedule": 86400.0,
            },
            # Seals a Merkle root over newly issued credentials.
            "anchor-batch": {
                "task": "app.tasks.anchoring.anchor_pending_batch",
                "schedule": 600.0,
            },
        },
    )

    return app


def init_celery() -> Celery:
    """Initialize and return the celery app. Called by worker entrypoint."""
    return get_celery_app()


# Module-level Celery instance for the Celery CLI:
#   celery -A app.tasks.celery_app:celery_app worker ...
# Celery's CLI requires an actual Celery instance. This resolves the app when
# the module is imported by the worker/beat process, where env vars are present.
# Tests import individual task modules, not this attribute, so lazy validation
# is preserved for the test suite.
celery_app = get_celery_app()
