# 05 — PostgreSQL & SQLAlchemy

**The pantry: how Woolly stores pattern data permanently and how Python talks to it.**

---

## What is a relational database?

A **relational database** stores data in **tables** — think of spreadsheets with rows and
columns, but with superpowers:

- Data is stored permanently (survives server restarts)
- Rows in one table can *relate to* rows in another table (hence "relational")
- You can query data with SQL — a powerful language for filtering, sorting, joining tables
- Transactions ensure that either all of a set of operations succeed, or none do

**PostgreSQL** (often called "Postgres") is one of the most popular open-source relational
databases. It's battle-tested, feature-rich, and has the pgvector extension Woolly needs.

**Analogy:** if Redis is the warming shelf (fast, temporary), PostgreSQL is the walk-in
pantry (permanent, organized, authoritative). Everything that matters long-term lives here.

---

## The `patterns` table: Woolly's main storage

The schema (structure) of the `patterns` table:

```sql
CREATE TABLE IF NOT EXISTS patterns (
    id          SERIAL PRIMARY KEY,    -- auto-incremented internal ID
    ravelry_id  INTEGER UNIQUE NOT NULL, -- Ravelry's own ID for this pattern
    name        TEXT NOT NULL,
    designer    TEXT,                  -- nullable: some patterns have no designer
    description TEXT,                  -- HTML-stripped description
    difficulty  TEXT,                  -- Ravelry's difficulty average (0-10), e.g. "3.2"
    craft       TEXT,                  -- "knitting" or "crochet"
    category    TEXT,                  -- first pattern category
    is_free     BOOLEAN DEFAULT FALSE,
    ravelry_url TEXT NOT NULL,         -- link back to Ravelry
    image_url   TEXT,                  -- Ravelry CDN URL — never hosted permanently by Woolly
    embedding   vector(384),           -- text AI embedding (pgvector / MiniLM)
    image_embedding vector(512),       -- CLIP photo embedding (nullable until backfilled)
    search_vector tsvector,              -- full-text search index (BM25 leg)
    tags        TEXT[],                -- array of tag strings
    raw_data    JSONB,                 -- full Ravelry API response
    created_at  TIMESTAMP DEFAULT NOW(),
    updated_at  TIMESTAMP DEFAULT NOW()
);
```

### Why each column exists — know this cold

| Column | Why it exists |
|---|---|
| `id` | Internal primary key — every table needs one. Woolly uses this for joins |
| `ravelry_id` | Ravelry's identifier — UNIQUE constraint prevents storing the same pattern twice |
| `name` | The pattern name — shown in the UI |
| `designer` | "by Jane Smith" — shown in the card |
| `description` | Used in the embedding; shown in search results |
| `difficulty` | Ravelry stores 0-10 as a float string; Woolly maps it to Beginner/Intermediate/Advanced in the UI |
| `embedding` | The 384-float text embedding — powers the semantic / hybrid vector leg |
| `image_embedding` | The 512-float CLIP embedding — powers visual (photo) search; NULL until backfilled |
| `search_vector` | PostgreSQL `tsvector` for full-text (BM25) search — auto-updated by trigger |
| `tags` | Used in embedding text and full-text index |
| `craft` | "knitting" or "crochet" — active search filter |
| `category` | "Sweaters", "Hats", etc. — active search filter |
| `raw_data` | Full Ravelry payload — for future field extraction without re-querying Ravelry |
| `created_at/updated_at` | Audit trail — when was this stored/last changed |

**Key design decision:** `image_url` stores only the URL, not the actual image file.
Woolly may **transiently** download bytes during CLIP backfill to compute
`image_embedding`, then discards the file — it does not host a pattern image CDN. The UI
still displays photos by linking to Ravelry's CDN. Required by API terms and saves storage.

---

## User tables: auth and personal data

Beyond `patterns`, Woolly has tables for authenticated features:

### `users`
```sql
id SERIAL PRIMARY KEY, email TEXT UNIQUE, password_hash TEXT, created_at TIMESTAMP
```

### `saved_patterns` (join table)
```sql
user_id → users.id, pattern_id → patterns.id, PRIMARY KEY (user_id, pattern_id)
```
Many-to-many: a user can save many patterns; a pattern can be saved by many users.

### `projects`
```sql
user_id, pattern_id, yarn, needle_size, notes, progress_pct,
stitch_count, row_count, status (queue/active/hibernating/finished)
```
A project is a pattern the user is actively working on, with WIP metadata.

### `seed_runs`
```sql
started_at, finished_at, patterns_added, patterns_updated, status
```
Audit log for seeding runs (manual or scheduled). Useful for observability.

See `11-authentication-and-user-data.md` for how these connect to the API.

---

## Full-text search: the `search_vector` column

Woolly uses PostgreSQL's built-in full-text search for the keyword leg of hybrid retrieval.

Set up in `init_db.py`:
- Column: `search_vector tsvector`
- Populated from: name + designer + description + tags
- Index: GIN index for fast lookups
- Trigger: auto-updates `search_vector` on INSERT/UPDATE

