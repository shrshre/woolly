# Product Requirements Document: Woolly — Week 2
**Version:** 1.0  
**Status:** Active — Week 2 build only  
**Depends on:** Week 1 scaffold (Ravelry API integration, FastAPI backend, React frontend, docker-compose)

---

## ⚠️ Scope Notice for Claude Code / Cursor

**Build ONLY the Week 2 deliverables defined in Section 6.** Week 1 must be complete and working before starting this. Do not implement user auth, the project tracker, the stitch counter, the pixel grid maker, or anything from the future roadmap section. Do not redesign the frontend beyond wiring the new search endpoint into the existing UI.

The goal of Week 2 is one thing: **replace the Ravelry keyword proxy with a real semantic search engine powered by vector embeddings and pgvector.**

---

## 1. Context & Goal

In Week 1, the search bar proxied queries directly to Ravelry's `patterns/search` API. This returns keyword-matched results — the same quality as Ravelry's own search, which is the problem Woolly is trying to solve.

Week 2 replaces this with a semantic search layer. When a user searches "cozy winter sweater," the app should understand *intent* and return relevant patterns even if those exact words don't appear in the pattern title. This is the core technical differentiator of the entire product.

**How it works at a high level:**
1. A batch seeding job pulls patterns from Ravelry and stores them in PostgreSQL
2. Each pattern's text content (name + description + tags) is converted into a vector embedding using a local ML model
3. When a user searches, the query is embedded using the same model
4. PostgreSQL finds the most semantically similar patterns using vector cosine similarity
5. Results are returned ranked by relevance

---

## 2. Tech Additions in Week 2

| Component | Addition |
|---|---|
| PostgreSQL | pgvector extension enabled; `patterns` table with `vector(384)` embedding column |
| ML model | `sentence-transformers` library, model `all-MiniLM-L6-v2` — runs **locally**, no API key |
| Backend | New embedding service, new semantic search route, seeding script |
| Frontend | Swap existing search to call new semantic endpoint (minimal change) |

---

## 3. Embedding Model Details

**Model:** `all-MiniLM-L6-v2` from sentence-transformers  
**Why this model:**
- Free, runs locally inside Docker — no external API dependency, no cost per query
- 384-dimensional vectors — small enough to be fast, large enough to be meaningful
- Well-documented, widely used for semantic search tasks
- Runs on CPU — no GPU required

**Installation:**
```bash
pip install sentence-transformers
```

**Usage:**
```python
from sentence_transformers import SentenceTransformer
model = SentenceTransformer('all-MiniLM-L6-v2')
embedding = model.encode("beginner chunky cardigan no seaming")
# returns a numpy array of shape (384,)
```

**Important:** The model download (~90MB) happens on first use. In Docker, this should be triggered at build time (not runtime) by adding a model warm-up step to the Dockerfile so startup is fast.

---

## 4. Database Schema

### Enable pgvector
```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

Add this to your database initialization script or migration.

### Patterns Table
```sql
CREATE TABLE IF NOT EXISTS patterns (
    id              SERIAL PRIMARY KEY,
    ravelry_id      INTEGER UNIQUE NOT NULL,
    name            TEXT NOT NULL,
    designer        TEXT,
    description     TEXT,
    difficulty      TEXT,
    craft           TEXT,         -- 'knitting' or 'crochet'
    category        TEXT,
    is_free         BOOLEAN DEFAULT FALSE,
    ravelry_url     TEXT NOT NULL,
    image_url       TEXT,         -- linked from Ravelry, never hosted
    embedding       vector(384),  -- semantic embedding of name + description + tags
    tags            TEXT[],       -- array of tag strings
    raw_data        JSONB,        -- full Ravelry API response for reference
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS patterns_embedding_idx
    ON patterns USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);
```

**Note on the index:** IVFFlat is an approximate nearest neighbor index. It makes similarity search fast at scale. `lists = 100` is appropriate for a dataset of ~1000–10000 patterns. Rebuild the index after seeding.

---

## 5. Architecture

### New Backend Services

```
backend/app/
├── services/
│   ├── ravelry_client.py     (existing — Week 1)
│   └── embedding_service.py  (NEW — Week 2)
├── db/
│   ├── models.py             (NEW — SQLAlchemy Pattern model)
│   ├── session.py            (NEW — database session management)
│   └── init_db.py            (NEW — create tables + enable pgvector)
├── search/
│   └── semantic_search.py    (NEW — pgvector similarity query)
├── api/
│   ├── patterns.py           (MODIFY — add /patterns/semantic-search route)
│   └── seed.py               (NEW — seeding endpoint or script)
└── scripts/
    └── seed_patterns.py      (NEW — standalone seeding script)
