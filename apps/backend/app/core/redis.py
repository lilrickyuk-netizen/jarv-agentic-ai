"""
JARV Backend - Redis Connection

Provides Redis client for caching, session storage, and worker queue.
"""
import logging
from typing import Optional
from redis.asyncio import Redis, ConnectionPool
from redis.exceptions import ConnectionError, TimeoutError

from app.core.config import settings

logger = logging.getLogger(__name__)

# Global Redis client
_redis_client: Optional[Redis] = None
_redis_pool: Optional[ConnectionPool] = None


async def init_redis() -> Redis:
    """Initialize Redis connection pool and client"""
    global _redis_client, _redis_pool

    if _redis_client is not None:
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
        logger.info(f"Redis connected: {settings.REDIS_URL}")

        return _redis_client

    except (ConnectionError, TimeoutError) as e:
        logger.error(f"Failed to connect to Redis: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error connecting to Redis: {e}")
        raise


async def get_redis() -> Redis:
    """Get Redis client instance"""
    if _redis_client is None:
        return await init_redis()
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
