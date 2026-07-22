# 06 — Redis & Caching

**The warming shelf: how Woolly makes repeated searches instant.**

---

## Why caching exists

Every search in Woolly involves work that takes time:
- Stage 1 hybrid retrieval: embed query + 3 SQL legs — ~50-100ms
- Stage 2 cross-encoder reranking on 60 pairs: ~200-500ms on CPU
- Total first search: ~300-600ms (acceptable, but not free)

If 100 users all search "beginner hat" at roughly the same time, why do 100 rounds of that
same work? The answer is 30-50ms × 100 = 3-5 seconds of unnecessary computation. All 100
users would get the same result anyway.

**Caching** saves the result of an expensive operation and returns the saved result for
future identical requests — skipping the expensive work entirely.

**Analogy — the warming shelf:** a restaurant's kitchen preps food from scratch (slow).
When the same dish gets ordered repeatedly, the chef puts extra portions on the warming
shelf by the pass (fast). The next 5 customers who order the soup get it instantly from
the shelf. The shelf is cleared every 30 minutes so it doesn't get stale.

---

## What Redis is

**Redis** = Remote Dictionary Server. It's an in-memory key-value store.

- **In-memory:** data lives in RAM, not on disk. This makes it orders of magnitude faster
  than a database (microseconds vs milliseconds). The trade-off: if the server restarts,
  the data is gone. That's fine for a cache — it's temporary by design.
- **Key-value:** data is stored as a pair of (key → value). Like a Python dictionary.
  You `set("my-key", "my-value")` and later `get("my-key")` → `"my-value"`.
- **TTL (Time To Live):** every entry can have an expiry time. Redis automatically deletes
  it when the TTL expires. This prevents the cache from growing forever.

Redis is not a replacement for PostgreSQL — it doesn't store patterns permanently. It
stores *search results* (JSON strings) temporarily so identical queries are fast.

---

## Cache-aside pattern: the three-step dance

Woolly uses the **cache-aside** pattern (also called "lazy loading"). The name comes from
the fact that data is loaded *into* the cache lazily — only when first requested — not
eagerly ahead of time.

The three steps on every request:

```
Step 1: CHECK — look for the result in Redis
    ↓ HIT                         ↓ MISS
Step 2: RETURN immediately    Step 2: COMPUTE the real answer
    ✓ done fast                        (embed query + pgvector search)
                                   Step 3: SAVE to Redis with TTL
                                       then RETURN the result
```

Code (simplified):

```python
async def semantic_search_patterns(q, craft, difficulty, free, category, offset, limit, ...):
    query = q.strip()

    # Step 1: Check cache (keyed by query + all active filters)
    cache_key = semantic_cache_key(query, craft=craft, difficulty=difficulty, free=free, category=category)
    cached = await get_cached(cache_key)
    if cached is not None:
        full = json.loads(cached)  # HIT: full ranked list already computed
    else:
        full = run_search_pipeline(db, query, craft=craft, ...)  # MISS: run pipeline
        await set_cached(cache_key, json.dumps(full), settings.semantic_cache_ttl_seconds)

    # Step 2: Slice the page from the cached full list
    page = full[offset : offset + limit]
    return SemanticSearchResult(query=query, patterns=page, total=len(full))
```

**Key design:** the cache stores a JSON **envelope** — the full ranked list (up to 50
results) plus `top_result_id`, `search_type`, and `latency_ms` — not individual
pages. Page 2, 3, 4 are all cache hits — just different slices of the same list.

See the actual code at: `backend/app/api/patterns.py`

---

## Cache keys: how Redis knows what's what

A **cache key** is the dictionary key under which a result is stored. It must be:
1. **Unique per query:** "beginner hat" and "beginner scarf" should be stored separately
2. **Deterministic:** the same query must always produce the same key
3. **Descriptive:** easy to understand in logs

Woolly's cache key functions:

```python
def search_cache_key(query: str) -> str:
    return f"patterns:search:{query.strip().lower()}"

def semantic_cache_key(query: str, **filters) -> str:
    key = f"semantic:{query.strip().lower()}"
    active = {k: v for k, v in sorted(filters.items()) if v is not None}
    if active:
        key += ":" + ":".join(f"{k}={str(v).lower()}" for k, v in active.items())
    return key
```

Examples:
- `"COZY WINTER SWEATER"` → `"semantic:cozy winter sweater"`
- `"cozy sweater"` + craft=knitting + free=true → `"semantic:cozy sweater:craft=knitting:free=true"`

Different filter combinations get different cache entries — correct, because the ranked
list changes when filters change.

---

## TTL values: why two different expiry times?

Woolly has two caches with different expiry times:

| Cache | Key prefix | TTL | Reason |
|---|---|---|---|
| Ravelry keyword search | `patterns:search:` | **3600s (1 hour)** | Ravelry data changes rarely; longer TTL = more cache hits |
| Semantic/hybrid search results | `semantic:` | **1800s (30 min)** | Slightly more responsive to corpus changes (new patterns seeded) |

**Why any TTL at all?** The cache can't live forever because:
- New patterns get seeded into the database → old cached results don't include them
- Pattern data on Ravelry can change (price, description) → cached data could go stale

**Cache invalidation on seed:** When patterns are seeded (manual or scheduled), Woolly
clears all search caches immediately via `clear_search_caches()` in `redis_client.py`.
Newly seeded patterns are discoverable right away — users don't wait for TTL expiry.
If clearing fails, stale entries expire naturally (graceful degradation).

