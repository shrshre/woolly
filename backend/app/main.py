"""Woolly FastAPI entrypoint."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.patterns import router as patterns_router
from app.config import get_settings
from app.db.init_db import init_db
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
    yield


app = FastAPI(
    title="Woolly API",
    description="Crafting companion for fiber artists. Pattern data courtesy of the Ravelry API.",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(patterns_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
