"""Background scheduler: incremental pattern re-seeding every 24 hours.

Uses APScheduler's BackgroundScheduler (thread-based), which suits the sync
seeding pipeline — the job runs in a worker thread and never blocks the
event loop. Each run fetches only patterns recently added to Ravelry, logs
to the seed_runs table, and clears the Redis search caches (all handled
inside run_seed).
"""

import logging

from apscheduler.schedulers.background import BackgroundScheduler

from app.services.seeding import run_seed

logger = logging.getLogger(__name__)

RESEED_INTERVAL_HOURS = 24
INCREMENTAL_LIMIT = 500  # cap on new patterns per nightly run

_scheduler: BackgroundScheduler | None = None


def _incremental_seed_job() -> None:
    logger.info("Scheduled re-seed starting (incremental, limit=%d)...", INCREMENTAL_LIMIT)
    try:
        summary = run_seed(limit=INCREMENTAL_LIMIT, incremental=True)
        logger.info(
            "Scheduled re-seed finished: run #%d %s, %d added, %d updated.",
            summary["seed_run_id"], summary["status"], summary["added"], summary["updated"],
        )
    except Exception:
        logger.exception("Scheduled re-seed failed; will retry at next interval.")


def start_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler()
        _scheduler.add_job(
            _incremental_seed_job,
            trigger="interval",
            hours=RESEED_INTERVAL_HOURS,
            id="incremental_reseed",
            max_instances=1,  # never overlap two seed runs
            coalesce=True,
        )
        _scheduler.start()
        logger.info("Background scheduler started: incremental re-seed every %dh.", RESEED_INTERVAL_HOURS)
    return _scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("Background scheduler stopped.")
