"""Pattern search routes.

Week 1: /patterns/search — proxies Ravelry pattern search with Redis caching.
Week 2: /patterns/semantic-search — hybrid vector + BM25 search over seeded patterns.
"""

import json
import logging
import time
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user, get_current_user_optional
from app.cache.redis_client import get_cached, search_cache_key, semantic_cache_key, set_cached
from app.config import Settings, get_settings
from app.db.models import Pattern, ResultInteraction, SavedPattern, SearchEvent, User
from app.db.session import get_db, get_sessionmaker
from app.search.pipeline import search as run_search_pipeline
from app.services import clip_service, reranking_service
from app.services.ravelry_client import (
    PatternProvider,
    PatternSearchResult,
    PatternSummary,
    RavelryAuthError,
    RavelryClient,
    RavelryRateLimitError,
    RavelryUnavailableError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/patterns", tags=["patterns"])


def get_pattern_provider(settings: Settings = Depends(get_settings)) -> PatternProvider:
    """Dependency boundary: swap this provider out when moving to OAuth."""
    return RavelryClient(
        username=settings.ravelry_username,
        password=settings.ravelry_password,
        base_url=settings.ravelry_api_base_url,
    )


@router.get("/search", response_model=PatternSearchResult)
async def search_patterns(
    q: str = Query(..., min_length=1, description="Search query"),
    provider: PatternProvider = Depends(get_pattern_provider),
    settings: Settings = Depends(get_settings),
) -> PatternSearchResult:
    query = q.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query must not be empty.")

    cache_key = search_cache_key(query)
    cached = await get_cached(cache_key)
    if cached is not None:
        return PatternSearchResult.model_validate_json(cached)

    try:
        result = await provider.search_patterns(query)
    except RavelryRateLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except RavelryAuthError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except RavelryUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    await set_cached(cache_key, result.model_dump_json(), settings.search_cache_ttl_seconds)
    return result


class SemanticPatternSummary(PatternSummary):
    similarity_score: float
    description: str | None = None
    difficulty: str | None = None  # Ravelry difficulty average, e.g. "3.2" (0-10 scale)
    # None when the reranker was unavailable and hybrid results passed through as-is
    rerank_score: float | None = None
    relevance_label: str | None = None  # "Strong match" / "Good match" / "Possible match"


class SemanticSearchResult(PatternSearchResult):
    patterns: list[SemanticPatternSummary]  # type: ignore[assignment]
    # Id of the logged search_events row, so the frontend can attribute later
    # save/click interactions to the search that produced them. None if the
    # analytics write failed (search itself still succeeds).
    search_event_id: int | None = None


def _log_search_event(
    *,
    session_id: str,
    user_id: int | None,
    query: str,
    filters: dict,
    result_count: int,
    top_result_id: int | None,
    latency_ms: int,
    cache_hit: bool,
    search_type: str,
) -> int | None:
    """Write one search_events row synchronously and return its id.

    Synchronous (not BackgroundTasks) on purpose: the search response needs the
    real FK id so result_interactions can reference it, and a background task
    couldn't return the DB-generated id. It's a single fast INSERT on a fresh
    session (never the request session, which is torn down after the response),
    and any failure is logged and swallowed so analytics never 500s the search.
    """
    try:
        with get_sessionmaker()() as session:
            event = SearchEvent(
                session_id=session_id,
                user_id=user_id,
                query=query,
                filters=filters,
                result_count=result_count,
                top_result_id=top_result_id,
                latency_ms=latency_ms,
                cache_hit=cache_hit,
                search_type=search_type,
            )
            session.add(event)
            session.commit()
            return event.id
    except Exception:
        logger.exception("Failed to log search event for %r; continuing.", query)
        return None


@router.get("/semantic-search", response_model=SemanticSearchResult)
async def semantic_search_patterns(
    q: str = Query(..., min_length=1, description="Natural-language search query"),
    limit: int = Query(10, ge=1, le=50, description="Page size"),
    offset: int = Query(0, ge=0, description="Number of results to skip (pagination)"),
    craft: str | None = Query(None, description="Filter: craft type, e.g. knitting or crochet"),
    difficulty: Literal["beginner", "intermediate", "advanced"] | None = Query(None),
    free: bool | None = Query(None, description="Filter: true for free patterns, false for paid"),
    category: str | None = Query(None, description="Filter: pattern category, e.g. Cardigan"),
    session_id: str | None = Query(None, description="Anonymous browser session id, for analytics"),
    user: User | None = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> SemanticSearchResult:
    query = q.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query must not be empty.")

    # Search must never 500 for want of a session id.
    session_id = session_id or str(uuid.uuid4())

    # The full relevance-ranked list (up to MAX_RESULTS) plus its pipeline-time
    # facts (top_result_id, search_type) are computed once and cached per
    # query+filters as an envelope; pages are sliced from it, so "load more" is
    # a cache hit with no recompute. total reflects the full result count.
    cache_key = semantic_cache_key(query, craft=craft, difficulty=difficulty, free=free, category=category)
    started = time.perf_counter()
    cached = await get_cached(cache_key)
    cache_hit = cached is not None

    if cache_hit:
        envelope = json.loads(cached)
        # Tolerate pre-Phase-4 cache entries that stored a bare list of results.
        if isinstance(envelope, list):
            envelope = {"results": envelope, "top_result_id": None, "search_type": "hybrid"}
        # cache-hit latency is the (tiny) cost of fetching from Redis; a
        # sub-millisecond hit still records as 1ms, never a misleading 0.
        latency_ms = max(1, round((time.perf_counter() - started) * 1000))
    else:
        try:
            envelope = run_search_pipeline(
                db, query, craft=craft, difficulty=difficulty, free=free, category=category
            )
        except Exception as exc:  # DB down, patterns table missing, etc.
            logger.error("Semantic search failed: %s", exc)
            raise HTTPException(
                status_code=503,
                detail="Semantic search is unavailable. Has the database been seeded?",
            ) from exc

        if not envelope["results"] and not any([craft, difficulty, free is not None, category]):
            raise HTTPException(
                status_code=503,
                detail="No embedded patterns found. Run scripts/seed_patterns.py first.",
            )

        latency_ms = envelope["latency_ms"]
        await set_cached(cache_key, json.dumps(envelope), settings.semantic_cache_ttl_seconds)

    results = envelope["results"]
    page = results[offset : offset + limit]

    filters = {
        k: v
        for k, v in {"craft": craft, "difficulty": difficulty, "free": free, "category": category}.items()
        if v is not None
    }
    search_event_id = _log_search_event(
        session_id=session_id,
        user_id=user.id if user else None,
        query=query,
        filters=filters,
        result_count=len(page),
        top_result_id=envelope.get("top_result_id"),
        latency_ms=latency_ms,
        cache_hit=cache_hit,
        search_type=envelope.get("search_type", "hybrid"),
    )

    return SemanticSearchResult(
        query=query,
        patterns=[SemanticPatternSummary(**row) for row in page],
        total=len(results),
        search_event_id=search_event_id,
    )


MAX_UPLOAD_BYTES = 10 * 1024 * 1024
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
VISUAL_SEARCH_QUERY_LABEL = "[image search]"  # search_events.query is NOT NULL


@router.post("/visual-search", response_model=SemanticSearchResult)
async def visual_search_patterns(
    file: UploadFile,
    limit: int = Query(10, ge=5, le=30, description="Results to return (min 5)"),
    session_id: str | None = Query(None, description="Anonymous browser session id, for analytics"),
    user: User | None = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
) -> SemanticSearchResult:
    """Find patterns whose photos look like the uploaded image.

    CLIP image-to-image similarity over the pattern photo corpus. Always
    returns the top-N nearest neighbors (no score threshold), so a valid
    image never yields an empty result set.
    """
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=415, detail="Upload a JPEG, PNG, or WebP image.")
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Image too large (max 10MB).")

    started = time.perf_counter()
    try:
        query_vector = clip_service.embed_image_bytes(data)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    vector_literal = "[" + ",".join(str(v) for v in query_vector) + "]"
    rows = db.execute(
        text(
            """
            SELECT ravelry_id, name, designer, description, difficulty,
                   ravelry_url, image_url, is_free, id AS internal_id,
                   1 - (image_embedding <=> CAST(:vec AS vector)) AS similarity
            FROM patterns
            WHERE image_embedding IS NOT NULL
            ORDER BY image_embedding <=> CAST(:vec AS vector)
            LIMIT :limit
            """
        ),
        {"vec": vector_literal, "limit": limit},
    ).mappings().all()

    if not rows:
        raise HTTPException(
            status_code=503,
            detail="No image-embedded patterns yet. Run scripts/embed_images.py first.",
        )

    latency_ms = max(1, round((time.perf_counter() - started) * 1000))
    patterns = []
    for row in rows:
        similarity = round(float(row["similarity"]), 4)
        patterns.append(
            SemanticPatternSummary(
                id=row["ravelry_id"],
                name=row["name"],
                designer=row["designer"],
                permalink=None,
                ravelry_url=row["ravelry_url"],
                photo_url=row["image_url"],
                free=row["is_free"],
                description=row["description"],
                difficulty=row["difficulty"],
                similarity_score=similarity,
                # Surfaced as rerank_score so the UI relevance bar renders;
                # for visual search this is raw CLIP cosine similarity.
                rerank_score=similarity,
                relevance_label=reranking_service.relevance_label(similarity),
            )
        )

    search_event_id = _log_search_event(
        session_id=session_id or str(uuid.uuid4()),
        user_id=user.id if user else None,
        query=VISUAL_SEARCH_QUERY_LABEL,
        filters={},
        result_count=len(patterns),
        top_result_id=rows[0]["internal_id"],
        latency_ms=latency_ms,
        cache_hit=False,
        search_type="visual",
    )

    return SemanticSearchResult(
        query=VISUAL_SEARCH_QUERY_LABEL,
        patterns=patterns,
        total=len(patterns),
        search_event_id=search_event_id,
    )


@router.get("/filters")
async def get_filter_options(db: Session = Depends(get_db)) -> dict:
    """Distinct craft and category values from seeded data, most common first."""
    from sqlalchemy import func

    crafts = [
        row[0]
        for row in db.query(Pattern.craft)
        .filter(Pattern.craft.isnot(None))
        .group_by(Pattern.craft)
        .order_by(func.count().desc())
        .all()
    ]
    categories = [
        row[0]
        for row in db.query(Pattern.category)
        .filter(Pattern.category.isnot(None))
        .group_by(Pattern.category)
        .order_by(func.count().desc())
        .all()
    ]
    return {"crafts": crafts, "categories": categories}


def pattern_summary_dict(pattern: Pattern) -> dict:
    """Serialize a stored Pattern to the shared PatternSummary shape."""
    return {
        "id": pattern.ravelry_id,
        "name": pattern.name,
        "designer": pattern.designer,
        "permalink": None,
        "ravelry_url": pattern.ravelry_url,
        "photo_url": pattern.image_url,
        "free": pattern.is_free,
        "description": pattern.description,
        "difficulty": pattern.difficulty,
    }


def _get_pattern_or_404(db: Session, ravelry_id: int) -> Pattern:
    pattern = db.query(Pattern).filter(Pattern.ravelry_id == ravelry_id).one_or_none()
    if pattern is None:
        raise HTTPException(status_code=404, detail="Pattern not found.")
    return pattern


@router.post("/{ravelry_id}/save", status_code=204)
async def save_pattern(
    ravelry_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    pattern = _get_pattern_or_404(db, ravelry_id)
    already = db.get(SavedPattern, (user.id, pattern.id))
    if already is None:
        db.add(SavedPattern(user_id=user.id, pattern_id=pattern.id))
        db.commit()


@router.delete("/{ravelry_id}/save", status_code=204)
async def unsave_pattern(
    ravelry_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    pattern = _get_pattern_or_404(db, ravelry_id)
    saved = db.get(SavedPattern, (user.id, pattern.id))
    if saved is not None:
        db.delete(saved)
        db.commit()


class InteractionCreate(BaseModel):
    search_event_id: int
    position: int  # 1-indexed, absolute across pages
    action: Literal["save", "ravelry_click"]


@router.post("/{ravelry_id}/interactions", status_code=204)
async def log_interaction(
    ravelry_id: int,
    body: InteractionCreate,
    db: Session = Depends(get_db),
) -> None:
    """Record a save/click on a search result for analytics. Separate from
    /save so the existing bookmark contract is untouched. Anonymous — anyone
    can log interactions on their own search results."""
    pattern = _get_pattern_or_404(db, ravelry_id)

    # Ignore interactions referencing an unknown search (e.g. an expired/flushed
    # event) rather than 500 on the FK violation.
    if db.get(SearchEvent, body.search_event_id) is None:
        return

    db.add(
        ResultInteraction(
            search_event_id=body.search_event_id,
            pattern_id=pattern.id,
            position=body.position,
            action=body.action,
        )
    )
    db.commit()
