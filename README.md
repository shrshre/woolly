# Woolly

A crafting companion for fiber artists (crochet and knitting). Semantic pattern search over Ravelry data: patterns are embedded locally with `all-MiniLM-L6-v2` and searched via pgvector cosine similarity, served by a FastAPI backend (cached in Redis) to a minimal React frontend.

Pattern data is provided by the [Ravelry API](https://www.ravelry.com/api). All patterns link back to Ravelry; Woolly caches search result metadata only.

## Stack

- **Backend:** Python / FastAPI
- **Cache:** Redis (1-hour TTL on Ravelry proxy, 30-minute TTL on semantic search)
- **Database:** PostgreSQL + pgvector (`patterns` table with 384-dim embeddings)
- **Embeddings:** sentence-transformers `all-MiniLM-L6-v2`, run locally on CPU
- **Frontend:** React + TypeScript (Vite)
- **Containerization:** Docker + docker-compose

## Local setup

### 1. Get Ravelry credentials

1. Go to [ravelry.com/pro/developer](https://www.ravelry.com/pro/developer) and create an app.
2. Choose **basic authentication, read-only access**.
3. Note the generated username and password.

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and fill in `RAVELRY_USERNAME` and `RAVELRY_PASSWORD`. Never commit `.env`.

### 3. Run the stack

```bash
docker-compose up --build
```

This starts:

| Service | URL |
|---|---|
| Frontend | http://localhost:5173 |
| Backend API | http://localhost:8000 (docs at /docs) |
| Redis | localhost:6379 |
| PostgreSQL | localhost:5432 (unused this week) |

### 4. Seed the pattern database (Week 2)

Semantic search runs against locally stored patterns. Seed ~500 of them (takes a few minutes; rate-limit friendly):

```bash
docker-compose exec backend python scripts/seed_patterns.py --limit 500
```

The script is safe to re-run — already-embedded patterns are skipped.

### 5. Verify

- Open http://localhost:5173 and try a natural-language search like "cozy winter sweater".
- Search the same term again — the backend logs should show a Redis cache hit.
- Or hit the API directly:
  - Semantic search: `curl "http://localhost:8000/patterns/semantic-search?q=cozy%20winter%20sweater"`
  - Ravelry keyword proxy (still available): `curl "http://localhost:8000/patterns/search?q=cardigan"`

## Running backend tests

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
│   │   ├── main.py            # FastAPI entrypoint
│   │   ├── config.py          # env-based settings
│   │   ├── api/patterns.py    # GET /patterns/search + /patterns/semantic-search
│   │   ├── services/          # Ravelry client + embedding service
│   │   ├── cache/             # Redis helpers
│   │   ├── db/                # SQLAlchemy Pattern model, session, init_db
│   │   ├── search/            # pgvector semantic search
│   │   └── auth/              # placeholder (Week 4+: JWT auth)
│   └── scripts/
│       └── seed_patterns.py   # seed patterns from Ravelry + embeddings
└── frontend/
    └── src/
        ├── App.tsx            # minimal search UI
        ├── api/client.ts      # typed fetch wrapper
        └── components/        # placeholder (Week 3+: pattern cards)
```