```

### Request Flow (Week 2)

```
User types query
      ↓
Frontend calls GET /patterns/semantic-search?q=...
      ↓
Backend embeds query using all-MiniLM-L6-v2
      ↓
pgvector cosine similarity search against patterns table
      ↓
Top 10 results returned, ordered by similarity score
      ↓
Frontend displays results (same card UI as Week 1)
```

### Seeding Flow (one-time batch job)

```
seed_patterns.py runs
      ↓
Calls Ravelry patterns/search for multiple broad queries
(e.g. "sweater", "hat", "shawl", "cardigan", "amigurumi")
      ↓
For each pattern: stores metadata in PostgreSQL
      ↓
Generates embedding from: name + " " + description + " " + tags.join(" ")
      ↓
Stores embedding in patterns.embedding column
      ↓
Logs progress — target: 500–1000 patterns for MVP
```

---

## 6. ✅ WEEK 2 DELIVERABLES (Build These Only)

### 6.1 Database Setup

- Enable the pgvector extension in PostgreSQL on container startup
- Create the `patterns` table per the schema in Section 4
- Create the IVFFlat index on the embedding column
- SQLAlchemy model for `Pattern` in `db/models.py`
- Database session management in `db/session.py`
- `init_db.py` script that can be run to create tables idempotently

### 6.2 Embedding Service

Create `services/embedding_service.py`:
- Load `all-MiniLM-L6-v2` model once at application startup (not per request — model loading is slow)
- Expose a function `embed_text(text: str) -> list[float]` that returns a 384-dimensional vector
- Expose a function `build_pattern_text(pattern: dict) -> str` that concatenates name + description + tags into a single string for embedding
- Model must be loaded in a singleton pattern — one instance shared across requests

**Dockerfile addition:** warm up the model at build time:
```dockerfile
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"
```

### 6.3 Seeding Script

Create `scripts/seed_patterns.py`:
- Accepts a `--limit` argument (default 500 patterns)
- Fetches patterns from Ravelry across multiple craft categories to ensure variety
- For each pattern: upserts into the `patterns` table using `ravelry_id` as the unique key
- Generates and stores embedding for each pattern
- Logs progress every 50 patterns (`Processed 50/500...`)
- Skips patterns that already have embeddings (safe to re-run)
- Handles Ravelry rate limits gracefully (add a small sleep between API calls)

Run via:
```bash
docker-compose exec backend python scripts/seed_patterns.py --limit 500
```

### 6.4 Semantic Search Route

Create `search/semantic_search.py`:
- Function `semantic_search(query: str, limit: int = 10) -> list[dict]`
- Embeds the query using the embedding service
- Runs pgvector cosine similarity: `ORDER BY embedding <=> query_vector LIMIT n`
- Returns pattern dicts with a `similarity_score` field (0–1, higher is better)

Add to `api/patterns.py`:
- New route: `GET /patterns/semantic-search?q={query}&limit={n}`
- Validates query is non-empty
- Returns results in same shape as the Week 1 Ravelry proxy response so frontend needs minimal changes
- Cache results in Redis keyed by `semantic:{normalized_query}` with 30-minute TTL
- Keep the original `/patterns/search` Ravelry proxy route — do not remove it

### 6.5 Frontend Update

Minimal change — swap the API call:
- Change the search fetch from `GET /patterns/search?q=...` to `GET /patterns/semantic-search?q=...`
- Response shape should be identical so no card component changes needed
- Add a small loading state if not already present (spinner or skeleton)
- No other frontend changes in Week 2

### 6.6 Week 2 Definition of Done

- `docker-compose up` starts cleanly with pgvector enabled
- `seed_patterns.py` runs successfully and populates 500+ patterns with embeddings
- Searching "cozy winter sweater" returns semantically relevant results even if those exact words aren't in the pattern title
- The same query served twice hits Redis cache on the second call (verifiable in logs)
- The original `/patterns/search` Ravelry proxy route still works
- No regressions in Week 1 functionality

---

## 7. Testing Queries

After seeding, manually test these queries to verify semantic understanding is working:

| Query | What good results look like |
|---|---|
| `cozy winter sweater` | Chunky sweaters, cardigans, pullovers |
| `quick gift for beginners` | Hats, mitts, cowls — beginner difficulty |
| `no seaming required` | Top-down, seamless, in-the-round patterns |
| `colorful stranded project` | Fair Isle, stranded colorwork, tapestry |
| `something for my cat` | Pet patterns, cat toys, animal beds |
| `summer beach cover-up` | Lightweight shawls, lacy tops, cover-ups |

If results for these queries are clearly wrong (returning unrelated patterns), the embedding pipeline or search query has a bug.

---

## 8. Performance Notes

- **Model loading time:** ~3–5 seconds on first load. Load at app startup, not per-request.
- **Embedding generation time:** ~10–50ms per text string on CPU. Acceptable for real-time search.
- **pgvector query time:** Sub-10ms for 1000 patterns with IVFFlat index.
- **Redis cache:** semantic search results cached for 30 minutes. Pattern data doesn't change often so this is safe.
- **Seeding time:** Expect 5–15 minutes for 500 patterns due to Ravelry API rate limits and embedding generation.

---

## 9. Environment Variables (additions to .env)

```
# Already in Week 1
RAVELRY_USERNAME=
RAVELRY_PASSWORD=
REDIS_URL=redis://redis:6379
DATABASE_URL=postgresql://postgres:password@db:5432/woolly

