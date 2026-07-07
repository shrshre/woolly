"""pgvector cosine-similarity search over the patterns table."""

import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.models import Pattern
from app.services.embedding_service import embed_text

logger = logging.getLogger(__name__)

# IVFFlat is approximate: with lists=100 and a small seed set (~500 rows),
# the default of probing 1 list can return fewer than `limit` results.
IVFFLAT_PROBES = 10


def semantic_search(db: Session, query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Embed the query and return the most similar patterns.

    Each result dict matches the Week 1 PatternSummary shape, plus a
    similarity_score field (0-1, higher is better).
    """
    query_vector = embed_text(query)

    db.execute(text(f"SET LOCAL ivfflat.probes = {IVFFLAT_PROBES}"))

    # cosine_distance = 1 - cosine_similarity; ORDER BY distance == most similar first
    distance = Pattern.embedding.cosine_distance(query_vector)
    rows = (
        db.query(Pattern, distance.label("distance"))
        .filter(Pattern.embedding.isnot(None))
        .order_by(distance)
        .limit(limit)
        .all()
    )

    results = []
    for pattern, dist in rows:
        results.append(
            {
                "id": pattern.ravelry_id,
                "name": pattern.name,
                "designer": pattern.designer,
                "permalink": None,
                "ravelry_url": pattern.ravelry_url,
                "photo_url": pattern.image_url,
                "free": pattern.is_free,
                "description": pattern.description,
                "difficulty": pattern.difficulty,
                "similarity_score": round(1.0 - float(dist), 4),
            }
        )

    logger.info("Semantic search for %r returned %d results.", query, len(results))
    return results
