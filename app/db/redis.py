"""
Redis client factory for OTP storage, rate limiting, and caching.

Usage in service layer:
    from app.db.redis import get_redis

    async def some_endpoint(redis: Redis = Depends(get_redis)):
        await redis.set("key", "value", ex=600)
"""

from __future__ import annotations

from typing import AsyncGenerator

import redis.asyncio as aioredis

from app.config import get_settings

settings = get_settings()

# ---------------------------------------------------------------------------
# Connection pool (shared across the application lifetime)
# ---------------------------------------------------------------------------

_pool = aioredis.ConnectionPool.from_url(
    settings.redis_url,
    max_connections=settings.redis_pool_size,
    decode_responses=True,
)


def get_redis_client() -> aioredis.Redis:
    """Return a Redis client bound to the shared connection pool.

    This is NOT an async generator — it returns a reusable client instance.
    The pool handles connection lifecycle.
    """
    return aioredis.Redis(connection_pool=_pool)


async def get_redis() -> AsyncGenerator[aioredis.Redis, None]:
    """FastAPI dependency that yields a Redis client."""
    client = get_redis_client()
    try:
        yield client
    finally:
        # Connection is returned to the pool automatically; no explicit close needed.
        pass
