"""Backfill CLIP image embeddings for visual pattern search.

Usage (inside the backend container):
    docker-compose exec backend python scripts/embed_images.py
    docker-compose exec backend python scripts/embed_images.py --limit 500

Idempotent: only patterns with an image_url and no image_embedding are
processed, so re-running continues where the last run stopped.
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.init_db import init_db  # noqa: E402
from app.db.session import get_sessionmaker  # noqa: E402
from app.services.clip_service import embed_missing_images  # noqa: E402

logger = logging.getLogger("embed_images")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Backfill CLIP image embeddings.")
    parser.add_argument("--limit", type=int, default=None, help="Max patterns to embed this run (default: all)")
    args = parser.parse_args()

    init_db()
    session = get_sessionmaker()()
    try:
        summary = embed_missing_images(session, limit=args.limit)
    finally:
        session.close()
    logger.info(
        "Done: %d embedded, %d failed, %d remaining.",
        summary["embedded"], summary["failed"], summary["remaining"],
    )


if __name__ == "__main__":
    main()
