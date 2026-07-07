"""Seed the patterns table from Ravelry and generate embeddings.

Usage (inside the backend container):
    docker-compose exec backend python scripts/seed_patterns.py --limit 500

Safe to re-run: patterns that already have embeddings are skipped, and
upserts are keyed on ravelry_id.
"""

import argparse
import logging
import re
import sys
import time
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.db.init_db import init_db  # noqa: E402
from app.db.models import Pattern  # noqa: E402
from app.db.session import get_sessionmaker  # noqa: E402
from app.services.embedding_service import build_pattern_text, embed_text, get_model  # noqa: E402

logger = logging.getLogger("seed_patterns")

# Broad queries across crafts/categories so the seed set has variety
SEED_QUERIES = [
    "sweater", "hat", "shawl", "cardigan", "amigurumi",
    "blanket", "socks", "scarf", "mittens", "bag",
    "baby", "toy", "cowl", "lace", "colorwork",
]

PAGE_SIZE = 50
SLEEP_BETWEEN_CALLS_SECONDS = 0.3  # stay well under Ravelry rate limits
LOG_EVERY = 50


def strip_html(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"<[^>]+>", " ", text).strip()


def fetch_json(client: httpx.Client, url: str, params: dict | None = None) -> dict[str, Any] | None:
    """GET with basic rate-limit handling; returns None on non-retryable errors."""
    for attempt in range(3):
        try:
            response = client.get(url, params=params)
        except httpx.HTTPError as exc:
            logger.warning("Request to %s failed (%s); retrying...", url, exc)
            time.sleep(2**attempt)
            continue
        if response.status_code == 429:
            wait = 5 * (attempt + 1)
            logger.warning("Rate limited by Ravelry; sleeping %ss...", wait)
            time.sleep(wait)
            continue
        if response.status_code != 200:
            logger.warning("Unexpected %s from %s; skipping.", response.status_code, url)
            return None
        return response.json()
    logger.warning("Giving up on %s after retries.", url)
    return None


def collect_pattern_ids(client: httpx.Client, base_url: str, limit: int) -> list[int]:
    """Gather up to `limit` unique pattern ids across the seed queries."""
    ids: list[int] = []
    seen: set[int] = set()
    per_query = max(limit // len(SEED_QUERIES) + 1, PAGE_SIZE)

    for query in SEED_QUERIES:
        if len(ids) >= limit:
            break
        page = 1
        fetched_for_query = 0
        while fetched_for_query < per_query and len(ids) < limit:
            payload = fetch_json(
                client,
                f"{base_url}/patterns/search.json",
                params={"query": query, "page_size": PAGE_SIZE, "page": page},
            )
            time.sleep(SLEEP_BETWEEN_CALLS_SECONDS)
            if payload is None:
                break
            patterns = payload.get("patterns", [])
            if not patterns:
                break
            for raw in patterns:
                pid = raw.get("id")
                if pid and pid not in seen:
                    seen.add(pid)
                    ids.append(pid)
                    fetched_for_query += 1
            page += 1
        logger.info("Collected %d ids so far (query: %r)", len(ids), query)

    return ids[:limit]


def extract_fields(detail: dict[str, Any]) -> dict[str, Any] | None:
    """Map a Ravelry pattern detail payload to our patterns table columns."""
    pattern = detail.get("pattern") or {}
    ravelry_id = pattern.get("id")
    name = pattern.get("name")
    permalink = pattern.get("permalink")
    if not ravelry_id or not name or not permalink:
        return None

    categories = pattern.get("pattern_categories") or []
    attributes = pattern.get("pattern_attributes") or []
    first_photo = (pattern.get("photos") or [{}])[0]
    difficulty_avg = pattern.get("difficulty_average")

    tags = [attr.get("permalink") for attr in attributes if attr.get("permalink")]
    tags += [cat.get("name") for cat in categories if cat.get("name")]

    return {
        "ravelry_id": ravelry_id,
        "name": name,
        "designer": (pattern.get("pattern_author") or {}).get("name"),
        "description": strip_html(pattern.get("notes_html") or pattern.get("notes")),
        # Ravelry reports 0 when a pattern has no difficulty ratings yet
        "difficulty": str(round(difficulty_avg, 1)) if difficulty_avg else None,
        "craft": (pattern.get("craft") or {}).get("name"),
        "category": categories[0].get("name") if categories else None,
        "is_free": bool(pattern.get("free")),
        "ravelry_url": f"https://www.ravelry.com/patterns/library/{permalink}",
        "image_url": first_photo.get("small_url") or first_photo.get("square_url"),
        "tags": tags,
        "raw_data": pattern,
    }


def seed(limit: int) -> None:
    settings = get_settings()
    if not settings.ravelry_username or not settings.ravelry_password:
        logger.error("RAVELRY_USERNAME / RAVELRY_PASSWORD are not set. Aborting.")
        sys.exit(1)

    logger.info("Initializing database (idempotent)...")
    init_db()

    logger.info("Loading embedding model...")
    get_model()

    session = get_sessionmaker()()
    existing_ids = {
        row[0]
        for row in session.query(Pattern.ravelry_id).filter(Pattern.embedding.isnot(None)).all()
    }
    logger.info("%d patterns already embedded; they will be skipped.", len(existing_ids))

    with httpx.Client(
        auth=(settings.ravelry_username, settings.ravelry_password), timeout=15.0
    ) as client:
        base_url = settings.ravelry_api_base_url.rstrip("/")
        ids = collect_pattern_ids(client, base_url, limit)
        logger.info("Collected %d pattern ids. Fetching details and embedding...", len(ids))

        processed = 0
        skipped = 0
        for pid in ids:
            if pid in existing_ids:
                skipped += 1
                continue

            detail = fetch_json(client, f"{base_url}/patterns/{pid}.json")
            time.sleep(SLEEP_BETWEEN_CALLS_SECONDS)
            if detail is None:
                continue

            fields = extract_fields(detail)
            if fields is None:
                continue

            fields["embedding"] = embed_text(build_pattern_text(fields))

            existing = session.query(Pattern).filter(Pattern.ravelry_id == fields["ravelry_id"]).one_or_none()
            if existing:
                for key, value in fields.items():
                    setattr(existing, key, value)
            else:
                session.add(Pattern(**fields))
            session.commit()

            processed += 1
            if processed % LOG_EVERY == 0:
                logger.info("Processed %d/%d...", processed, len(ids))

    session.close()
    logger.info("Done. Processed %d new patterns, skipped %d already-embedded.", processed, skipped)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Seed patterns from Ravelry with embeddings.")
    parser.add_argument("--limit", type=int, default=500, help="Number of patterns to seed (default 500)")
    args = parser.parse_args()
    seed(args.limit)
