"""Seed the patterns table from Ravelry and generate embeddings.

Usage (inside the backend container):
    docker-compose exec backend python scripts/seed_patterns.py --limit 5000
    docker-compose exec backend python scripts/seed_patterns.py --limit 5000 --re-embed
    docker-compose exec backend python scripts/seed_patterns.py --incremental

Safe to re-run: upserts are keyed on ravelry_id and patterns that already
have embeddings are skipped during collection. Use --re-embed after changing
build_pattern_text to refresh existing embeddings from stored raw_data.

Every run is logged to the seed_runs table, and the Redis search caches are
cleared afterward. The same pipeline (app.services.seeding) also powers the
24-hour background scheduler.
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.init_db import init_db  # noqa: E402
from app.services.seeding import run_seed  # noqa: E402

logger = logging.getLogger("seed_patterns")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Seed patterns from Ravelry with embeddings.")
    parser.add_argument("--limit", type=int, default=5000, help="Max new patterns to seed (default 5000)")
    parser.add_argument(
        "--re-embed",
        action="store_true",
        help="Recompute embeddings for all existing patterns (after build_pattern_text changes)",
    )
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="Only fetch patterns recently added to Ravelry (what the scheduler runs nightly)",
    )
    args = parser.parse_args()

    logger.info("Initializing database (idempotent)...")
    init_db()

    summary = run_seed(limit=args.limit, re_embed=args.re_embed, incremental=args.incremental)
    logger.info(
        "Done. Seed run #%d %s: %d added, %d updated.",
        summary["seed_run_id"], summary["status"], summary["added"], summary["updated"],
    )


if __name__ == "__main__":
    main()