```sql
-- Keyword search in hybrid_search.py:
WHERE search_vector @@ plainto_tsquery('english', :query)
ORDER BY ts_rank(search_vector, plainto_tsquery('english', :query)) DESC
```

**Why not Elasticsearch?** At Woolly's scale, PostgreSQL full-text search with a GIN index
is fast enough and keeps everything in one database. No extra infrastructure.

---

## Designer trigram matching: `pg_trgm`

Brand-style designer names (PetiteKnit, KnitPicks) break full-text tokenization. Woolly
uses the `pg_trgm` extension:

```sql
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX patterns_designer_trgm_idx ON patterns USING GIN (designer gin_trgm_ops);
```

Similarity is computed on space-stripped, lowercased names:
`similarity(replace(lower(designer), ' ', ''), 'petiteknit')`

See `10-hybrid-search-and-reranking.md` for how this fits into hybrid search.

---

## What is an ORM?

**ORM = Object-Relational Mapper.** It's a tool that bridges two worlds:
- **Relational world:** tables, rows, SQL queries
- **Object world:** Python classes, instances, method calls

Without an ORM, to get patterns from the database you'd write raw SQL strings in Python:
```python
cursor.execute("SELECT id, name, designer FROM patterns WHERE embedding IS NOT NULL LIMIT 10")
rows = cursor.fetchall()
for row in rows:
    print(row[1])  # what is index 1 again? Oh, "name". Hope I don't forget.
```

This is error-prone: typos in SQL aren't caught by Python, column indexes are magic numbers,
and you have to manually map rows to Python objects.

**With SQLAlchemy (Woolly's ORM):**
```python
rows = db.query(Pattern).filter(Pattern.embedding.isnot(None)).limit(10).all()
for pattern in rows:
    print(pattern.name)  # dot-access by name, type-aware, checked by Python
```

**Analogy:** an ORM is a **translator** at the United Nations. The Python code speaks
Python, the database speaks SQL, and the ORM translates between them in both directions.

---

## The SQLAlchemy Pattern model

In `backend/app/db/models.py`, the `patterns` table is defined as a Python class:

```python
from sqlalchemy import Column, Integer, Text, Boolean, DateTime
from sqlalchemy.orm import DeclarativeBase
from pgvector.sqlalchemy import Vector

class Pattern(Base):
    __tablename__ = "patterns"

    id          = Column(Integer, primary_key=True)
    ravelry_id  = Column(Integer, unique=True, nullable=False)
    name        = Column(Text, nullable=False)
    designer    = Column(Text)
    description = Column(Text)
    difficulty  = Column(Text)
    craft       = Column(Text)
    category    = Column(Text)
    is_free     = Column(Boolean, default=False)
    ravelry_url = Column(Text, nullable=False)
    image_url   = Column(Text)
    embedding   = mapped_column(Vector(384))    # text MiniLM
    image_embedding = mapped_column(Vector(512))  # CLIP visual search (nullable)
    search_vector = mapped_column(TSVECTOR)     # full-text search
    tags        = mapped_column(ARRAY(Text))
    raw_data    = Column(JSONB)
    created_at  = Column(DateTime, server_default=func.now())
    updated_at  = Column(DateTime, server_default=func.now())
```

Each Python attribute maps to a database column. You get auto-completion, type hints, and
Python-level column access. SQLAlchemy converts your Python method calls into SQL.

---

## Database sessions: the connection lifecycle

Databases don't have unlimited connections. You open a connection when you need to talk
to the database and close it when you're done — otherwise you leak connections and
eventually the database refuses new ones.

A **session** in SQLAlchemy is a unit of work against the database — it manages the
connection and groups operations together.

In `backend/app/db/session.py`:

```python
def get_db():
    db = SessionLocal()  # open a new session (borrow a connection from the pool)
    try:
        yield db          # hand it to the route handler
    finally:
        db.close()        # always close it when done, even if there was an error
```

This is a Python **generator function** (uses `yield` instead of `return`). FastAPI uses
`Depends(get_db)` to:
1. Call `get_db()`, run it up to the `yield`, and get the `db` session
2. Pass `db` into the route handler
3. After the request finishes (even on error), run the `finally` block to close the session

**Analogy:** it's like a library book checkout system. You check out a book (open a
session), use it, and return it (close the session). The `finally` block is the guarantee
that the book always gets returned — even if you drop it on the way out.

---

## Idempotent database initialization

In `backend/app/db/init_db.py`, the setup code runs every time the server starts:

```python
def init_db():
    # Enable pgvector extension
    conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(engine)  # creates all tables (patterns, users, projects, etc.)
    # Create indexes: IVFFlat (vectors), GIN (full-text), GIN (trigram)
    conn.execute(text(IVFFLAT_INDEX_SQL))
    conn.execute(text(FULLTEXT_SEARCH_SQL))   # search_vector + trigger
    conn.execute(text(DESIGNER_TRGM_SQL))     # pg_trgm extension + index
```

The key phrase is **`IF NOT EXISTS`**. This makes the initialization **idempotent** —
it can run any number of times and produces the same result. Run it 1 time or 100 times:
you end up with the extension enabled and the table existing. No crashes, no duplicates.

