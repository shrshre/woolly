"""Pattern seeding pipeline: fetch from Ravelry, embed, upsert.

Shared by the manual CLI (scripts/seed_patterns.py) and the 24h background
scheduler (app/scheduler.py). Every run is logged to the seed_runs table and
ends by clearing the Redis search caches so new patterns are immediately
discoverable.

Idempotent: upserts are keyed on ravelry_id, so re-running never duplicates
patterns.
"""

import logging
import re
import time
from datetime import datetime
from typing import Any

import httpx

from app.cache.redis_client import clear_search_caches
from app.config import get_settings
from app.db.models import Pattern, SeedRun
from app.db.session import get_sessionmaker
from app.services.embedding_service import build_pattern_text, embed_text, get_model

logger = logging.getLogger(__name__)

# All major Ravelry categories (PRD week 3, section 3.1)
SEED_CATEGORIES = [
    "sweater", "cardigan", "pullover", "vest", "shawl", "wrap",
    "hat", "mittens", "gloves", "socks", "scarf", "cowl",
    "baby", "children", "toys", "home", "kitchen", "bag",
    "blanket", "afghan", "amigurumi", "dishcloth", "accessories",
]

# Sort orders that surface the most popular patterns per category
SEED_SORTS = ["best", "projects", "rating"]

PAGE_SIZE = 100
SLEEP_BETWEEN_CALLS_SECONDS = 0.5
LOG_EVERY = 100


def strip_html(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"<[^>]+>", " ", text).strip()


def build_seed_queries(incremental: bool = False) -> list[dict[str, Any]]:
    """Build the list of Ravelry search param sets to seed from.

    Full mode: each category is crossed with popularity sorts, split between
    knitting and crochet, plus an unfiltered "best match" pass that naturally
    mixes free and paid patterns (~90+ queries total).

    Incremental mode: newest patterns per category (sort=date) so scheduled
    runs only pick up patterns recently added to Ravelry.
    """
    queries: list[dict[str, Any]] = []
    if incremental:
        for category in SEED_CATEGORIES:
            queries.append({"query": category, "sort": "date"})
        return queries

    for category in SEED_CATEGORIES:
        queries.append({"query": category, "sort": "best"})
        for sort in SEED_SORTS[1:]:
            queries.append({"query": category, "sort": sort, "craft": "knitting"})
            queries.append({"query": category, "sort": sort, "craft": "crochet"})
    return queries


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


