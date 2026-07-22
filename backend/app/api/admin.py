"""Internal analytics endpoint.

Placeholder auth: gated by a shared secret (X-Admin-Token) until the app grows
real admin roles. An empty admin_api_token setting closes the endpoint to
everyone — it must never mean "open access".
"""

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db.session import get_db

router = APIRouter(prefix="/admin", tags=["admin"])


def require_admin_token(
    x_admin_token: str | None = Header(None),
    settings: Settings = Depends(get_settings),
) -> None:
    token = settings.admin_api_token
    if not token or x_admin_token != token:
        raise HTTPException(status_code=403, detail="Forbidden.")


@router.get("/analytics")
async def analytics(
    _: None = Depends(require_admin_token),
    db: Session = Depends(get_db),
) -> dict:
    """Search-quality metrics over today's search_events (UTC, by created_at)."""
    row = db.execute(
        text(
            """
            SELECT
                COUNT(*) AS queries_today,
                COALESCE(AVG(cache_hit::int), 0) AS cache_hit_rate,
                COALESCE(AVG(latency_ms), 0) AS avg_latency_ms,
                COALESCE(AVG((result_count = 0)::int), 0) AS zero_result_rate
            FROM search_events
            WHERE created_at::date = CURRENT_DATE
            """
        )
    ).one()

    top_queries = [
        r[0]
        for r in db.execute(
            text(
                """
                SELECT lower(query) AS q
                FROM search_events
                WHERE created_at::date = CURRENT_DATE
                GROUP BY lower(query)
                ORDER BY COUNT(*) DESC
                LIMIT 10
                """
            )
        ).all()
    ]

    zero_result_queries = [
        r[0]
        for r in db.execute(
            text(
                """
                SELECT lower(query) AS q
                FROM search_events
                WHERE created_at::date = CURRENT_DATE AND result_count = 0
                GROUP BY lower(query)
                ORDER BY COUNT(*) DESC
                LIMIT 10
                """
            )
        ).all()
    ]

    return {
        "queries_today": int(row.queries_today),
        "cache_hit_rate": round(float(row.cache_hit_rate), 4),
        "avg_latency_ms": round(float(row.avg_latency_ms), 1),
        "zero_result_rate": round(float(row.zero_result_rate), 4),
        "top_queries": top_queries,
        "zero_result_queries": zero_result_queries,
    }
