"""Idempotent database initialization: enable pgvector, create tables and index.

Run manually with:  python -m app.db.init_db
Also invoked at application startup.
"""

import logging

from sqlalchemy import text

from app.db.models import Base
from app.db.session import get_engine

logger = logging.getLogger(__name__)

IVFFLAT_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS patterns_embedding_idx
    ON patterns USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);
"""


def init_db() -> None:
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()

    Base.metadata.create_all(engine)

    with engine.connect() as conn:
        conn.execute(text(IVFFLAT_INDEX_SQL))
        # Lightweight migrations: create_all doesn't alter existing tables
        conn.execute(
            text(
                "ALTER TABLE projects "
                "ADD COLUMN IF NOT EXISTS stitch_count INTEGER NOT NULL DEFAULT 0, "
                "ADD COLUMN IF NOT EXISTS row_count INTEGER NOT NULL DEFAULT 0"
            )
        )
        conn.commit()

    logger.info("Database initialized: pgvector enabled, tables and index created.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    init_db()
