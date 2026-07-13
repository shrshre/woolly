"""Pattern search routes.

Week 1: /patterns/search — proxies Ravelry pattern search with Redis caching.
Week 2: /patterns/semantic-search — hybrid vector + BM25 search over seeded patterns.
"""

import json
import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.cache.redis_client import get_cached, search_cache_key, semantic_cache_key, set_cached
from app.config import Settings, get_settings
from app.db.models import Pattern, SavedPattern, User
from app.db.session import get_db
from app.search.pipeline import search as run_search_pipeline
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


@router.get("/semantic-search", response_model=SemanticSearchResult)
async def semantic_search_patterns(
    q: str = Query(..., min_length=1, description="Natural-language search query"),
    limit: int = Query(10, ge=1, le=50, description="Page size"),
    offset: int = Query(0, ge=0, description="Number of results to skip (pagination)"),
    craft: str | None = Query(None, description="Filter: craft type, e.g. knitting or crochet"),
    difficulty: Literal["beginner", "intermediate", "advanced"] | None = Query(None),
    free: bool | None = Query(None, description="Filter: true for free patterns, false for paid"),
    category: str | None = Query(None, description="Filter: pattern category, e.g. Cardigan"),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> SemanticSearchResult:
    query = q.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query must not be empty.")

    # The full relevance-ranked list (up to MAX_RESULTS) is computed once and
    # cached per query+filters; pages are sliced from it, so "load more" is a
    # cache hit with no recompute. total reflects the full result count.
    cache_key = semantic_cache_key(query, craft=craft, difficulty=difficulty, free=free, category=category)
    cached = await get_cached(cache_key)
    if cached is not None:
        full = json.loads(cached)
    else:
        try:
            full = run_search_pipeline(
                db, query, craft=craft, difficulty=difficulty, free=free, category=category
            )
        except Exception as exc:  # DB down, patterns table missing, etc.
            logger.error("Semantic search failed: %s", exc)
            raise HTTPException(
                status_code=503,
                detail="Semantic search is unavailable. Has the database been seeded?",
            ) from exc

        if not full and not any([craft, difficulty, free is not None, category]):
            raise HTTPException(
                status_code=503,
                detail="No embedded patterns found. Run scripts/seed_patterns.py first.",
            )

        await set_cached(cache_key, json.dumps(full), settings.semantic_cache_ttl_seconds)

    page = full[offset : offset + limit]
    return SemanticSearchResult(
        query=query,
        patterns=[SemanticPatternSummary(**row) for row in page],
        total=len(full),
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
