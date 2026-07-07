"""Pattern search routes.

Week 1: /patterns/search — proxies Ravelry pattern search with Redis caching.
Week 2: /patterns/semantic-search — pgvector similarity search over seeded patterns.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.cache.redis_client import get_cached, search_cache_key, semantic_cache_key, set_cached
from app.config import Settings, get_settings
from app.db.session import get_db
from app.search.semantic_search import semantic_search as run_semantic_search
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


class SemanticSearchResult(PatternSearchResult):
    patterns: list[SemanticPatternSummary]  # type: ignore[assignment]


@router.get("/semantic-search", response_model=SemanticSearchResult)
async def semantic_search_patterns(
    q: str = Query(..., min_length=1, description="Natural-language search query"),
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> SemanticSearchResult:
    query = q.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query must not be empty.")

    cache_key = semantic_cache_key(query)
    cached = await get_cached(cache_key)
    if cached is not None:
        return SemanticSearchResult.model_validate_json(cached)

    try:
        rows = run_semantic_search(db, query, limit=limit)
    except Exception as exc:  # DB down, patterns table missing, etc.
        logger.error("Semantic search failed: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="Semantic search is unavailable. Has the database been seeded?",
        ) from exc

    if not rows:
        raise HTTPException(
            status_code=503,
            detail="No embedded patterns found. Run scripts/seed_patterns.py first.",
        )

    result = SemanticSearchResult(
        query=query,
        patterns=[SemanticPatternSummary(**row) for row in rows],
        total=len(rows),
    )
    await set_cached(cache_key, result.model_dump_json(), settings.semantic_cache_ttl_seconds)
    return result
