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

FULLTEXT_SEARCH_SQL = """
ALTER TABLE patterns ADD COLUMN IF NOT EXISTS search_vector tsvector;

UPDATE patterns SET search_vector = to_tsvector('english',
    coalesce(name, '') || ' ' ||
    coalesce(designer, '') || ' ' ||
    coalesce(description, '') || ' ' ||
    coalesce(array_to_string(tags, ' '), '')
)
WHERE search_vector IS NULL;

CREATE INDEX IF NOT EXISTS patterns_search_vector_idx
    ON patterns USING GIN (search_vector);

CREATE OR REPLACE FUNCTION update_search_vector()
RETURNS trigger AS $$
BEGIN
    NEW.search_vector := to_tsvector('english',
        coalesce(NEW.name, '') || ' ' ||
        coalesce(NEW.designer, '') || ' ' ||
        coalesce(NEW.description, '') || ' ' ||
        coalesce(array_to_string(NEW.tags, ' '), '')
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS patterns_search_vector_update ON patterns;
CREATE TRIGGER patterns_search_vector_update
    BEFORE INSERT OR UPDATE ON patterns
    FOR EACH ROW EXECUTE FUNCTION update_search_vector();
"""

# Trigram matching on designer names. Full-text search tokenizes a query like
# "petite knit" into ('petit' & 'knit'), which never matches the single lexeme
# 'petiteknit' — so brand-style designer names (PetiteKnit, KnitPicks) were
# unfindable. Trigram similarity on the space-stripped name fixes that and also
# tolerates typos.
DESIGNER_TRGM_SQL = """
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE INDEX IF NOT EXISTS patterns_designer_trgm_idx
    ON patterns USING GIN (designer gin_trgm_ops);
"""


def init_db() -> None:
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()

    Base.metadata.create_all(engine)

    with engine.connect() as conn:
        conn.execute(text(IVFFLAT_INDEX_SQL))
        conn.execute(text(FULLTEXT_SEARCH_SQL))
        conn.execute(text(DESIGNER_TRGM_SQL))
        # Lightweight migrations: create_all doesn't alter existing tables
        conn.execute(
            text(
                "ALTER TABLE projects "
                "ADD COLUMN IF NOT EXISTS stitch_count INTEGER NOT NULL DEFAULT 0, "
                "ADD COLUMN IF NOT EXISTS row_count INTEGER NOT NULL DEFAULT 0"
            )
        )
        # CLIP image embeddings for visual search (backfilled by scripts/embed_images.py)
        conn.execute(
            text("ALTER TABLE patterns ADD COLUMN IF NOT EXISTS image_embedding vector(512)")
        )
        conn.commit()

    logger.info("Database initialized: pgvector enabled, tables and index created.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    init_db()
