"""Redis connection and small cache helpers for search responses."""

import hashlib
import logging

import redis as redis_sync
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


def ask_cache_key(question: str, history: list[str]) -> str:
    """Cache key for one conversational answer.

    The whole conversation is part of the key, because the same question means
    different things after different turns ("cheaper ones?"). Hashed rather
    than embedded so key length stays bounded no matter how long the chat gets.
    """
    conversation = "\n".join([*history, question.strip().lower()])
    return "ask:answer:" + hashlib.sha256(conversation.encode("utf-8")).hexdigest()[:32]


def ask_rate_limit_key(identity: str) -> str:
    """Rate-limit counter key. Deliberately not under the ask:answer: prefix,
    so clearing cached answers after a seed run never resets anyone's quota."""
    return f"ratelimit:ask:{identity}"


async def increment_rate_limit(key: str, window_seconds: int) -> int | None:
    """Count one hit in a fixed window and return the running total.

    Returns None when Redis is unreachable — the limiter fails open, since
    losing Redis should degrade cost control, not break the feature.
    """
    try:
        pipe = get_redis().pipeline()
        pipe.incr(key)
        pipe.expire(key, window_seconds, nx=True)
        count, _ = await pipe.execute()
        return int(count)
    except redis.RedisError as exc:
        logger.warning("Redis rate-limit check failed (%s); allowing the request.", exc)
        return None


def recommendations_cache_key(user_id: int | None, limit: int) -> str:
    """Cache key for homepage recommendations: per user, or shared for anonymous."""
    who = f"user:{user_id}" if user_id is not None else "anon"
    return f"recs:{who}:limit={limit}"


async def invalidate_user_recommendations(user_id: int) -> None:
    """Drop a user's cached recommendations (called when their library changes).

    Best-effort: on Redis failure the stale entry simply expires via TTL.
    """
    try:
        client = get_redis()
        keys = [key async for key in client.scan_iter(match=f"recs:user:{user_id}:*", count=100)]
        if keys:
            await client.delete(*keys)
    except redis.RedisError as exc:
        logger.warning("Failed to invalidate recommendations for user %d (%s).", user_id, exc)


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


# Search-related key prefixes, invalidated after each seed run so newly
# seeded patterns are immediately discoverable (recommendations included, so
# fresh patterns can surface on the homepage right away; cached conversational
# answers too, since they cite a now-stale shortlist).
SEARCH_CACHE_PREFIXES = ("patterns:search:*", "semantic:*", "recs:*", "ask:answer:*")


def clear_search_caches() -> int:
    """Delete all cached search responses. Sync — used by the seeding pipeline.

    Returns the number of keys deleted. Never raises: cache clearing is
    best-effort and must not fail a seed run.
    """
    deleted = 0
    try:
        client = redis_sync.from_url(get_settings().redis_url, decode_responses=True)
        for prefix in SEARCH_CACHE_PREFIXES:
            batch: list[str] = []
            for key in client.scan_iter(match=prefix, count=500):
                batch.append(key)
                if len(batch) >= 500:
                    deleted += client.delete(*batch)
                    batch = []
            if batch:
                deleted += client.delete(*batch)
        client.close()
        logger.info("Cleared %d cached search entries.", deleted)
    except redis_sync.RedisError as exc:
        logger.warning("Failed to clear search caches (%s); stale entries will expire via TTL.", exc)
    return deleted
