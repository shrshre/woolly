# Woolly

A full-stack crafting companion for knitters and crocheters. Woolly helps you find patterns by **intent** — plain-English queries and photos — instead of exact keyword matches, then keeps projects, a pattern library, and crafting tools in one place.

Pattern metadata comes from the [Ravelry API](https://www.ravelry.com/api). Results always link back to Ravelry and the original designers; Woolly stores and indexes cached pattern data for search.

## Features

- **Hybrid text search** — vector similarity + BM25 + designer name matching, then cross-encoder reranking
- **Ask Woolly** — a conversational finder: describe a project in a sentence and get a short recommendation with cited patterns, grounded in the same search pipeline (optional; needs an OpenAI key)
- **Visual search** — upload a photo of a knit/crochet piece; CLIP finds visually similar patterns
- **Filters & pagination** — craft, difficulty, free/paid, category; ranked results cached and sliced by page
- **Recommendations** — homepage picks from a "taste vector" built from your saved patterns and recent searches, with a popularity fallback for new and anonymous visitors
- **Accounts** — register/login with JWT in an httpOnly cookie; saved pattern library and project tracker
- **Stitch counter** — voice-assisted counting (Web Speech API)
- **Colorwork grid maker** — turn an image into a quantized knitting/crochet chart
- **Background seeding** — incremental Ravelry re-seed every 24 hours, with Redis cache invalidation

## How search works

**Text:** query → embedding (`all-MiniLM-L6-v2`) → hybrid retrieval over Postgres/pgvector (dense + full-text + designer trigram) → cross-encoder rerank (`ms-marco-MiniLM-L-6-v2`) → filters/pagination from a Redis-cached ranked list.

**Visual:** uploaded image → CLIP (`clip-ViT-B-32`, multi-crop blend) → nearest pattern `image_embedding` vectors (512-d).

## How Ask Woolly works

`POST /patterns/ask` is retrieval-augmented generation over the search pipeline — retrieval is unchanged, generation is added on top:

1. **Extraction** — the message (plus recent turns, so "cheaper ones?" works) becomes a clean search query plus `craft` / `difficulty` / `free` / `category` filters. The model may only pick craft and category values that exist in the corpus, and anything it invents is dropped before the filters reach SQL.
2. **Retrieval** — the same hybrid + cross-encoder pipeline the search bar uses. Filters are soft: if they match nothing, the search is retried without them and the response is flagged `filters_relaxed`.
3. **Generation** — the top 5 results are packed into a numbered context block (name, designer, craft, category, difficulty, free/paid, yarn weight, needles, tags, truncated description) and the model writes 2–4 sentences citing them as `[1]`, `[2]`. The frontend renders those patterns as numbered cards in the same order.

The prompt is grounded strictly in retrieved rows and only in the metadata Woolly stores — the model is instructed never to invent a pattern or write out stitch instructions, which stay on Ravelry.

Conversations are not persisted: the client sends recent turns with each request. Asks are cached in Redis (keyed by the whole conversation), rate limited per account or browser session, and logged to `search_events` as `search_type = "rag"`, so saves and Ravelry clicks on cited cards attribute the same way as search results. With no `OPENAI_API_KEY` set the feature disables itself — `GET /patterns/ask/capability` reports it unavailable and the UI hides the tab.

## How recommendations work

Homepage `GET /patterns/recommendations` builds a **taste vector** from your recent saved-pattern embeddings (weight 2) and recent text-search queries (weight 1), then finds nearest not-yet-saved patterns by cosine similarity, with a per-designer diversity cap. Anonymous visitors and cold-start accounts get a **popularity** ranking (library saves ×2 + result clicks). Responses are cached in Redis per user; saving or unsaving a pattern invalidates that cache.

## Stack

| Layer | Technology |
|---|---|
| Frontend | React 18, TypeScript, Vite, React Router |
| Backend | Python 3.12, FastAPI, Uvicorn, Pydantic Settings |
| Database | PostgreSQL 16 + pgvector + `pg_trgm` |
| Cache | Redis 7 |
| Auth | JWT in httpOnly cookie, bcrypt passwords |
| Text embeddings | `sentence-transformers` `all-MiniLM-L6-v2` (384-d) |
| Reranker | `cross-encoder/ms-marco-MiniLM-L-6-v2` |
| Visual search | `clip-ViT-B-32` (512-d image embeddings) |
| Conversational answers | OpenAI chat completions (`gpt-4o-mini` by default), optional |
| Jobs | APScheduler (24h incremental seed) |
| Containers | Docker + docker-compose |

## Local setup

### 1. Get Ravelry credentials

1. Go to [ravelry.com/pro/developer](https://www.ravelry.com/pro/developer) and create an app.
2. Choose **basic authentication, read-only access**.
3. Note the generated username and password.

### 2. Configure environment

```bash
cp .env.example .env
```

Fill in at least:

- `RAVELRY_USERNAME` / `RAVELRY_PASSWORD`
- `JWT_SECRET_KEY` — generate with `openssl rand -hex 32` (do not leave blank or use a weak default in any shared environment)

Optional: set `OPENAI_API_KEY` to enable Ask Woolly. Leave it blank and everything else works — the Ask tab simply doesn't appear. `ASK_RATE_LIMIT_PER_HOUR` (default 10) caps asks per account or browser session.

Never commit `.env`.

### 3. Run the stack

```bash
docker-compose up --build
```

| Service | URL |
|---|---|
| Frontend | http://localhost:5173 |
| Backend API | http://localhost:8000 — OpenAPI at `/docs` |
| PostgreSQL | localhost:5432 |
| Redis | localhost:6379 |

First backend startup downloads/loads the text embedding and reranker models (CLIP loads lazily on the first visual search).

### 4. Seed patterns (required for text search)

```bash
docker-compose exec backend python scripts/seed_patterns.py --limit 500
```

Safe to re-run: upserts by `ravelry_id`, skips patterns that already have embeddings. For a fuller corpus use a higher `--limit` (default is 5000). Incremental mode (also used by the nightly scheduler):

```bash
docker-compose exec backend python scripts/seed_patterns.py --incremental
```

### 5. Backfill image embeddings (required for visual search)

```bash
docker-compose exec backend python scripts/embed_images.py
```

Idempotent: only patterns with an image URL and no `image_embedding` are processed. Optional `--limit` / `--re-embed`.

### 6. Try it

- Open http://localhost:5173 and search something like `cozy winter sweater` or `quick gift for beginners`
- With `OPENAI_API_KEY` set, switch to **Ask Woolly** and try `a beginner gift I can finish this weekend`, then follow up with `cheaper ones?`
- Upload a photo of a finished object for visual search
- Create an account to save patterns and track projects
- API smoke checks:

```bash
curl "http://localhost:8000/health"
curl "http://localhost:8000/patterns/semantic-search?q=cozy%20winter%20sweater"
curl "http://localhost:8000/patterns/search?q=cardigan"   # Ravelry keyword proxy
```

## Main API routes

| Area | Endpoints |
|---|---|
| Search | `GET /patterns/semantic-search`, `POST /patterns/visual-search`, `GET /patterns/search`, `GET /patterns/filters` |
| Ask Woolly | `POST /patterns/ask`, `GET /patterns/ask/capability` |
| Recommendations | `GET /patterns/recommendations` |
| Library | `POST/DELETE /patterns/{ravelry_id}/save`, `GET /users/me/library` |
| Auth | `POST /auth/register`, `POST /auth/login`, `POST /auth/logout`, `GET /auth/me` |
| Projects | `GET/POST /projects`, `PATCH/DELETE /projects/{id}` |
| Admin | `GET /admin/analytics` (requires `X-Admin-Token` when `ADMIN_API_TOKEN` is set) |
| Health | `GET /health` |

## Tests

```bash
cd backend
pip install -r requirements.txt
pytest
```

## Repository structure

```
woolly/
├── docker-compose.yml
├── .env.example
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI entrypoint, lifespan, routers
│   │   ├── config.py          # env-based settings
│   │   ├── api/               # patterns, projects, users, admin
│   │   ├── auth/              # JWT cookie auth
│   │   ├── search/            # hybrid pipeline, conversational RAG, recommendations, filters
│   │   ├── services/          # Ravelry, embeddings, CLIP, rerank, LLM, seeding
│   │   ├── db/                # SQLAlchemy models, session, init
│   │   ├── cache/             # Redis helpers
│   │   └── scheduler.py       # 24h incremental seed
│   ├── scripts/
│   │   ├── seed_patterns.py
│   │   └── embed_images.py
│   └── tests/
└── frontend/
    └── src/
        ├── pages/             # Home, Library, Projects, Counter, Grid, Auth
        ├── components/        # SearchBar, AskPanel, PatternCard, RecommendedPatterns, …
        ├── api/client.ts      # typed API client
        └── auth/              # AuthContext, SavedPatternsContext
```

## Attribution

Pattern data courtesy of [Ravelry](https://www.ravelry.com). All patterns link back to their designers.
