"""Two-stage search pipeline: hybrid retrieval -> cross-encoder reranking.

Stage 1 (fast): hybrid vector + BM25 + designer retrieval, over-fetching a
pool of candidates. Stage 2 (accurate): the cross-encoder reranks the whole
pool and returns up to MAX_RESULTS ordered by relevance.

The API layer caches this full ranked list per query+filters and serves it in
pages, so relevance decreases as the user loads more.

If the reranker fails for any reason, the hybrid results are returned
unmodified (capped at MAX_RESULTS) — search must never break because the
second stage is unavailable. The request is marked degraded (see
app.observability), so the API neither caches nor hides it.
"""

import logging
import time
from typing import Any

from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import Pattern
from app.observability import fallback, stage
from app.search.filters import DifficultyTier
from app.search.hybrid_search import hybrid_search
from app.services import reranking_service

logger = logging.getLogger(__name__)

# Most results we ever rank/return for a single query (5 pages of 10).
MAX_RESULTS = 50
# Candidates pulled from stage 1 into the reranker. Larger than MAX_RESULTS so
# reranking can promote strong matches that stage-1 scoring ranked lower, while
# staying small enough to keep cross-encoder latency reasonable on CPU.
# Cost is linear in the pool, so it is a setting (RERANK_POOL) to measure
# against the search eval floors rather than a constant.
RERANK_POOL = get_settings().rerank_pool


def search(
    db: Session,
    query: str,
    craft: str | None = None,
    difficulty: DifficultyTier | None = None,
    free: bool | None = None,
    category: str | None = None,
    max_results: int = MAX_RESULTS,
    include_candidates: bool = False,
) -> dict[str, Any]:
    """Run the pipeline and return an envelope of the full ranked list plus the
    pipeline-time analytics facts the API layer logs and caches:

        {"results": [...], "top_result_id": int | None,
         "search_type": "hybrid" | "semantic", "latency_ms": int}

    top_result_id is the internal Pattern.id of the first ranked result — the
    result dicts only carry ravelry_id, so it is resolved here before the API
    caches the envelope, keeping cache hits able to log it correctly.

    include_candidates adds "candidate_ids": the stage-1 ravelry ids in hybrid
    order, before reranking. Offline evaluation only; the API leaves it off so
    cached envelopes stay small.
    """
    started = time.perf_counter()

    with stage("retrieve"):
        candidates, search_type = hybrid_search(
            db,
            query,
            limit=RERANK_POOL,
            craft=craft,
            difficulty=difficulty,
            free=free,
            category=category,
        )

    candidate_ids = [c["id"] for c in candidates]
    if not candidates:
        envelope = {"results": [], "top_result_id": None, "search_type": search_type, "latency_ms": 0}
        if include_candidates:
            envelope["candidate_ids"] = []
        return envelope

    try:
        with stage("rerank"):
            results = reranking_service.rerank(query, candidates, top_n=max_results)
    except Exception:
        logger.exception("Reranking failed for %r; returning hybrid results unmodified.", query)
        fallback("rerank")
        results = candidates[:max_results]

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    logger.info(
        "Search pipeline for %r: %d candidates -> %d results in %dms.",
        query, len(candidates), len(results), elapsed_ms,
    )

    # Result dicts expose ravelry_id as "id"; resolve the top one to the
    # internal PK the search_events.top_result_id FK expects.
    top_result_id = (
        db.query(Pattern.id).filter(Pattern.ravelry_id == results[0]["id"]).scalar()
        if results
        else None
    )
    envelope = {
        "results": results,
        "top_result_id": top_result_id,
        "search_type": search_type,
        "latency_ms": elapsed_ms,
    }
    if include_candidates:
        envelope["candidate_ids"] = candidate_ids
    return envelope
