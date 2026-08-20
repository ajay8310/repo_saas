"""
Task enqueue helpers.

Every Celery task in this package was previously unreachable — nothing in the
codebase called ``.delay()`` or ``apply_async()``, so bulk uploads never ran and
webhook events were written as ``pending`` and never delivered.  These helpers
are the single place request handlers hand work to the worker.

Each returns ``True`` when the job was accepted by the broker and ``False`` when
no broker is reachable.  Callers decide what that means: the bulk endpoint fails
the request with 503 because silently accepting a batch nobody will process is
worse than rejecting it, while event fan-out degrades to inline best-effort
because losing a webhook must not fail the originating write.

Enqueue failures are never raised past this module, so a broker outage cannot
turn a successful document upload into a 500.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _send(task_path: str, *args: Any) -> bool:
    """Enqueue *task_path* by name, returning False if it could not be queued.

    Sending by name avoids importing task modules (and their transitive service
    dependencies) into the request path.

    ``get_celery_app()`` is used rather than the module-level ``celery_app``,
    which is only populated by ``init_celery()`` in the worker entrypoint and is
    therefore always None inside the API process.

    ``retry=False`` makes an unreachable broker fail immediately instead of
    blocking the request while Celery retries the connection.
    """
    try:
        from app.tasks.celery_app import get_celery_app

        get_celery_app().send_task(task_path, args=list(args), retry=False)
        return True
    except Exception as exc:  # noqa: BLE001 - never propagate into the request
        logger.warning("Could not enqueue %s: %s", task_path, exc)
        return False


def enqueue_bulk_upload(
    *,
    job_id: str,
    tenant_id: str,
    schema_id: str,
    cmk_arn: str | None,
    records: list[dict],
) -> bool:
    """Queue a bulk upload batch for processing."""
    return _send(
        "app.tasks.bulk_upload.process_bulk_upload",
        job_id,
        tenant_id,
        schema_id,
        records,
        cmk_arn,
    )


def enqueue_webhook_delivery(event_id: str) -> bool:
    """Queue delivery of a single webhook event."""
    return _send("app.tasks.webhooks.deliver_webhook_event", event_id)


def enqueue_notification(
    *,
    tenant_id: str,
    beneficiary_id: str,
    event_type: str,
    context: dict[str, Any] | None = None,
) -> bool:
    """Queue a beneficiary notification."""
    return _send(
        "app.tasks.notifications.send_notification",
        tenant_id,
        beneficiary_id,
        event_type,
        context or {},
    )


def enqueue_digilocker_push(push_id: str) -> bool:
    """Queue a DigiLocker push attempt."""
    return _send("app.tasks.digilocker.attempt_digilocker_push", push_id)
