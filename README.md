# Woolly

A full-stack crafting companion for knitters and crocheters. Woolly helps you find patterns by **intent** — plain-English queries and photos — instead of exact keyword matches, then keeps projects, a pattern library, and crafting tools in one place.

Pattern metadata comes from the [Ravelry API](https://www.ravelry.com/api). Results always link back to Ravelry and the original designers; Woolly stores and indexes cached pattern data for search.

## Features

- **Hybrid text search** — vector similarity + BM25 + designer name matching, then cross-encoder reranking
- **Ask Woolly** — a conversational finder: describe a project in a sentence and get a short recommendation with cited patterns, grounded in the same search pipeline (optional; needs an OpenAI key)
- **Visual search** — upload a photo of a knit/crochet piece; CLIP finds visually similar patterns
- **Filters & pagination** — craft, difficulty, free/paid, category; ranked results cached and sliced by page
- **Recommendations** — homepage picks from a "taste vector" built from your saved patterns and recent searches, with a popularity fallback for new and anonymous visitors
- **Accounts** — register/login with JWT in an httpOnly cookie; forgot-password email reset; saved pattern library and project tracker
- **Stitch counter** — voice-assisted counting (Web Speech API)
- **Colorwork grid maker** — turn an image into a quantized knitting/crochet chart
- **Background seeding** — incremental Ravelry re-seed every 24 hours, with Redis cache invalidation

## How search works

**Text:** query → embedding (`all-MiniLM-L6-v2`) → hybrid retrieval over Postgres/pgvector (dense + full-text + designer trigram) → cross-encoder rerank (`ms-marco-MiniLM-L-6-v2`) → filters/pagination from a Redis-cached ranked list.

**Visual:** uploaded image → CLIP (`clip-ViT-B-32`, multi-crop blend) → nearest pattern `image_embedding` vectors (512-d).

## How Ask Woolly works

`POST /patterns/ask` is retrieval-augmented generation over the search pipeline — retrieval is unchanged, generation is added on top:

1. **Extraction** — the message (plus recent turns, so "cheaper ones?" works) becomes a clean search query plus `craft` / `difficulty` / `free` filters. The model may only pick crafts that exist in the corpus and that the crafter actually named, and anything it invents is dropped before the filters reach SQL.
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

Forgot-password emails need SMTP (`SMTP_HOST`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM`, plus `FRONTEND_URL` so the reset link points at this app). Leave `SMTP_HOST` blank locally — requesting a reset still works, and the link is printed in the backend logs.

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

Use `--skip-images` when seeding large batches to avoid loading CLIP during text seed:

```bash
docker-compose exec backend python scripts/seed_patterns.py --limit 5000 --skip-images
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

## Deploying to production

Woolly runs in production as **Vercel (frontend) + Railway (backend, Postgres, Redis)**.

| Service | Platform |
|---|---|
| React app | Vercel — static build from `frontend/` |
| FastAPI + ML models | Railway — Docker from `backend/` |
| PostgreSQL + pgvector | Railway Postgres plugin |
| Redis | Railway Redis plugin |

Key points:

- **API proxy:** `frontend/vercel.json` rewrites `/api/*` to Railway. Production `client.ts` uses `/api` — do not set `VITE_API_URL` on Vercel.
- **Auth:** Same-origin `/api` proxy keeps httpOnly cookies working on mobile Safari.
- **Password reset:** Set `SMTP_HOST` / `SMTP_USERNAME` / `SMTP_PASSWORD` / `SMTP_FROM` and `FRONTEND_URL` (your Vercel origin) on the backend so reset emails can be sent.
- **Seeding:** Run `seed_patterns.py` and `embed_images.py` against the production Postgres public URL (or a Railway one-off service). Use `--skip-images` during bulk text seed to save RAM.
- **Scheduler:** Railway backend runs incremental seed every 24h (up to 500 new patterns + 500 image backfills).

Full step-by-step guide: [`docs/15-deployment.md`](docs/15-deployment.md).

Ask Woolly deep dive: [`docs/14-ask-woolly-rag.md`](docs/14-ask-woolly-rag.md).

## Main API routes

| Area | Endpoints |
|---|---|
| Search | `GET /patterns/semantic-search`, `POST /patterns/visual-search`, `GET /patterns/search`, `GET /patterns/filters` |
| Ask Woolly | `POST /patterns/ask`, `GET /patterns/ask/capability` |
| Recommendations | `GET /patterns/recommendations` |
| Library | `POST/DELETE /patterns/{ravelry_id}/save`, `GET /users/me/library` |
| Auth | `POST /auth/register`, `POST /auth/login`, `POST /auth/logout`, `GET /auth/me`, `POST /auth/forgot-password`, `POST /auth/reset-password` |
| Projects | `GET/POST /projects`, `PATCH/DELETE /projects/{id}` |
| Admin | `GET /admin/analytics?days=7` (requires `X-Admin-Token` matching `ADMIN_API_TOKEN`; closed when that's unset) |
| Health | `GET /health` (503 when Postgres or Redis is down) |

## Tests

```bash
cd backend
pip install -r requirements.txt
pytest
```

## Evals

Offline quality checks run fixed JSONL cases through the real search, Ask Woolly, and visual-search code and print a scoreboard. Search can also run as vector-only or hybrid-without-rerank to compare stages:

```bash
docker-compose exec -e GIT_SHA=$(git rev-parse --short HEAD) backend python -m evals.run
docker-compose exec backend python -m evals.run --suite search --variant vector
```

On 26 queries with pooled, graded relevance labels (16.5k-pattern corpus):

| | vector only | hybrid, no rerank | hybrid + rerank |
|---|---|---|---|
| nDCG@10 | 0.826 | 0.711 | **0.888** |
| Exact-title MRR | 0.562 | 0.833 | **1.000** |
| p50 latency | 28 ms | 93 ms | 317 ms |

Ask Woolly is scored per stage on 31 cases, replayed from recorded model responses so no API key is needed:

| Extraction accuracy | Citation validity | Faithfulness (hand-judged) |
|---|---|---|
| 0.913 | 1.000 | 0.903 |

The run exits non-zero when a metric drops below its floor in `backend/evals/thresholds.json`. Case format and options: [`backend/evals/README.md`](backend/evals/README.md).

## Observability

Every search, visual search, and Ask request writes one `search_events` row and one JSON log line (`woolly.requests`) with its total latency, exclusive time per stage (`embed`, `retrieve`, `rerank`, `extract`, `answer`...), any fallbacks (a rerank failure serves unranked results; those aren't cached), and an `error` when it failed. `GET /admin/analytics?days=7` turns that into per-surface p50/p95, error and zero-result rates, cache hit, save and click rates, and stage percentiles with the slowest stage named:

| | p50 | p95 | Slowest stage (p95) |
|---|---|---|---|
| Search | 319 ms | 373 ms | rerank, 288 ms |
| Ask | 3.3 s | 4.3 s | extraction, 2.2 s |

Local, uncached. Details: `docs/20-observability.md`.

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
│   ├── evals/             # offline eval harness: JSONL cases, runner, scoring
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