def collect_pattern_ids(
    client: httpx.Client,
    base_url: str,
    limit: int,
    skip_ids: set[int],
    incremental: bool = False,
) -> list[int]:
    """Gather up to `limit` unique pattern ids not already in `skip_ids`."""
    queries = build_seed_queries(incremental=incremental)
    ids: list[int] = []
    seen: set[int] = set(skip_ids)
    per_query = max(limit // len(queries) + 1, PAGE_SIZE)

    for query_params in queries:
        if len(ids) >= limit:
            break
        page = 1
        fetched_for_query = 0
        while fetched_for_query < per_query and len(ids) < limit:
            payload = fetch_json(
                client,
                f"{base_url}/patterns/search.json",
                params={**query_params, "page_size": PAGE_SIZE, "page": page},
            )
            time.sleep(SLEEP_BETWEEN_CALLS_SECONDS)
            if payload is None:
                break
            patterns = payload.get("patterns", [])
            if not patterns:
                break
            new_on_page = 0
            for raw in patterns:
                pid = raw.get("id")
                if pid and pid not in seen:
                    seen.add(pid)
                    ids.append(pid)
                    fetched_for_query += 1
                    new_on_page += 1
            # Incremental runs walk newest-first; once a whole page is
            # already known, everything older is known too.
            if incremental and new_on_page == 0:
                break
            page += 1
        logger.info("Collected %d new ids so far (params: %r)", len(ids), query_params)

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


def _pattern_to_dict(pattern: Pattern) -> dict[str, Any]:
    return {
        "name": pattern.name,
        "description": pattern.description,
        "tags": pattern.tags,
        "craft": pattern.craft,
        "difficulty": pattern.difficulty,
        "category": pattern.category,
        "raw_data": pattern.raw_data,
    }


def re_embed_existing(session) -> int:
    """Recompute embeddings for every pattern already in the DB.

    Uses the stored raw_data — no Ravelry API calls needed. Run this after
    changing build_pattern_text so old and new patterns embed consistently.
    """
    updated = 0
    patterns = session.query(Pattern).all()
    logger.info("Re-embedding %d existing patterns...", len(patterns))
    for pattern in patterns:
        pattern.embedding = embed_text(build_pattern_text(_pattern_to_dict(pattern)))
        updated += 1
        if updated % LOG_EVERY == 0:
            session.commit()
            logger.info("Re-embedded %d/%d...", updated, len(patterns))
    session.commit()
    logger.info("Re-embedded %d patterns.", updated)
    return updated


def run_seed(
    limit: int,
    re_embed: bool = False,
    incremental: bool = False,
) -> dict[str, Any]:
    """Execute one seed run and log it to the seed_runs table.

    Args:
        limit: max number of NEW patterns to fetch from Ravelry.
        re_embed: also recompute embeddings for all existing patterns.
        incremental: only look for patterns recently added to Ravelry
            (used by the 24h scheduler).

    Returns a summary dict: {added, updated, status, seed_run_id}.
    """
    settings = get_settings()
    if not settings.ravelry_username or not settings.ravelry_password:
        raise RuntimeError("RAVELRY_USERNAME / RAVELRY_PASSWORD are not set.")

    get_model()  # load embedding model up front

    session = get_sessionmaker()()
    run = SeedRun(status="running")
    session.add(run)
    session.commit()

    added = 0
    updated = 0
    try:
        if re_embed:
            updated += re_embed_existing(session)

        existing_ids = {
            row[0]
            for row in session.query(Pattern.ravelry_id)
            .filter(Pattern.embedding.isnot(None))
            .all()
        }
        logger.info("%d patterns already embedded; collecting up to %d new ones.", len(existing_ids), limit)

        with httpx.Client(
            auth=(settings.ravelry_username, settings.ravelry_password), timeout=15.0
        ) as client:
            base_url = settings.ravelry_api_base_url.rstrip("/")
            ids = collect_pattern_ids(client, base_url, limit, skip_ids=existing_ids, incremental=incremental)
            logger.info("Collected %d new pattern ids. Fetching details and embedding...", len(ids))

            processed = 0
            for pid in ids:
                detail = fetch_json(client, f"{base_url}/patterns/{pid}.json")
                time.sleep(SLEEP_BETWEEN_CALLS_SECONDS)
                if detail is None:
                    continue

                fields = extract_fields(detail)
                if fields is None:
                    continue

                fields["embedding"] = embed_text(build_pattern_text(fields))

                existing = (
                    session.query(Pattern)
                    .filter(Pattern.ravelry_id == fields["ravelry_id"])
                    .one_or_none()
                )
                if existing:
                    for key, value in fields.items():
                        setattr(existing, key, value)
                    updated += 1
                else:
                    session.add(Pattern(**fields))
                    added += 1
                session.commit()

                processed += 1
                if processed % LOG_EVERY == 0:
                    logger.info("Processed %d/%d...", processed, len(ids))

        run.status = "completed"
    except Exception:
        logger.exception("Seed run %d failed.", run.id)
        run.status = "failed"
        raise
    finally:
        run.patterns_added = added
        run.patterns_updated = updated
        run.finished_at = datetime.utcnow()
        session.commit()
        session.close()
        cleared = clear_search_caches()
        logger.info(
            "Seed run %d %s: %d added, %d updated, %d cache entries cleared.",
            run.id, run.status, added, updated, cleared,
        )

    return {"added": added, "updated": updated, "status": run.status, "seed_run_id": run.id}
