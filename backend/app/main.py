"""Woolly FastAPI entrypoint."""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.admin import router as admin_router
from app.api.patterns import router as patterns_router
from app.api.projects import router as projects_router
from app.api.users import router as users_router
from app.auth.routes import router as auth_router
from app.cache.redis_client import get_redis
from app.config import get_settings
from app.db.init_db import init_db
from app.db.session import get_engine
from app.observability import TraceMiddleware
from app.scheduler import start_scheduler, stop_scheduler
from app.services.embedding_service import get_model

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        init_db()
    except Exception as exc:
        logger.warning("Database init failed (%s); semantic search will be unavailable.", exc)
    get_model()  # load the embedding model once at startup, not per request
    # Reranker loads lazily on the first search (saves ~500MB RAM at boot).
    start_scheduler()  # incremental re-seed every 24h
    yield
    stop_scheduler()


app = FastAPI(
    title="Woolly API",
    description="Crafting companion for fiber artists. Pattern data courtesy of the Ravelry API.",
    version="0.2.0",
    lifespan=lifespan,
    redirect_slashes=False,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(TraceMiddleware)

app.include_router(patterns_router)
app.include_router(projects_router)
app.include_router(users_router)
app.include_router(auth_router)
app.include_router(admin_router)


HEALTH_TIMEOUT_SECONDS = 2.0


def _ping_postgres() -> None:
    with get_engine().connect() as conn:
        conn.execute(text("SELECT 1"))


async def _check(probe) -> str:
    try:
        await asyncio.wait_for(probe(), HEALTH_TIMEOUT_SECONDS)
    except Exception as exc:  # timeout, refused connection, auth...
        logger.warning("Health check failed: %s", exc)
        return "down"
    return "ok"


@app.get("/health")
async def health(response: Response) -> dict[str, str]:
    """200 when Postgres and Redis both answer within the timeout, else 503.

    Search still serves with Redis down (every request is a cache miss), so a
    503 here means "degraded", not necessarily "unusable"; the body says which.
    """
    checks = {
        "postgres": await _check(lambda: run_in_threadpool(_ping_postgres)),
        "redis": await _check(lambda: get_redis().ping()),
    }
    healthy = all(state == "ok" for state in checks.values())
    if not healthy:
        response.status_code = 503
    return {"status": "ok" if healthy else "degraded", **checks}
