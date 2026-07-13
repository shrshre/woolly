"""pgvector cosine-similarity search over the patterns table."""

import logging
from typing import Any, Literal

from sqlalchemy import Float, cast, text
from sqlalchemy.orm import Session

from app.db.models import Pattern
from app.search.filters import DIFFICULTY_RANGES, DifficultyTier
from app.services.embedding_service import embed_text

logger = logging.getLogger(__name__)

# IVFFlat is approximate; probe more lists as the corpus grows past ~500 rows.
IVFFLAT_PROBES = 10


def pattern_to_result(
    *,
    ravelry_id: int,
    name: str,
    designer: str | None,
    ravelry_url: str,
    image_url: str | None,
    is_free: bool,
    description: str | None,
    difficulty: str | None,
    similarity_score: float,
    semantic_score: float | None = None,
    keyword_score: float | None = None,
    combined_score: float | None = None,
) -> dict[str, Any]:
    """Serialize a pattern row to the shared API result shape."""
    return {
        "id": ravelry_id,
        "name": name,
        "designer": designer,
        "permalink": None,
        "ravelry_url": ravelry_url,
        "photo_url": image_url,
        "free": is_free,
        "description": description,
        "difficulty": difficulty,
        "similarity_score": similarity_score,
        "semantic_score": semantic_score if semantic_score is not None else similarity_score,
        "keyword_score": keyword_score if keyword_score is not None else 0.0,
        "combined_score": combined_score if combined_score is not None else similarity_score,
    }


def semantic_search(
    db: Session,
    query: str,
    limit: int = 10,
    craft: str | None = None,
    difficulty: DifficultyTier | None = None,
    free: bool | None = None,
    category: str | None = None,
) -> list[dict[str, Any]]:
    """Embed the query and return the most similar patterns.

    Filters are applied in SQL *before* the vector ranking, so the top-N
    results are the most similar patterns within the filtered set.
    """
    query_vector = embed_text(query)

    db.execute(text(f"SET LOCAL ivfflat.probes = {IVFFLAT_PROBES}"))

    distance = Pattern.embedding.cosine_distance(query_vector)
    q = db.query(Pattern, distance.label("distance")).filter(Pattern.embedding.isnot(None))

    if craft:
        q = q.filter(Pattern.craft.ilike(craft))
    if free is not None:
        q = q.filter(Pattern.is_free == free)
    if category:
        q = q.filter(Pattern.category.ilike(category))
    if difficulty:
        low, high = DIFFICULTY_RANGES[difficulty]
        numeric = cast(Pattern.difficulty, Float)
        q = q.filter(Pattern.difficulty.isnot(None), numeric > 0, numeric >= low, numeric < high)

    rows = q.order_by(distance).limit(limit).all()

    results = [
        pattern_to_result(
            ravelry_id=pattern.ravelry_id,
            name=pattern.name,
            designer=pattern.designer,
            ravelry_url=pattern.ravelry_url,
            image_url=pattern.image_url,
            is_free=pattern.is_free,
            description=pattern.description,
            difficulty=pattern.difficulty,
            similarity_score=round(1.0 - float(dist), 4),
        )
        for pattern, dist in rows
    ]

    logger.info("Semantic search for %r returned %d results.", query, len(results))
    return results
