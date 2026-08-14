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
        ],
        # Beat schedule for periodic tasks
        beat_schedule={
            "anomaly-detection-sweep": {
                "task": "app.tasks.anomaly_detection.run_anomaly_sweep",
                "schedule": 60.0,  # Every 60 seconds (Req 10.6)
            },
        },
    )

    return app


# Module-level reference for Celery CLI: celery -A app.tasks.celery_app:celery_app
# Only resolves when the worker actually starts (not at import time in tests).
celery_app: Celery | None = None


def init_celery() -> Celery:
    """Initialize and return the celery app. Called by worker entrypoint."""
    global celery_app
    celery_app = get_celery_app()
    return celery_app