**Why this matters:** every time the Docker container starts, this runs. If the database
already has the table (e.g. you're restarting the server), it just skips the creation
step gracefully. No manual migration step needed for normal restarts.

---

## UPSERT: insert or update, not both

When the seeding script runs, it might encounter a pattern it's already stored. Instead of
crashing ("this ravelry_id already exists!") or silently skipping it, Woolly does an
**UPSERT**: "insert this row, but if it already exists (same `ravelry_id`), update it."

```python
# In seed_patterns.py — conceptual version
existing = db.query(Pattern).filter(Pattern.ravelry_id == data["id"]).first()
if existing:
    # update the fields
    existing.name = data["name"]
    existing.embedding = embed_text(build_pattern_text(data))
    db.commit()
else:
    # create new row
    new_pattern = Pattern(**data)
    db.add(new_pattern)
    db.commit()
```

This is why re-running the seed script is safe. It won't create 1,000 duplicate patterns —
it'll update the ones it's seen before and add only truly new ones.

---

## SQL vs NoSQL: why Woolly uses SQL (Postgres)

You might wonder: why not use MongoDB (a NoSQL, document-based database)?

| Factor | PostgreSQL (SQL) | MongoDB (NoSQL) |
|---|---|---|
| Data structure | Rigid schema — columns defined upfront | Flexible — any shape document |
| Queries | Powerful SQL — joins, aggregations, full-text search | More limited query language |
| pgvector support | Yes | No |
| Transactions | Full ACID compliance | Partial |
| Best for | Structured, related data | Rapidly changing, flexible schemas |

Woolly's data is well-structured (patterns always have the same fields), needs
pgvector, and will eventually need joins (e.g. saved_patterns joining users and patterns).
SQL is the clear choice. The `raw_data JSONB` column gives Woolly MongoDB-like flexibility
for the fields that are unpredictable, while keeping structure where it matters.

---

## The JSONB column: best of both worlds

```sql
raw_data JSONB
```

`JSONB` is PostgreSQL's binary JSON type. It stores the entire Ravelry API response as-is.

**Why store the whole response?** Ravelry's API returns ~50 fields per pattern. Woolly
promotes some to first-class columns, and still reads nested fields like `yarn_weight` and
`pattern_needle_sizes` from JSON inside `build_pattern_text`. Keeping `raw_data` means you
can change the embedding text (or add columns later) and **re-embed without re-fetching**
Ravelry — just run `re_embed_existing()`.

`JSONB` also supports SQL queries and indexing on nested fields:
```sql
SELECT raw_data->'yarn_weight' FROM patterns WHERE ravelry_id = 12345;
```

**Analogy:** `raw_data` is like keeping the original receipt. The structured columns are
the summary you wrote in your expense tracker. If you ever need to verify a detail, the
original receipt is right there.

---

## Connection pooling (brief)

Opening a new database connection for every request is expensive (~100ms). SQLAlchemy uses
a **connection pool** — a set of pre-opened connections that requests borrow and return.

```python
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,  # test connections before using them (catches stale ones)
)
```

`pool_pre_ping=True` means "before handing out a connection, send a quick ping to make
sure it's still alive." This prevents errors from connections that went stale (e.g. the
database restarted).

---

## Interview questions for this topic

**Q: Walk me through your database schema.**
A: "The core table is `patterns` — Ravelry metadata plus a 384-dim text embedding, a
512-dim CLIP `image_embedding` for visual search, a `search_vector` tsvector for full-text
search, and tags as a PostgreSQL array. User tables include `users` (email + bcrypt hash),
`saved_patterns` (many-to-many bookmarks), and `projects` (WIP tracker with yarn, progress,
stitch counts). `seed_runs` logs seeding executions. Index types: IVFFlat for text vectors,
GIN for full-text, GIN trigram for designer names. Image vectors are scanned directly at
current scale; an ANN index would come later."

**Q: What is an ORM and why use one?**
A: "An ORM maps database tables to Python classes so you can work with familiar objects
instead of raw SQL strings. SQLAlchemy lets me write `db.query(Pattern).filter(...)`
instead of building SQL strings manually — which is type-safe, composable, and less
error-prone. The trade-off is that ORMs can generate inefficient SQL for complex queries,
but for Woolly's usage patterns it's the right tool."

**Q: What is idempotent database initialization?**
A: "Using `CREATE TABLE IF NOT EXISTS` and `CREATE EXTENSION IF NOT EXISTS` means the
setup code can run any number of times — including on every server restart — without
crashing or creating duplicates. It's the same end state regardless of how many times
you run it."

**Q: Why store `raw_data` as JSONB?**
A: "Ravelry's API returns ~50 fields per pattern. I only use about a dozen now, but I
don't want to have to re-query Ravelry if I need more fields later. JSONB stores the full
payload and PostgreSQL can query into it. It's the receipt — the structured columns are
the summary."

**Q: What is a database session?**
A: "A session is a unit of work against the database — it manages the connection lifecycle.
FastAPI's dependency injection calls `get_db()`, which opens a session and yields it to
the route handler. After the request finishes (even on error), the `finally` block closes
it. This prevents connection leaks."
