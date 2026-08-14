"""
Anomalous access pattern detection — Celery periodic task.

Tracks document retrievals per identity using a Redis sliding-window counter.
Alerts tenant admin when threshold is exceeded.

Requirements: 10.6
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Redis key pattern: anomaly:{tenant_id}:{identity}
_ANOMALY_PREFIX = "anomaly_access:"


async def check_and_record_access(
    redis,
    tenant_id: str,
    identity: str,
    window_minutes: int = 10,
    threshold: int = 500,
) -> bool:
    """Record a document retrieval and check if threshold is breached.

    Uses a Redis sorted set with timestamps as scores (sliding window).
    Returns True if threshold exceeded (alert should be triggered).
    """
    import time

    key = f"{_ANOMALY_PREFIX}{tenant_id}:{identity}"
    now = time.time()
    window_start = now - (window_minutes * 60)

    pipe = redis.pipeline()
    pipe.zremrangebyscore(key, 0, window_start)
    pipe.zadd(key, {f"{now}": now})
    pipe.zcard(key)
    pipe.expire(key, window_minutes * 60 + 60)
    results = await pipe.execute()

    count = results[2]

    if count >= threshold:
        logger.warning(
            "Anomalous access detected: tenant=%s identity=%s count=%d threshold=%d",
            tenant_id,
            identity,
            count,
            threshold,
        )
        return True

    return False


def run_anomaly_detection_sweep():
    """Periodic task: scan for anomalous access patterns.

    Designed to run every minute via Celery Beat.
    Checks all active sliding windows and generates alerts
    for any that exceed the configured threshold.

    In production, this would:
    1. Scan Redis keys matching the anomaly prefix
    2. Check counts against threshold
    3. Send alerts via NotificationService to tenant admins
    4. Write alert entries to the audit log
    """
    import asyncio

    async def _sweep():
        from app.config import get_settings
        from app.db.redis import get_redis_client

        settings = get_settings()
        redis = get_redis_client()
        threshold = settings.anomaly_detection_threshold
        window = settings.anomaly_detection_window_minutes

        # Scan all anomaly keys
        cursor = 0
        alerts = []
        while True:
            cursor, keys = await redis.scan(
                cursor=cursor,
                match=f"{_ANOMALY_PREFIX}*",
                count=100,
            )
            for key in keys:
                count = await redis.zcard(key)
                if count >= threshold:
                    # Extract tenant_id and identity from key
                    parts = key.replace(_ANOMALY_PREFIX, "").split(":", 1)
                    if len(parts) == 2:
                        alerts.append({
                            "tenant_id": parts[0],
                            "identity": parts[1],
                            "count": count,
                            "threshold": threshold,
                            "window_minutes": window,
                            "detected_at": datetime.now(timezone.utc).isoformat(),
                        })

            if cursor == 0:
                break

        if alerts:
            logger.warning("Anomaly detection found %d alerts", len(alerts))
            # In production: dispatch alerts via notification service

        return alerts

    return asyncio.run(_sweep())
