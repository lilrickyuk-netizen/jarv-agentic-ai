"""
JARV Backend - Redis Connection

Provides Redis client for caching, session storage, and worker queue.
"""
import logging
import os
from typing import Optional
from redis.asyncio import Redis, ConnectionPool
from redis.exceptions import ConnectionError, TimeoutError

from app.core.config import settings

logger = logging.getLogger(__name__)

# Global Redis client
_redis_client: Optional[Redis] = None
_redis_pool: Optional[ConnectionPool] = None
_redis_loop = None


async def init_redis() -> Redis:
    """Initialize Redis connection pool and client"""
    global _redis_client, _redis_pool

    if _redis_client is not None:
        return _redis_client

    # Test-only path: use an in-memory fakeredis client so the test suite can
    # run without a real Redis server. This branch is gated strictly on
    # settings.TESTING (set only by tests/conftest.py); production and dev are
    # unaffected and continue to use a real Redis connection pool below.
    use_test_double = (
        getattr(settings, "TESTING", False)
        and os.getenv("JARV_TEST_REAL_REDIS") != "1"
    )
    if use_test_double:
        import fakeredis.aioredis as _fakeredis  # dev/test dependency only

        class _TestFakeRedis(_fakeredis.FakeRedis):
            # fakeredis does not implement the Redis INFO command. The health/
            # readiness checks call info("server"); provide a minimal, clearly
            # test-only response so the in-memory double reports as reachable
            # (real Redis returns full server info in production).
            async def info(self, section=None):  # type: ignore[override]
                return {"redis_version": "fakeredis", "uptime_in_seconds": 0}

        _redis_client = _TestFakeRedis(decode_responses=True)
        await _redis_client.ping()
        logger.info("Redis (TEST MODE): using in-memory fakeredis")
        return _redis_client

    try:
        # Create connection pool
        _redis_pool = ConnectionPool.from_url(
            str(settings.REDIS_URL),
            encoding="utf-8",
            decode_responses=True,
            max_connections=settings.REDIS_MAX_CONNECTIONS,
            socket_connect_timeout=5,
            socket_keepalive=True,
        )

        # Create Redis client
        _redis_client = Redis(connection_pool=_redis_pool)

        # Test connection
        await _redis_client.ping()
        logger.info("Redis connection established")

        return _redis_client

    except (ConnectionError, TimeoutError) as e:
        logger.error(f"Failed to connect to Redis: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error connecting to Redis: {e}")
        raise


async def get_redis() -> Redis:
    """Get the Redis client for the running event loop.

    The API runs one event loop for its whole life. Celery tasks run each job in
    a fresh ``asyncio.run`` loop, and a pooled connection opened on a finished
    loop cannot be used on the next one, so a client made on another loop is
    replaced (the test double is loop-independent and kept)."""
    global _redis_client, _redis_pool, _redis_loop
    import asyncio

    loop = asyncio.get_running_loop()
    if _redis_client is not None and _redis_pool is not None and _redis_loop is not loop:
        _redis_client, _redis_pool = None, None
    if _redis_client is None:
        client = await init_redis()
        _redis_loop = loop
        return client
    return _redis_client


async def close_redis() -> None:
    """Close Redis connection"""
    global _redis_client, _redis_pool

    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None
        logger.info("Redis connection closed")

    if _redis_pool is not None:
        await _redis_pool.aclose()
        _redis_pool = None


async def check_redis_health() -> dict:
    """Check Redis connection health"""
    try:
        client = await get_redis()
        await client.ping()

        # Get server info
        info = await client.info("server")

        return {
            "status": "healthy",
            "redis_version": info.get("redis_version", "unknown"),
            "uptime_seconds": info.get("uptime_in_seconds", 0),
        }
    except Exception as e:
        logger.error(f"Redis health check failed: {e}")
        return {
            "status": "unhealthy",
            "error": str(e),
        }