# No new env vars needed for Week 2
# The embedding model downloads automatically from HuggingFace
# If behind a corporate proxy, set:
# HF_HUB_OFFLINE=1 (and pre-download the model)
```

---

## 10. Future Roadmap (Context Only — DO NOT BUILD)

### Week 3 — Search UI Polish
- Polished pattern cards with real Ravelry images
- Filter sidebar: craft type, difficulty, free/paid, category
- Filters applied server-side before vector search runs
- Loading skeleton states, empty states, error states

### Week 4 — Accounts + Library + Deploy
- JWT email/password auth
- Saved patterns library (`saved_patterns` join table)
- Deploy to Railway (backend) + Vercel (frontend) for public URL
- README screenshots and architecture diagram

### Month 2 — Project Tracker + Stitch Counter
- Project tracker: pattern + yarn + notes + progress + WIP photos
- Voice-activated stitch counter (Web Speech API)

### Month 3+ — Recommendations + AWS + Monetization
- Personalized recommendations from saved-pattern history
- AWS deployment (ECS + RDS + ElastiCache + S3 + CloudFront)
- Ravelry OAuth for users to link their own accounts
- Freemium tier gating via feature flags (LaunchDarkly)
- Stripe integration (deferred until validated user demand)

---

## 11. Interview Talking Points

This section exists so you can explain what you built. Study it before interviews.

**"What is pgvector?"**  
pgvector is a PostgreSQL extension that adds a `vector` data type and similarity search operators. The `<=>` operator computes cosine distance between two vectors. It lets you do ML-style nearest-neighbor search inside a regular SQL database without a separate vector store.

**"Why all-MiniLM-L6-v2?"**  
It's a sentence transformer model that converts text into 384-dimensional dense vectors where semantically similar text ends up geometrically close. It's small (runs on CPU), fast (~20ms per embedding), free, and well-suited for semantic search tasks. The "L6" refers to 6 transformer layers — a good speed/quality tradeoff for search.

**"Why run embeddings locally instead of using OpenAI?"**  
Cost control, no external dependency, no latency on API calls, and it's a better engineering story — I understand what the model is doing rather than treating it as a black box. The tradeoff is model quality, but all-MiniLM-L6-v2 is good enough for pattern search.

**"How does cosine similarity work here?"**  
Both the query and each stored pattern are represented as 384-dimensional vectors. Cosine similarity measures the angle between them — vectors pointing in the same direction (score near 1) represent semantically similar text, regardless of exact word overlap. "Cozy winter sweater" and "warm chunky pullover" end up close in vector space even though they share no words.

**"What would you do differently at scale?"**  
With 100k+ patterns, IVFFlat approximate search becomes important for speed. I'd also consider a two-stage pipeline: fast ANN search to get top-100 candidates, then a reranking step using a higher-quality cross-encoder model to reorder the final top-10. I'd also move embeddings to a dedicated vector store like Pinecone or Weaviate if query volume justified it.
