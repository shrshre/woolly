"""Internal analytics endpoint.

Placeholder auth: gated by a shared secret (X-Admin-Token) until the app grows
real admin roles. An empty admin_api_token setting closes the endpoint to
everyone — it must never mean "open access".
"""

from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db.session import get_db

router = APIRouter(prefix="/admin", tags=["admin"])

# hybrid and semantic are the two paths of one search bar (semantic is the
# fallback when the keyword and designer legs match nothing).
SURFACE_SQL = """
    CASE
        WHEN search_type IN ('hybrid', 'semantic') THEN 'search'
        WHEN search_type = 'rag' THEN 'ask'
        ELSE search_type
    END
"""

EVENTS_CTE = f"""
    WITH ev AS (
        SELECT e.*,
               {SURFACE_SQL} AS surface,
               EXISTS (SELECT 1 FROM result_interactions r
                       WHERE r.search_event_id = e.id AND r.action = 'save') AS saved,
               EXISTS (SELECT 1 FROM result_interactions r
                       WHERE r.search_event_id = e.id AND r.action = 'ravelry_click') AS clicked
        FROM search_events e
        WHERE e.created_at >= :since
    )
"""

# Latency, cache, zero-result, and engagement rates are over requests that
# succeeded; failures are counted on their own so an outage can't look fast.
SURFACE_SQL_QUERY = EVENTS_CTE + """
    SELECT surface,
           COUNT(*) AS requests,
           COUNT(*) FILTER (WHERE error IS NOT NULL) AS errors,
           COUNT(*) FILTER (WHERE error IS NULL AND fallbacks <> '[]'::jsonb) AS degraded,
           AVG(cache_hit::int) FILTER (WHERE error IS NULL) AS cache_hit_rate,
           AVG((result_count = 0)::int) FILTER (WHERE error IS NULL) AS zero_result_rate,
           AVG(saved::int) FILTER (WHERE error IS NULL) AS save_rate,
           AVG(clicked::int) FILTER (WHERE error IS NULL) AS click_rate,
           AVG((search_type = 'semantic')::int) FILTER (WHERE error IS NULL) AS semantic_fallback_rate,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms) FILTER (WHERE error IS NULL) AS p50,
           percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms) FILTER (WHERE error IS NULL) AS p95,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms)
               FILTER (WHERE error IS NULL AND NOT cache_hit) AS uncached_p50,
           percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms)
               FILTER (WHERE error IS NULL AND NOT cache_hit) AS uncached_p95
    FROM ev
    GROUP BY surface
"""

# Cache hits only time the Redis lookup, so stages are over cache misses.
STAGE_SQL_QUERY = EVENTS_CTE + """
    SELECT surface,
           s.key AS stage,
           COUNT(*) AS n,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY s.value::numeric) AS p50,
           percentile_cont(0.95) WITHIN GROUP (ORDER BY s.value::numeric) AS p95
    FROM ev, jsonb_each_text(ev.stage_ms) AS s
    WHERE error IS NULL AND NOT cache_hit
    GROUP BY surface, s.key
"""

FALLBACK_SQL_QUERY = EVENTS_CTE + """
    SELECT surface, f AS name, COUNT(*) AS n
    FROM ev, jsonb_array_elements_text(ev.fallbacks) AS f
    GROUP BY surface, f
"""

ERROR_SQL_QUERY = EVENTS_CTE + """
    SELECT surface, error AS name, COUNT(*) AS n
    FROM ev
    WHERE error IS NOT NULL
    GROUP BY surface, error
"""

TOP_QUERIES_SQL = EVENTS_CTE + """
    SELECT lower(query) AS q, COUNT(*) AS n
    FROM ev
    WHERE surface <> 'visual' AND error IS NULL {extra}
    GROUP BY lower(query)
    ORDER BY COUNT(*) DESC, lower(query)
    LIMIT 10
"""


def require_admin_token(
    x_admin_token: str | None = Header(None),
    settings: Settings = Depends(get_settings),
) -> None:
    token = settings.admin_api_token
    if not token or x_admin_token != token:
        raise HTTPException(status_code=403, detail="Forbidden.")


def window_start(days: int, today: date) -> datetime:
    """Midnight UTC at the start of a window of ``days`` calendar days ending today."""
    return datetime.combine(today - timedelta(days=days - 1), time.min)


def _rate(value: Any) -> float | None:
    return None if value is None else round(float(value), 4)


def _ms(value: Any) -> int | None:
    return None if value is None else round(float(value))


def shape_report(
    surfaces: list[dict[str, Any]],
    stages: list[dict[str, Any]],
    fallbacks: list[dict[str, Any]],
    errors: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """One block per surface (search / ask / visual) from the aggregate rows."""
    report: dict[str, dict[str, Any]] = {}
    for row in surfaces:
        block = {
            "requests": int(row["requests"]),
            "errors": int(row["errors"]),
            "error_rate": round(int(row["errors"]) / int(row["requests"]), 4) if row["requests"] else 0.0,
            "degraded": int(row["degraded"]),
            "cache_hit_rate": _rate(row["cache_hit_rate"]),
            "zero_result_rate": _rate(row["zero_result_rate"]),
            "save_rate": _rate(row["save_rate"]),
            "click_rate": _rate(row["click_rate"]),
            "latency_ms": {"p50": _ms(row["p50"]), "p95": _ms(row["p95"])},
            "uncached_latency_ms": {"p50": _ms(row["uncached_p50"]), "p95": _ms(row["uncached_p95"])},
            "stages_ms": {},
            "slowest_stage": None,
            "fallbacks": {},
            "errors_by_kind": {},
        }
        if row["surface"] == "search":
            block["semantic_fallback_rate"] = _rate(row["semantic_fallback_rate"])
        report[row["surface"]] = block

    for row in stages:
        if row["surface"] in report:
            report[row["surface"]]["stages_ms"][row["stage"]] = {
                "n": int(row["n"]),
                "p50": _ms(row["p50"]),
                "p95": _ms(row["p95"]),
            }
    for block in report.values():
        if block["stages_ms"]:
            block["slowest_stage"] = max(block["stages_ms"], key=lambda s: block["stages_ms"][s]["p95"])

    for rows, key in ((fallbacks, "fallbacks"), (errors, "errors_by_kind")):
        for row in rows:
            if row["surface"] in report:
                report[row["surface"]][key][row["name"]] = int(row["n"])
    return report


@router.get("/analytics")
async def analytics(
    days: int = Query(1, ge=1, le=90, description="Calendar days (UTC) ending today; 1 = today"),
    _: None = Depends(require_admin_token),
    db: Session = Depends(get_db),
) -> dict:
    """Request metrics over a window of search_events, per surface.

    Answers "p95 of search vs Ask", "zero-result rate this week", and "is
    rerank the slow stage" (``stages_ms`` and ``slowest_stage``, over cache
    misses).
    """
    since = window_start(days, datetime.now(timezone.utc).date())
    params = {"since": since}

    def rows(sql: str) -> list[dict[str, Any]]:
        return [dict(r) for r in db.execute(text(sql), params).mappings().all()]

    report = shape_report(
        rows(SURFACE_SQL_QUERY), rows(STAGE_SQL_QUERY), rows(FALLBACK_SQL_QUERY), rows(ERROR_SQL_QUERY)
    )
    return {
        "window": {"days": days, "since": since.isoformat() + "Z"},
        "surfaces": report,
        "top_queries": [r["q"] for r in rows(TOP_QUERIES_SQL.format(extra=""))],
        "zero_result_queries": [r["q"] for r in rows(TOP_QUERIES_SQL.format(extra="AND result_count = 0"))],
    }
