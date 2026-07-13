"""Hybrid retrieval: pgvector semantic search + PostgreSQL full-text (BM25)
+ trigram matching on designer names."""

import logging
from typing import Any, Literal

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.search.filters import DifficultyTier, build_filter_clause
from app.search.semantic_search import IVFFLAT_PROBES, pattern_to_result, semantic_search
from app.services.embedding_service import embed_text

logger = logging.getLogger(__name__)

SEMANTIC_WEIGHT = 0.6
KEYWORD_WEIGHT = 0.25
DESIGNER_WEIGHT = 0.15
SEMANTIC_CANDIDATE_LIMIT = 100

# Minimum trigram similarity (0-1) between the space-stripped query and a
# space-stripped designer name for that designer's patterns to be pulled into
# the candidate pool. 0.4 catches "petite knit" -> "PetiteKnit" (1.0) and typos
# like "petit knit" (0.62) while excluding coincidental overlaps.
DESIGNER_SIMILARITY_THRESHOLD = 0.4


def _vector_literal(values: list[float]) -> str:
    return "[" + ",".join(str(v) for v in values) + "]"


def _stripped(query: str) -> str:
    """Lowercase and remove whitespace — 'Petite Knit' -> 'petiteknit'."""
    return "".join(query.lower().split())


def _leg_match_counts(
    db: Session,
    query: str,
    craft: str | None = None,
    difficulty: DifficultyTier | None = None,
    free: bool | None = None,
    category: str | None = None,
) -> tuple[int, int]:
    """Return (keyword_matches, designer_matches) for the fallback decision."""
    filter_clause, params = build_filter_clause(craft, difficulty, free, category)
    params["query"] = query
    params["designer_query"] = _stripped(query)
    params["designer_threshold"] = DESIGNER_SIMILARITY_THRESHOLD
    row = db.execute(
        text(
            f"""
            SELECT
                COUNT(*) FILTER (
                    WHERE search_vector @@ plainto_tsquery('english', :query)
                ) AS keyword_n,
                COUNT(*) FILTER (
                    WHERE designer IS NOT NULL
                      AND similarity(replace(lower(designer), ' ', ''), :designer_query)
                          > :designer_threshold
                ) AS designer_n
            FROM patterns
            WHERE embedding IS NOT NULL
              {filter_clause}
            """
        ),
        params,
    ).one()
    return int(row.keyword_n), int(row.designer_n)


