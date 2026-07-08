"""Redis connection and small cache helpers for search responses."""

import logging

import redis.asyncio as redis

from app.config import get_settings

logger = logging.getLogger(__name__)

_redis: redis.Redis | None = None


def get_redis() -> redis.Redis:
    global _redis
    if _redis is None:
        _redis = redis.from_url(get_settings().redis_url, decode_responses=True)
    return _redis


def search_cache_key(query: str) -> str:
    """Cache key for a pattern search, keyed by the normalized query string."""
    return f"patterns:search:{query.strip().lower()}"


def semantic_cache_key(query: str, **filters: object) -> str:
    """Cache key for a semantic search: normalized query plus any active filters."""
    key = f"semantic:{query.strip().lower()}"
    active = {k: v for k, v in sorted(filters.items()) if v is not None}
    if active:
        key += ":" + ":".join(f"{k}={str(v).lower()}" for k, v in active.items())
    return key


async def get_cached(key: str) -> str | None:
    try:
        value = await get_redis().get(key)
    except redis.RedisError as exc:
        logger.warning("Redis GET failed (%s); falling through to Ravelry.", exc)
        return None
    if value is not None:
        logger.info("Cache HIT for %s", key)
    else:
        logger.info("Cache MISS for %s", key)
    return value


async def set_cached(key: str, value: str, ttl_seconds: int) -> None:
    try:
        await get_redis().set(key, value, ex=ttl_seconds)
    except redis.RedisError as exc:
        logger.warning("Redis SET failed (%s); response not cached.", exc)
