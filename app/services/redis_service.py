"""Redis service for caching and session state."""

from typing import Any

import redis.asyncio as redis

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# Global Redis connection pool
_redis_pool: redis.ConnectionPool | None = None
_redis_client: redis.Redis | None = None


async def init_redis() -> None:
    """Initialize Redis connection pool."""
    global _redis_pool, _redis_client

    _redis_pool = redis.ConnectionPool.from_url(
        str(settings.redis_url),
        decode_responses=True,
        max_connections=50,
    )
    _redis_client = redis.Redis(connection_pool=_redis_pool)

    # Verify connection
    await _redis_client.ping()
    logger.info("Redis connection established")


async def close_redis() -> None:
    """Close Redis connections."""
    global _redis_pool, _redis_client

    if _redis_client:
        await _redis_client.aclose()
    if _redis_pool:
        await _redis_pool.disconnect()

    logger.info("Redis connection closed")


def get_redis() -> redis.Redis:
    """Get Redis client instance."""
    if _redis_client is None:
        raise RuntimeError("Redis not initialized. Call init_redis() first.")
    return _redis_client


class RedisService:
    """Redis service for common operations."""

    def __init__(self) -> None:
        self.client = get_redis()

    # Session state management
    async def set_call_state(
        self,
        call_id: str,
        state: dict[str, Any],
        ttl_seconds: int = 3600,
    ) -> None:
        """Store call session state."""
        import json

        key = f"call:{call_id}:state"
        await self.client.setex(key, ttl_seconds, json.dumps(state))

    async def get_call_state(self, call_id: str) -> dict[str, Any] | None:
        """Retrieve call session state."""
        import json

        key = f"call:{call_id}:state"
        data = await self.client.get(key)
        return json.loads(data) if data else None

    async def delete_call_state(self, call_id: str) -> None:
        """Delete call session state."""
        key = f"call:{call_id}:state"
        await self.client.delete(key)

    # Rate limiting
    async def check_rate_limit(
        self,
        key: str,
        max_requests: int,
        window_seconds: int,
    ) -> tuple[bool, int]:
        """
        Check rate limit using sliding window.
        Returns (is_allowed, remaining_requests).
        """
        import time

        now = int(time.time())
        window_start = now - window_seconds
        rate_key = f"ratelimit:{key}"

        pipe = self.client.pipeline()
        pipe.zremrangebyscore(rate_key, 0, window_start)
        pipe.zadd(rate_key, {str(now): now})
        pipe.zcard(rate_key)
        pipe.expire(rate_key, window_seconds)
        results = await pipe.execute()

        request_count = results[2]
        is_allowed = request_count <= max_requests
        remaining = max(0, max_requests - request_count)

        return is_allowed, remaining

    # Caching
    async def cache_get(self, key: str) -> str | None:
        """Get cached value."""
        return await self.client.get(f"cache:{key}")

    async def cache_set(
        self,
        key: str,
        value: str,
        ttl_seconds: int = 300,
    ) -> None:
        """Set cached value."""
        await self.client.setex(f"cache:{key}", ttl_seconds, value)

    async def cache_delete(self, key: str) -> None:
        """Delete cached value."""
        await self.client.delete(f"cache:{key}")

    # Pub/Sub for real-time events
    async def publish(self, channel: str, message: str) -> None:
        """Publish message to channel."""
        await self.client.publish(channel, message)
