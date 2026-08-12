"""
Celery application instance.

Configured from app.config settings. Used by all task modules.
"""

from __future__ import annotations

from celery import Celery

from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "repo_saas",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_serializer=settings.celery_task_serializer,
    result_serializer=settings.celery_result_serializer,
    timezone=settings.celery_timezone,
    accept_content=["json"],
    task_track_started=True,
    worker_prefetch_multiplier=1,
)