def hybrid_search(
    db: Session,
    query: str,
    limit: int = 10,
    craft: str | None = None,
    difficulty: DifficultyTier | None = None,
    free: bool | None = None,
    category: str | None = None,
    semantic_weight: float = SEMANTIC_WEIGHT,
    keyword_weight: float = KEYWORD_WEIGHT,
    designer_weight: float = DESIGNER_WEIGHT,
) -> list[dict[str, Any]]:
    """Combine vector similarity, BM25 keyword ranking, and designer trigram
    matching into a single candidate pool.

    Each leg's raw scores are max-normalized to [0, 1] within that leg's
    candidate pool before weighting. For rows that appear in only some legs,
    the active weights are renormalized so a single strong signal is not
    structurally capped (e.g. a designer-only exact match is not stuck at
    0.15). Raw semantic/keyword scores are preserved in the output; the
    designer leg feeds recall and ranking but is not surfaced as a field.

    Falls back to pure semantic search only when both the keyword and designer
    legs are empty (niche natural-language queries where they add no signal).
    """
    keyword_n, designer_n = _leg_match_counts(db, query, craft, difficulty, free, category)
    if keyword_n == 0 and designer_n == 0:
        logger.info("Hybrid search for %r: no keyword/designer matches, semantic fallback.", query)
        return semantic_search(db, query, limit, craft, difficulty, free, category)

    filter_clause, params = build_filter_clause(craft, difficulty, free, category, prefix="p.")
    inner_filter = filter_clause.replace("p.", "")
    params.update(
        {
            "query": query,
            "designer_query": _stripped(query),
            "designer_threshold": DESIGNER_SIMILARITY_THRESHOLD,
            "query_embedding": _vector_literal(embed_text(query)),
            "semantic_weight": semantic_weight,
            "keyword_weight": keyword_weight,
            "designer_weight": designer_weight,
            "limit": limit,
        }
    )

    db.execute(text(f"SET LOCAL ivfflat.probes = {IVFFLAT_PROBES}"))

    rows = db.execute(
        text(
            f"""
            WITH semantic_raw AS (
                SELECT id,
                       1 - (embedding <=> CAST(:query_embedding AS vector)) AS semantic_score
                FROM patterns
                WHERE embedding IS NOT NULL
                {inner_filter}
                ORDER BY embedding <=> CAST(:query_embedding AS vector)
                LIMIT {SEMANTIC_CANDIDATE_LIMIT}
            ),
            semantic AS (
                SELECT id,
                       semantic_score,
                       CASE
                           WHEN MAX(semantic_score) OVER () > 0
                           THEN semantic_score / MAX(semantic_score) OVER ()
                           ELSE 1.0
                       END AS semantic_norm
                FROM semantic_raw
            ),
            keyword_raw AS (
                SELECT id,
                       ts_rank(search_vector, plainto_tsquery('english', :query)) AS keyword_score
                FROM patterns
                WHERE search_vector @@ plainto_tsquery('english', :query)
                {inner_filter}
            ),
            keyword AS (
                SELECT id,
                       keyword_score,
                       CASE
                           WHEN MAX(keyword_score) OVER () > 0
                           THEN keyword_score / MAX(keyword_score) OVER ()
                           ELSE 1.0
                       END AS keyword_norm
                FROM keyword_raw
            ),
            designer_raw AS (
                SELECT id,
                       similarity(replace(lower(designer), ' ', ''), :designer_query)
                           AS designer_score
                FROM patterns
                WHERE designer IS NOT NULL
                  AND similarity(replace(lower(designer), ' ', ''), :designer_query)
                      > :designer_threshold
                {inner_filter}
            ),
            designer AS (
                SELECT id,
                       CASE
                           WHEN MAX(designer_score) OVER () > 0
                           THEN designer_score / MAX(designer_score) OVER ()
                           ELSE 1.0
                       END AS designer_norm
                FROM designer_raw
            )
            SELECT p.id,
                   p.ravelry_id,
                   p.name,
                   p.designer,
                   p.description,
                   p.difficulty,
                   p.ravelry_url,
                   p.image_url,
                   p.is_free,
                   COALESCE(s.semantic_score, 0) AS semantic_score,
                   COALESCE(k.keyword_score, 0) AS keyword_score,
                   (
                       COALESCE(s.semantic_norm, 0) * :semantic_weight +
                       COALESCE(k.keyword_norm, 0) * :keyword_weight +
                       COALESCE(d.designer_norm, 0) * :designer_weight
                   ) / NULLIF(
                       (CASE WHEN s.id IS NOT NULL THEN :semantic_weight ELSE 0 END) +
                       (CASE WHEN k.id IS NOT NULL THEN :keyword_weight ELSE 0 END) +
                       (CASE WHEN d.id IS NOT NULL THEN :designer_weight ELSE 0 END),
                       0
                   ) AS combined_score
            FROM patterns p
            LEFT JOIN semantic s ON p.id = s.id
            LEFT JOIN keyword k ON p.id = k.id
            LEFT JOIN designer d ON p.id = d.id
            WHERE s.id IS NOT NULL OR k.id IS NOT NULL OR d.id IS NOT NULL
            ORDER BY combined_score DESC,
                     COALESCE(k.keyword_score, 0) DESC,
                     COALESCE(s.semantic_score, 0) DESC
            LIMIT :limit
            """
        ),
        params,
    ).mappings().all()

    results = [
        pattern_to_result(
            ravelry_id=row["ravelry_id"],
            name=row["name"],
            designer=row["designer"],
            ravelry_url=row["ravelry_url"],
            image_url=row["image_url"],
            is_free=row["is_free"],
            description=row["description"],
            difficulty=row["difficulty"],
            similarity_score=round(float(row["combined_score"]), 4),
            semantic_score=round(float(row["semantic_score"]), 4),
            keyword_score=round(float(row["keyword_score"]), 4),
            combined_score=round(float(row["combined_score"]), 4),
        )
        for row in rows
    ]

    logger.info("Hybrid search for %r returned %d results.", query, len(results))
    return results
