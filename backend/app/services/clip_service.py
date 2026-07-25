"""CLIP image embedding service for visual pattern search (512-dim vectors).

clip-ViT-B-32 embeds images and text into a shared space; here it is used
image-to-image: pattern photos are embedded offline (scripts/embed_images.py)
and an uploaded photo is embedded at query time, ranked by cosine similarity.

Loaded lazily as a singleton — unlike the text models it is NOT loaded at app
startup, since it costs ~600MB RAM and only visual searches need it.
"""

import io
import logging
import threading
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

MODEL_NAME = "clip-ViT-B-32"

# Backfill politeness: Ravelry CDN download pacing and encode batch size.
DOWNLOAD_TIMEOUT_SECONDS = 10.0
SLEEP_BETWEEN_DOWNLOADS_SECONDS = 0.2
ENCODE_BATCH_SIZE = 16
LOG_EVERY = 100

_model = None
_model_lock = threading.Lock()


def get_clip_model():
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                from sentence_transformers import SentenceTransformer

                logger.info("Loading CLIP model %s ...", MODEL_NAME)
                _model = SentenceTransformer(MODEL_NAME)
                logger.info("CLIP model loaded.")
    return _model


def embed_image_bytes(data: bytes) -> list[float]:
    """Return a 512-dim normalized CLIP embedding for raw image bytes.

    Raises ValueError if the bytes are not a decodable image.
    """
    from PIL import Image, UnidentifiedImageError

    try:
        image = Image.open(io.BytesIO(data)).convert("RGB")
    except UnidentifiedImageError as exc:
        raise ValueError("Could not decode image.") from exc
    vector = get_clip_model().encode(image, normalize_embeddings=True)
    return vector.tolist()


def embed_missing_images(session, limit: int | None = None) -> dict[str, Any]:
    """Backfill image_embedding for patterns that have a photo but no vector.

    Downloads each pattern's image_url (transiently, never stored), encodes in
    batches, and commits periodically. Failures on individual images are logged
    and skipped so one dead URL never stalls the run.

    Returns {"embedded": int, "failed": int, "remaining": int}.
    """
    from PIL import Image, UnidentifiedImageError

    from app.db.models import Pattern

    query = (
        session.query(Pattern)
        .filter(Pattern.image_url.isnot(None), Pattern.image_embedding.is_(None))
        .order_by(Pattern.id)
    )
    if limit:
        query = query.limit(limit)
    patterns = query.all()

    if not patterns:
        return {"embedded": 0, "failed": 0, "remaining": 0}

    model = get_clip_model()
    logger.info("Backfilling image embeddings for %d patterns...", len(patterns))

    embedded = 0
    failed = 0
    batch: list[tuple[Pattern, Any]] = []

    def flush_batch() -> None:
        nonlocal embedded
        if not batch:
            return
        images = [img for _, img in batch]
        vectors = model.encode(images, normalize_embeddings=True, batch_size=ENCODE_BATCH_SIZE)
        for (pattern, _), vector in zip(batch, vectors):
            pattern.image_embedding = vector.tolist()
        embedded += len(batch)
        batch.clear()
        session.commit()

    with httpx.Client(timeout=DOWNLOAD_TIMEOUT_SECONDS, follow_redirects=True) as client:
        for pattern in patterns:
            try:
                response = client.get(pattern.image_url)
                time.sleep(SLEEP_BETWEEN_DOWNLOADS_SECONDS)
                if response.status_code != 200:
                    raise ValueError(f"HTTP {response.status_code}")
                image = Image.open(io.BytesIO(response.content)).convert("RGB")
            except (httpx.HTTPError, UnidentifiedImageError, ValueError, OSError) as exc:
                failed += 1
                logger.warning("Skipping image for pattern %d (%s)", pattern.id, exc)
                continue

            batch.append((pattern, image))
            if len(batch) >= ENCODE_BATCH_SIZE:
                flush_batch()
            if (embedded + failed) % LOG_EVERY == 0:
                logger.info("Image backfill progress: %d embedded, %d failed...", embedded, failed)

    flush_batch()

    remaining = (
        session.query(Pattern)
        .filter(Pattern.image_url.isnot(None), Pattern.image_embedding.is_(None))
        .count()
    )
    logger.info("Image backfill done: %d embedded, %d failed, %d remaining.", embedded, failed, remaining)
    return {"embedded": embedded, "failed": failed, "remaining": remaining}
