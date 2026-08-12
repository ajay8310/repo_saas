"""
Per-tenant Redis sliding-window rate limiter.

Uses a sliding window counter algorithm in Redis to enforce per-tenant
request quotas. Returns HTTP 429 with Retry-After header when exceeded.

Requirements: 1.9, 8.4
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

_RATE_LIMIT_PREFIX = "ratelimit:"


@dataclass(frozen=True, slots=True)
class RateLimitResult:
    """Result of a rate limit check."""

    allowed: bool
    remaining: int
    limit: int
    retry_after: int  # seconds until window reset (0 if allowed)


class RateLimiterService:
    """Sliding-window counter rate limiter using Redis.

    Each tenant has a configurable request limit per rolling window.
    The implementation uses a sorted set with timestamps as scores,
    trimming expired entries on each check.
    """

    def __init__(
        self,
        redis: aioredis.Redis,
        default_limit: int,
        window_seconds: int,
    ) -> None:
        self.redis = redis
        self.default_limit = default_limit
        self.window_seconds = window_seconds

    async def check(
        self,
        tenant_id: str,
        tenant_limit: int | None = None,
    ) -> RateLimitResult:
        """Check and consume one request from the tenant's rate limit quota.

        Args:
            tenant_id: The tenant UUID string.
            tenant_limit: Per-tenant override; uses default_limit if None.

        Returns:
            RateLimitResult indicating whether the request is allowed.
        """
        limit = tenant_limit or self.default_limit
        now = time.time()
        window_start = now - self.window_seconds
        key = f"{_RATE_LIMIT_PREFIX}{tenant_id}"

        pipe = self.redis.pipeline()

        # Remove entries outside the current window
        pipe.zremrangebyscore(key, 0, window_start)
        # Count current entries in the window
        pipe.zcard(key)
        # Add the current request timestamp
        pipe.zadd(key, {f"{now}:{id(pipe)}": now})
        # Set TTL to auto-expire the key after the window passes
        pipe.expire(key, self.window_seconds + 1)

        results = await pipe.execute()
        current_count = results[1]  # zcard result (before adding current)

        if current_count >= limit:
            # Over limit — remove the entry we just added
            await self.redis.zremrangebyscore(key, now, now + 1)

            # Calculate retry-after: time until the oldest entry in window expires
            oldest = await self.redis.zrange(key, 0, 0, withscores=True)
            if oldest:
                oldest_time = oldest[0][1]
                retry_after = max(1, int((oldest_time + self.window_seconds) - now))
            else:
                retry_after = self.window_seconds

            return RateLimitResult(
                allowed=False,
                remaining=0,
                limit=limit,
                retry_after=retry_after,
            )

        remaining = max(0, limit - current_count - 1)
        return RateLimitResult(
            allowed=True,
            remaining=remaining,
            limit=limit,
            retry_after=0,
        )

    async def get_usage(self, tenant_id: str) -> int:
        """Get the current request count for a tenant in the active window."""
        now = time.time()
        window_start = now - self.window_seconds
        key = f"{_RATE_LIMIT_PREFIX}{tenant_id}"

        # Trim expired entries and count
        pipe = self.redis.pipeline()
        pipe.zremrangebyscore(key, 0, window_start)
        pipe.zcard(key)
        results = await pipe.execute()
        return results[1]
