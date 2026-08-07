# Woolly

A full-stack crafting companion for knitters and crocheters. Woolly helps you find patterns by **intent** — plain-English queries and photos — instead of exact keyword matches, then keeps projects, a pattern library, and crafting tools in one place.

Pattern metadata comes from the [Ravelry API](https://www.ravelry.com/api). Results always link back to Ravelry and the original designers; Woolly stores and indexes cached pattern data for search.

## Features

- **Hybrid text search** — vector similarity + BM25 + designer name matching, then cross-encoder reranking
- **Visual search** — upload a photo of a knit/crochet piece; CLIP finds visually similar patterns
- **Filters & pagination** — craft, difficulty, free/paid, category; ranked results cached and sliced by page
- **Accounts** — register/login with JWT in an httpOnly cookie; saved pattern library and project tracker
- **Stitch counter** — voice-assisted counting (Web Speech API)
- **Colorwork grid maker** — turn an image into a quantized knitting/crochet chart
- **Background seeding** — incremental Ravelry re-seed every 24 hours, with Redis cache invalidation

## How search works

**Text:** query → embedding (`all-MiniLM-L6-v2`) → hybrid retrieval over Postgres/pgvector (dense + full-text + designer trigram) → cross-encoder rerank (`ms-marco-MiniLM-L-6-v2`) → filters/pagination from a Redis-cached ranked list.

**Visual:** uploaded image → CLIP (`clip-ViT-B-32`, multi-crop blend) → nearest pattern `image_embedding` vectors (512-d).

For a deeper walkthrough, see [`PROJECT_EXPLAINER.md`](PROJECT_EXPLAINER.md).

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
├── PROJECT_EXPLAINER.md       # interview-oriented system walkthrough
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI entrypoint, lifespan, routers
│   │   ├── config.py          # env-based settings
│   │   ├── api/               # patterns, projects, users, admin
│   │   ├── auth/              # JWT cookie auth
│   │   ├── search/            # hybrid pipeline, filters, semantic helpers
│   │   ├── services/          # Ravelry, embeddings, CLIP, rerank, seeding
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
        ├── components/        # SearchBar, PatternCard, FilterBar, …
        ├── api/client.ts      # typed API client
        └── auth/              # AuthContext, SavedPatternsContext
```

## Attribution

Pattern data courtesy of [Ravelry](https://www.ravelry.com). All patterns link back to their designers.
