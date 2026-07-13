"""Two-stage search pipeline: hybrid retrieval -> cross-encoder reranking.

Stage 1 (fast): hybrid vector + BM25 + designer retrieval, over-fetching a
pool of candidates. Stage 2 (accurate): the cross-encoder reranks the whole
pool and returns up to MAX_RESULTS ordered by relevance.

The API layer caches this full ranked list per query+filters and serves it in
pages, so relevance decreases as the user loads more.

If the reranker fails for any reason, the hybrid results are returned
unmodified (capped at MAX_RESULTS) — search must never break because the
second stage is unavailable.
"""

import logging
import time
from typing import Any

from sqlalchemy.orm import Session

from app.search.filters import DifficultyTier
from app.search.hybrid_search import hybrid_search
from app.services import reranking_service

logger = logging.getLogger(__name__)

# Most results we ever rank/return for a single query (5 pages of 10).
MAX_RESULTS = 50
# Candidates pulled from stage 1 into the reranker. Larger than MAX_RESULTS so
# reranking can promote strong matches that stage-1 scoring ranked lower, while
# staying small enough to keep cross-encoder latency reasonable on CPU.
RERANK_POOL = 60


def search(
    db: Session,
    query: str,
    craft: str | None = None,
    difficulty: DifficultyTier | None = None,
    free: bool | None = None,
    category: str | None = None,
    max_results: int = MAX_RESULTS,
) -> list[dict[str, Any]]:
    """Return the full relevance-ranked result list (up to max_results)."""
    started = time.perf_counter()

    candidates = hybrid_search(
        db,
        query,
        limit=RERANK_POOL,
        craft=craft,
        difficulty=difficulty,
        free=free,
        category=category,
    )

    if not candidates:
        return []

    try:
        results = reranking_service.rerank(query, candidates, top_n=max_results)
    except Exception:
        logger.exception("Reranking failed for %r; returning hybrid results unmodified.", query)
        results = candidates[:max_results]

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    logger.info(
        "Search pipeline for %r: %d candidates -> %d results in %dms.",
        query, len(candidates), len(results), elapsed_ms,
    )
    return results
