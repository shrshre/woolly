"""Local embedding service using all-MiniLM-L6-v2 (384-dim vectors).

The model is loaded once (singleton) — loading takes ~3-5s, so it happens at
application startup, never per request. Like the Ravelry client, this sits
behind small module-level functions so the model could be swapped later.
"""

import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)

MODEL_NAME = "all-MiniLM-L6-v2"

_model = None
_model_lock = threading.Lock()


def get_model():
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                from sentence_transformers import SentenceTransformer

                logger.info("Loading embedding model %s ...", MODEL_NAME)
                _model = SentenceTransformer(MODEL_NAME)
                logger.info("Embedding model loaded.")
    return _model


def embed_text(text: str) -> list[float]:
    """Return a 384-dimensional embedding for the given text."""
    vector = get_model().encode(text, normalize_embeddings=True)
    return vector.tolist()


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed several texts in one batched model call."""
    vectors = get_model().encode(texts, normalize_embeddings=True)
    return [vector.tolist() for vector in vectors]


def yarn_weight_from_raw(raw: dict[str, Any]) -> str:
    yarn_weight = raw.get("yarn_weight") or {}
    return yarn_weight.get("name") or ""


def needle_sizes_from_raw(raw: dict[str, Any]) -> str:
    sizes = raw.get("pattern_needle_sizes") or []
    return " ".join(size.get("name", "").strip() for size in sizes if size.get("name"))


def build_pattern_text(pattern: dict[str, Any]) -> str:
    """Build the text used for embedding a pattern.

    Combines name, designer, and description, and tags with craft,
    difficulty, category, yarn weight, and needle sizes so queries like
    "worsted weight beginner hat" — or a designer's name — match on more
    than just the free-text description.
    """
    raw = pattern.get("raw_data") or {}
    parts = [
        pattern.get("name") or "",
        pattern.get("designer") or "",
        pattern.get("description") or "",
        " ".join(pattern.get("tags") or []),
        pattern.get("craft") or "",
        pattern.get("difficulty") or "",
        pattern.get("category") or "",
        pattern.get("yarn_weight") or yarn_weight_from_raw(raw),
        pattern.get("needle_size") or needle_sizes_from_raw(raw),
    ]
    return " ".join(part for part in parts if part).strip()
