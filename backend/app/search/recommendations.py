"""Personalized pattern recommendations.

Builds a "taste vector" for a user by averaging the text embeddings of their
saved patterns (strong signal) and their recent search queries (weaker
signal), then finds the nearest not-yet-saved patterns by cosine similarity
in pgvector. When there is no signal — an anonymous visitor or a brand-new
account — callers fall back to popular_patterns(), a popularity ranking
built from library saves and result clicks.
"""

import logging

import numpy as np
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.db.models import Pattern, ResultInteraction, SavedPattern, SearchEvent
from app.services import embedding_service

logger = logging.getLogger(__name__)

# How much history feeds the taste vector. Recent activity only, so taste
# drifts with the user instead of being anchored to their first saves.
MAX_SAVED_SIGNALS = 20
MAX_QUERY_SIGNALS = 10

# A deliberate save says more about taste than a typed query.
SAVED_WEIGHT = 2.0
QUERY_WEIGHT = 1.0

# Over-fetch candidates so the per-designer diversity cap can't starve a page.
CANDIDATE_MULTIPLIER = 3
MAX_PER_DESIGNER = 2

# search_events.query placeholder for visual searches — carries no text signal.
VISUAL_QUERY_LABEL = "[image search]"


def saved_pattern_ids(db: Session, user_id: int) -> list[int]:
    """All pattern ids in the user's library (for exclusion from results)."""
    rows = db.query(SavedPattern.pattern_id).filter(SavedPattern.user_id == user_id).all()
    return [row[0] for row in rows]


def combine_signal_vectors(
    saved_vectors: list[list[float]], query_vectors: list[list[float]]
) -> list[float] | None:
    """Weighted-average saved-pattern and query embeddings into one unit vector.

    Returns None when there are no signals, or when the average degenerates to
    the zero vector (cosine distance is undefined against it).
    """
    vectors: list[np.ndarray] = []
    weights: list[float] = []
    for vec in saved_vectors:
        vectors.append(np.asarray(vec, dtype=np.float32))
        weights.append(SAVED_WEIGHT)
    for vec in query_vectors:
        vectors.append(np.asarray(vec, dtype=np.float32))
        weights.append(QUERY_WEIGHT)
    if not vectors:
        return None

    taste = np.average(np.stack(vectors), axis=0, weights=weights)
    norm = float(np.linalg.norm(taste))
    if norm == 0.0:
        return None
    return (taste / norm).tolist()


def diversify(candidates: list[Pattern], limit: int) -> list[Pattern]:
    """Pick up to `limit` candidates, capping each designer at MAX_PER_DESIGNER.

    Candidates must already be ordered best-first. If the cap leaves the page
    short, remaining slots are backfilled in original order.
    """
    picked: list[Pattern] = []
    per_designer: dict[str, int] = {}
    for pattern in candidates:
        if len(picked) >= limit:
            break
        key = (pattern.designer or "").strip().lower()
        if key and per_designer.get(key, 0) >= MAX_PER_DESIGNER:
            continue
        per_designer[key] = per_designer.get(key, 0) + 1
        picked.append(pattern)

    if len(picked) < limit:
        chosen = {p.id for p in picked}
        for pattern in candidates:
            if len(picked) >= limit:
                break
            if pattern.id not in chosen:
                picked.append(pattern)
    return picked


def _recent_query_texts(db: Session, user_id: int) -> list[str]:
    """The user's most recent distinct text search queries, newest first."""
    rows = (
        db.query(SearchEvent.query, func.max(SearchEvent.created_at).label("last_searched"))
        .filter(
            SearchEvent.user_id == user_id,
            SearchEvent.search_type != "visual",
            SearchEvent.query != VISUAL_QUERY_LABEL,
        )
        .group_by(SearchEvent.query)
        .order_by(desc("last_searched"))
        .limit(MAX_QUERY_SIGNALS)
        .all()
    )
    return [row[0] for row in rows]


def recommend_for_user(db: Session, user_id: int, limit: int) -> list[Pattern] | None:
    """Embedding-similarity recommendations for a user, or None with no signal.

    None (rather than []) tells the caller to fall back to popularity —
    an empty list would mean "personalized, but nothing matched".
    """
    saved_rows = (
        db.query(Pattern.embedding)
        .join(SavedPattern, SavedPattern.pattern_id == Pattern.id)
        .filter(SavedPattern.user_id == user_id, Pattern.embedding.isnot(None))
        .order_by(SavedPattern.created_at.desc())
        .limit(MAX_SAVED_SIGNALS)
        .all()
    )
    saved_vectors = [row[0] for row in saved_rows]

    query_texts = _recent_query_texts(db, user_id)
    query_vectors = embedding_service.embed_texts(query_texts) if query_texts else []

    taste = combine_signal_vectors(saved_vectors, query_vectors)
    if taste is None:
        return None

    exclude_ids = saved_pattern_ids(db, user_id)
    candidates_query = db.query(Pattern).filter(Pattern.embedding.isnot(None))
    if exclude_ids:
        candidates_query = candidates_query.filter(Pattern.id.notin_(exclude_ids))
    candidates = (
        candidates_query.order_by(Pattern.embedding.cosine_distance(taste))
        .limit(limit * CANDIDATE_MULTIPLIER)
        .all()
    )
    return diversify(candidates, limit)


def popular_patterns(db: Session, limit: int, exclude_ids: list[int] | None = None) -> list[Pattern]:
    """Patterns ranked by engagement: library saves (2x) plus result clicks.

    Ties (e.g. a freshly seeded corpus with no engagement yet) fall back to
    newest-first, so the section is never empty once patterns exist.
    """
    save_counts = (
        db.query(SavedPattern.pattern_id.label("pid"), func.count().label("saves"))
        .group_by(SavedPattern.pattern_id)
        .subquery()
    )
    click_counts = (
        db.query(ResultInteraction.pattern_id.label("pid"), func.count().label("clicks"))
        .group_by(ResultInteraction.pattern_id)
        .subquery()
    )
    popularity = (
        func.coalesce(save_counts.c.saves, 0) * 2 + func.coalesce(click_counts.c.clicks, 0)
    ).label("popularity")

    query = (
        db.query(Pattern)
        .outerjoin(save_counts, save_counts.c.pid == Pattern.id)
        .outerjoin(click_counts, click_counts.c.pid == Pattern.id)
        .filter(Pattern.image_url.isnot(None))
    )
    if exclude_ids:
        query = query.filter(Pattern.id.notin_(exclude_ids))
    return query.order_by(popularity.desc(), Pattern.created_at.desc()).limit(limit).all()
