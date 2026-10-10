"""CLIP image-to-image nearest neighbours over pattern photos."""

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


def nearest_patterns(db: Session, query_vector: list[float], limit: int) -> list[dict[str, Any]]:
    """Patterns whose image_embedding is closest to ``query_vector``.

    Always the top-N by cosine similarity, with no score threshold. Rows carry
    ravelry_id, internal_id, the card fields, and ``similarity``.
    """
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
    return [dict(row) for row in rows]
