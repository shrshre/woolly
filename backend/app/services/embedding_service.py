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


def build_pattern_text(pattern: dict[str, Any]) -> str:
    """Concatenate name + description + tags into a single string for embedding."""
    parts = [
        pattern.get("name") or "",
        pattern.get("description") or "",
        " ".join(pattern.get("tags") or []),
    ]
    return " ".join(part for part in parts if part).strip()
