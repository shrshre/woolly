"""Database engine and session management."""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

_engine = None
_SessionLocal: sessionmaker | None = None


def _sqlalchemy_database_url(url: str) -> str:
    """Use the psycopg2 driver we ship in requirements.txt.

    Railway (and some Postgres templates) emit ``postgresql+psycopg://``, which
    needs psycopg v3. We install ``psycopg2-binary``, so coerce the URL.
    """
    if url.startswith("postgres://"):
        url = "postgresql://" + url.removeprefix("postgres://")
    if url.startswith("postgresql+psycopg://"):
        return "postgresql+psycopg2://" + url.removeprefix("postgresql+psycopg://")
    if url.startswith("postgresql://"):
        return "postgresql+psycopg2://" + url.removeprefix("postgresql://")
    return url


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(
            _sqlalchemy_database_url(get_settings().database_url),
            pool_pre_ping=True,
        )
    return _engine


def get_sessionmaker() -> sessionmaker:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)
    return _SessionLocal


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a database session."""
    session = get_sessionmaker()()
    try:
        yield session
    finally:
        session.close()
