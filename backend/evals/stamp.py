"""Run metadata, so two scoreboards can be compared honestly.

A score without the code version, corpus size, models, and dataset hash
behind it is not comparable to anything.
"""

import hashlib
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


def git_revision() -> dict[str, Any]:
    """GIT_SHA wins (the container has no .git); otherwise ask git."""
    sha = os.environ.get("GIT_SHA")
    if sha:
        return {"sha": sha, "dirty": None}
    root = Path(__file__).resolve().parents[2]
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=root, capture_output=True, text=True, check=True
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True, check=True
            ).stdout.strip()
        )
    except (OSError, subprocess.CalledProcessError):
        return {"sha": "unknown", "dirty": None}
    return {"sha": sha, "dirty": dirty}


def corpus_stats(db: Session) -> dict[str, int]:
    row = db.execute(
        text(
            "SELECT COUNT(*) AS patterns, COUNT(embedding) AS text_embedded, "
            "COUNT(image_embedding) AS image_embedded FROM patterns"
        )
    ).one()
    return {"patterns": row.patterns, "text_embedded": row.text_embedded, "image_embedded": row.image_embedded}


def pipeline_config() -> dict[str, Any]:
    from app.config import get_settings
    from app.search import conversational, hybrid_search, pipeline
    from app.services import clip_service, embedding_service, reranking_service

    return {
        "embedding_model": embedding_service.MODEL_NAME,
        "reranker_model": reranking_service.MODEL_NAME,
        "clip_model": clip_service.MODEL_NAME,
        "llm_model": get_settings().openai_model,
        "hybrid_weights": {
            "semantic": hybrid_search.SEMANTIC_WEIGHT,
            "keyword": hybrid_search.KEYWORD_WEIGHT,
            "designer": hybrid_search.DESIGNER_WEIGHT,
        },
        "rerank_pool": pipeline.RERANK_POOL,
        "max_results": pipeline.MAX_RESULTS,
        "min_rerank_score": reranking_service.MIN_RERANK_SCORE,
        "ask_cited_limit": conversational.CITED_LIMIT,
    }


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def now_utc() -> datetime:
    return datetime.now(UTC)