**How to pick a TTL:** ask "how often does the underlying data change, and how much would
users be hurt by seeing stale data?" Pattern metadata changes infrequently (hours or days),
so 30-60 minutes is the right balance between freshness and cache efficiency.

---

## Graceful degradation: what happens when Redis goes down

A cache is not critical infrastructure — if it goes down, the app should still work (just
slower, not broken). Woolly implements this via graceful degradation:

```python
async def get_cached(key: str) -> str | None:
    try:
        value = await get_redis().get(key)
    except redis.RedisError as exc:
        logger.warning("Redis GET failed (%s); falling through to Ravelry.", exc)
        return None   # ← treat it as a cache miss, continue to the real work
    ...
```

If Redis throws any error (connection refused, timeout, etc.), `get_cached` returns `None`
— which the caller treats as a cache miss and does the full computation instead. The user
gets a slightly slower response, but they still get a response.

Similarly:
```python
async def set_cached(key, value, ttl_seconds) -> None:
    try:
        await get_redis().set(key, value, ex=ttl_seconds)
    except redis.RedisError as exc:
        logger.warning("Redis SET failed (%s); response not cached.", exc)
        # no crash — just don't cache it this time
```

If saving to the cache fails, the result is still returned to the user. The next identical
request just won't be cached either, but everything still works.

**Analogy:** if the warming shelf breaks, the restaurant still serves food — it's just
cooked fresh every time, which is slower. The broken shelf doesn't close the restaurant.

**Interview framing:** "I wrap all Redis calls in try-except and treat errors as cache
misses. This means if Redis is unavailable, users get correct but slower responses instead
of errors. The cache is a performance layer, not a correctness layer."

---

## Cache HIT and MISS logs

Woolly logs cache hits and misses:

```python
if value is not None:
    logger.info("Cache HIT for %s", key)
else:
    logger.info("Cache MISS for %s", key)
```

This produces log output like:
```
2026-07-07 12:00:01 INFO: Cache HIT for semantic:cozy winter sweater
2026-07-07 12:00:05 INFO: Cache MISS for semantic:beginner hat
```

You can verify the cache is working by running two identical searches and watching the logs.
The first search shows MISS, the second shows HIT — verify by running two identical searches
and watching the logs.

---

## What Woolly stores in Redis

Redis values are **strings** (Redis doesn't natively understand Python objects or JSON
structure — it just stores bytes/strings). Woolly serializes the entire `PatternSearchResult`
Pydantic model to a JSON string and stores that:

```python
# Store: serialize to JSON string
await set_cached(cache_key, result.model_dump_json(), ttl_seconds)

# Retrieve: deserialize from JSON string back to Pydantic model
return SemanticSearchResult.model_validate_json(cached)
```

Pydantic's `model_dump_json()` converts the model to a JSON string. `model_validate_json()`
parses a JSON string back into a model. Redis just sees and stores opaque strings.

---

## Async Redis

Woolly uses `redis.asyncio` — the async version of the Redis client:

```python
import redis.asyncio as redis
```

This matters because `await redis.get(key)` (async) returns control to the event loop
while waiting for Redis's response, allowing other requests to be handled concurrently.
Using the synchronous version would block the whole server during every Redis call.

---

## Interview questions for this topic

**Q: How does your caching layer work?**
A: "Cache-aside with Redis. On every search, I check Redis with a key of
`semantic:{normalized-query}:{filters}`. A cache hit returns the pre-computed full ranked
list — no AI models, no database. I slice the requested page from that list. A miss runs
the two-stage pipeline, caches the full list for 30 minutes, then returns the page.
Pagination is free after the first search. Seeding clears all search caches so new patterns
are immediately discoverable."

**Q: Why cache the full result list instead of each page separately?**
A: "Relevance ranking is computed once for the whole result set. Caching the full list means
page 2 is a cache hit with just a slice — no recompute. It also guarantees consistent
ordering across pages. The list is capped at 50 results, so memory per entry is bounded."

**Q: What is cache-aside?**
A: "Cache-aside (or lazy loading) means the application manages the cache manually: check
the cache first, on a miss compute the real answer and write it to the cache, then return.
The alternative is write-through (always write to cache and DB simultaneously), but
cache-aside is simpler and appropriate for read-heavy search results."

**Q: What happens if Redis goes down?**
A: "All Redis calls are wrapped in try-except. If Redis throws any error, `get_cached`
returns None (treating it as a miss) and the app falls through to the actual computation.
Users get correct results, just without the cache speedup. The cache is a performance
layer, not a correctness layer — the app is correct with or without it."

**Q: How did you choose the TTL?**
A: "Pattern data doesn't change often — designers rarely update titles or descriptions.
A 30-minute TTL for semantic search results gives a good balance: frequent queries stay
fast, but if patterns are re-seeded the cache refreshes within half an hour. The Ravelry
keyword proxy uses 1 hour since that data is even more stable."

**Q: Why Redis instead of just storing results in PostgreSQL?**
A: "Redis is an in-memory store — reads and writes are microseconds, vs milliseconds for a
disk-based database. For a cache that's hit on every repeat search, that speed difference
matters a lot. PostgreSQL is the right tool for permanent, structured storage. Redis is
the right tool for fast, temporary storage. They solve different problems."
