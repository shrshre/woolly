"""Woolly FastAPI entrypoint."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.admin import router as admin_router
from app.api.patterns import router as patterns_router
from app.api.projects import router as projects_router
from app.api.users import router as users_router
from app.auth.routes import router as auth_router
from app.config import get_settings
from app.db.init_db import init_db
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

app.include_router(patterns_router)
app.include_router(projects_router)
app.include_router(users_router)
app.include_router(auth_router)
app.include_router(admin_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
