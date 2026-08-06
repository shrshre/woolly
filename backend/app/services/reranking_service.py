"""Cross-encoder reranking service (stage 2 of the search pipeline).

Unlike the bi-encoder embedding model (which embeds query and document
separately), the cross-encoder scores the query and document *together*,
which is far more accurate but too slow to run over the whole corpus —
so it only reorders the small candidate set from hybrid retrieval.

Same singleton pattern as embedding_service: loaded once, reused.
"""

import logging
import math
import threading
from typing import Any

logger = logging.getLogger(__name__)

MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"

# Scores below this are dropped from results (after sigmoid, 0-1 scale)...
MIN_RERANK_SCORE = 0.1
# ...but never below this many results: when the threshold-passing set is
# short, it is backfilled with the next-highest-scoring candidates so a
# query with enough retrieved candidates always yields a full page.
MIN_RESULT_COUNT = 10

_model = None
_model_lock = threading.Lock()


def get_reranker():
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                from sentence_transformers import CrossEncoder

                logger.info("Loading cross-encoder model %s ...", MODEL_NAME)
                _model = CrossEncoder(MODEL_NAME)
                logger.info("Cross-encoder model loaded.")
    return _model


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def relevance_label(score: float) -> str:
    if score > 0.7:
        return "Strong match"
    if score > 0.4:
        return "Good match"
    return "Possible match"


def _pattern_to_text(pattern: dict[str, Any]) -> str:
    name = pattern.get("name") or ""
    designer = pattern.get("designer") or "unknown designer"
    description = (pattern.get("description") or "")[:200]
    return f"{name} by {designer}. {description}"


def rerank(query: str, candidates: list[dict[str, Any]], top_n: int = 10) -> list[dict[str, Any]]:
    """Reorder candidates by cross-encoder relevance to the query.

    The model outputs raw logits; a sigmoid maps them to 0-1 so the
    rerank_score works with the fixed label/threshold cutoffs and the
    UI's proportional relevance bar. Mutates and returns the candidate
    dicts with rerank_score and relevance_label set.

    Returns at least min(MIN_RESULT_COUNT, len(candidates), top_n) results:
    the sub-threshold tail is only dropped when enough candidates clear
    MIN_RERANK_SCORE on their own.
    """
    if not candidates:
        return []

    pairs = [(query, _pattern_to_text(p)) for p in candidates]
    scores = get_reranker().predict(pairs)

    ranked = sorted(zip(candidates, scores), key=lambda x: float(x[1]), reverse=True)

    results = []
    for pattern, score in ranked[:top_n]:
        pattern["rerank_score"] = round(_sigmoid(float(score)), 4)
        pattern["relevance_label"] = relevance_label(pattern["rerank_score"])
        results.append(pattern)

    kept = [r for r in results if r["rerank_score"] >= MIN_RERANK_SCORE]
    if len(kept) < MIN_RESULT_COUNT:
        # Backfill with the best below-threshold candidates (they keep their
        # real scores and "Possible match" labels) so the threshold trims the
        # tail of a rich result set but never starves a sparse one.
        below = [r for r in results if r["rerank_score"] < MIN_RERANK_SCORE]
        kept = kept + below[: MIN_RESULT_COUNT - len(kept)]
    return kept
