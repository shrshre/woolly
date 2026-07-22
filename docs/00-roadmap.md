# Woolly Study Plan — Current Architecture

This folder contains one deep-dive file per concept implemented in Woolly. The goal is to go
from "I built this with help" to "I can explain every layer, defend every decision, and answer
follow-up questions cold."

Each file is self-contained. You can study them in any order, but the sequence below is
designed so each topic builds on the previous one.

**Time estimate:** 12–14 focused study sessions (45–60 min each). Don't try to do it all at
once — two sessions per day is the sweet spot.

---

## What Changed Since the Original Plan

The original study plan covered Weeks 1 & 2: semantic search, pgvector, Redis, Docker. Woolly
has since grown into a full product architecture:

| Area | Before | Now |
|---|---|---|
| Search | Pure semantic (vector only) | **Two-stage pipeline:** hybrid retrieval (vector + BM25 + designer trigram) → cross-encoder reranking |
| Filters | None | Craft, difficulty tier, free/paid, category — applied in SQL before ranking |
| Pagination | Single page of 10 | Up to 50 ranked results, cached as a full list, paginated via `offset`/`limit` |
| Auth | Placeholder UI | JWT in httpOnly cookies, bcrypt passwords, protected routes |
| User data | None | Saved patterns (library), project tracker (WIP), stitch counter |
| Seeding | Manual script only | Manual + **24h incremental scheduler**, `seed_runs` audit table, cache invalidation |
| Frontend | Single search page | React Router, multiple pages, auth context, filter bar |

**Interview priority:** Sessions 3, 4, and 10 (search stack) are where you'll spend the most
time. Know that pipeline cold.

---

## The Files in This Folder

| File | Topic | Priority |
|---|---|---|
| `01-full-stack-architecture.md` | How the whole system fits together | Must-know |
| `02-fastapi-backend.md` | The Python server (FastAPI, async, routing) | Must-know |
| `03-semantic-search-embeddings.md` | Embeddings, bi-encoders, cosine similarity | Must-know |
| `04-pgvector-vector-databases.md` | How vectors are stored and searched in Postgres | Must-know |
| `05-postgresql-sqlalchemy.md` | Schema, ORM, full-text search, user tables | Must-know |
| `06-redis-caching.md` | Cache-aside, filter-aware keys, invalidation | Must-know |
| `07-docker-containerization.md` | Running the app anywhere, reliably | Strong to know |
| `08-external-apis-design-patterns.md` | Ravelry API + key code patterns | Strong to know |
| `09-react-typescript-frontend.md` | React Router, auth, filters, pagination | Strong to know |
| `10-hybrid-search-and-reranking.md` | **The headline feature** — hybrid + rerank pipeline | **Must-know** |
| `11-authentication-and-user-data.md` | JWT cookies, library, projects | Strong to know |

---

## Recommended Study Sessions

### Session 1 — The big picture (45 min)
**File:** `01-full-stack-architecture.md`

Start here. Before diving into any specific piece, you need a clear mental model of how
everything connects.

**Goal by end of session:** You can draw the system on a whiteboard and explain what each
box does and what travels between them — including auth, the two-stage search pipeline, and
user features.

**Sample question you should be able to answer:**
> "Walk me through what happens from the moment a user types a search query to the moment
> they see results."

---

### Session 2 — The server (45 min)
**File:** `02-fastapi-backend.md`

The FastAPI backend is the brain of the operation. Covers routing, Pydantic, dependency
injection, lifespan hooks (two AI models + scheduler), and the new routers.

**Sample questions:**
> "Why did you use FastAPI over Flask or Django?"
> "What happens when the server starts up?"
> "How do you protect routes that require a logged-in user?"

---

### Session 3 — Embeddings: the foundation (50 min)
**File:** `03-semantic-search-embeddings.md`

Covers what embeddings are, the bi-encoder model, cosine similarity, and seeding. Semantic
search is now *one leg* of hybrid retrieval — but you still need the embedding concepts cold.

**Sample questions:**
> "What is an embedding? What is a vector?"
> "Why run the model locally instead of using OpenAI?"
> "What is the difference between a bi-encoder and a cross-encoder?"

---

### Session 4 — pgvector (40 min)
**File:** `04-pgvector-vector-databases.md`

How Woolly stores and searches 384-dimensional embeddings inside PostgreSQL.

**Sample questions:**
> "What is pgvector? Why not Pinecone?"
> "What is an IVFFlat index?"
> "What does approximate nearest neighbor mean?"

---

### Session 5 — Hybrid search + reranking (60 min) ⭐
**File:** `10-hybrid-search-and-reranking.md`

**This is the most important new session.** Read it slowly, twice if needed. This is what
you'll talk about when an interviewer asks "explain your search architecture."

**Goal by end of session:** You can explain the two-stage pipeline, why hybrid beats pure
semantic, how BM25 and designer trigram matching complement vectors, and why reranking only
runs on a small candidate pool.

**Sample questions:**
> "Walk me through your search architecture."
> "Why hybrid search instead of pure semantic?"
> "What is reranking and why not run it over the whole database?"
> "How do filters interact with search?"

---

### Session 6 — The database (45 min)
**File:** `05-postgresql-sqlalchemy.md`

Covers the `patterns` table, new user tables, `search_vector` for BM25, designer trigram
indexes, and SQLAlchemy sessions.

**Sample questions:**
> "Walk me through your database schema."
> "Why is `raw_data` stored as JSONB?"
> "How does full-text search work alongside pgvector?"

---

### Session 7 — Redis caching (40 min)
**File:** `06-redis-caching.md`

Cache-aside, filter-aware cache keys, full-result caching for pagination, and cache
invalidation after seeding.

**Sample questions:**
> "How does your caching layer work?"
> "Why cache the full result list instead of each page separately?"
> "What happens when new patterns are seeded?"

---

### Session 8 — Auth and user data (45 min)
**File:** `11-authentication-and-user-data.md`

JWT in httpOnly cookies, saved patterns, project tracker, authorization patterns.

**Sample questions:**
> "How does authentication work?"
> "Why httpOnly cookies instead of localStorage?"
> "How do you ensure users only see their own projects?"

---

### Session 9 — Docker (40 min)
**File:** `07-docker-containerization.md`

**Sample questions:**
> "Why Docker? What problem does it solve?"
> "How would you deploy this on AWS?"

---

### Session 10 — External APIs and code patterns (45 min)
**File:** `08-external-apis-design-patterns.md`

**Sample questions:**
> "What is the interface pattern and why did you use it for Ravelry?"
> "Where does Woolly use the singleton pattern?"

---

### Session 11 — The front end (45 min)
**File:** `09-react-typescript-frontend.md`

React Router, auth context, FilterBar, pagination, protected routes.

**Sample questions:**
> "Walk me through your React architecture."
> "How does the frontend handle authentication?"
> "How does pagination work with the cached backend results?"

---

## How to Use These Files

1. **Read the whole file once** without stopping, just to absorb the shape.
2. **Read it again** and pause at every analogy/metaphor — make sure it clicks before moving on.
3. **Say the "one-liner" answers out loud.** Seriously. Speaking is different from reading.
4. **Look at the actual code** referenced in each file (the file paths are always given).
   Don't just trust the explanation — look at the real code.
5. **Answer the interview questions at the end of each file** out loud, as if in an interview.

---

## The 5 Questions You Will Definitely Be Asked

No matter what, be ready for these five. If you can answer these well, the interview goes
well.

1. **"Walk me through your search architecture."**
   → Session 5 (`10-hybrid-search-and-reranking.md`) is your anchor. Layer in Sessions 3, 4,
   6, and 7 for depth.

2. **"What happens end to end when a user searches?"**
   → Session 1 gives the skeleton; Sessions 5, 6, and 7 fill in the organs.

3. **"Why did you make [X] decision?"** (usually about hybrid search, reranking, pgvector, or Redis)
   → Every session has a "why this, not that" section. Decisions are the most important
   things to explain.

4. **"How would this scale?"**
   → Sessions 3, 4, 5, and 6 all have scaling sections.

5. **"What would you build next?"**
   → See your backlog: recommendations engine, image-to-pattern search, Ravelry OAuth,
   public project pages, observability (metrics/tracing). Hybrid retrieval and reranking
   are **done** — don't say you'd build those next.

---

## Cheat Sheet: the One Sentence Per Topic

Commit these to memory. Each is a launchpad for a longer explanation.

- **Full-stack app:** "A React front end talks to a FastAPI back end over REST, with PostgreSQL for permanent data, Redis for search caching, and two local AI models — all running in Docker."
- **Two-stage search:** "Stage 1 is fast hybrid retrieval — vector similarity, PostgreSQL full-text (BM25), and designer trigram matching fused with weighted scores. Stage 2 is a cross-encoder reranker that scores query-document pairs together on the top ~60 candidates for much higher accuracy."
- **Bi-encoder vs cross-encoder:** "The bi-encoder embeds query and document separately (fast, runs over the whole corpus). The cross-encoder scores them together (slow but accurate, only runs on the candidate pool)."
- **pgvector:** "A PostgreSQL extension that lets you store vectors and search by cosine similarity — nearest-neighbor search inside a regular database."
- **BM25 / full-text search:** "PostgreSQL's `tsvector` + GIN index lets me do keyword ranking with `ts_rank` — catches exact terms and designer names that pure semantic search might miss."
- **Designer trigram matching:** "The `pg_trgm` extension compares space-stripped query text to designer names, so 'Petite Knit' finds PetiteKnit patterns that full-text search tokenization would miss."
- **Redis cache:** "I cache the full ranked result list (up to 50 patterns) per query+filters for 30 minutes, so pagination is instant and identical queries skip both AI models and the database."
- **Auth:** "JWT stored in an httpOnly cookie — the browser sends it automatically, JavaScript can't read it (XSS-safe), and protected routes use a FastAPI dependency that decodes the token."
- **Singleton:** "Both AI models (bi-encoder and cross-encoder) load once at startup and are shared across all requests — loading per-request would add seconds of latency."
- **12-factor config:** "All secrets and server addresses come from environment variables — nothing is hardcoded — so the same code runs locally and in the cloud."

---

## Quick Reference: Key Code Paths

When an interviewer says "show me where that happens," know these files:

| Concern | File |
|---|---|
| Search entry point | `backend/app/api/patterns.py` → `semantic_search_patterns()` |
| Two-stage pipeline | `backend/app/search/pipeline.py` |
| Hybrid retrieval | `backend/app/search/hybrid_search.py` |
| Pure semantic (fallback) | `backend/app/search/semantic_search.py` |
| Cross-encoder reranking | `backend/app/services/reranking_service.py` |
| SQL filters | `backend/app/search/filters.py` |
| Bi-encoder embeddings | `backend/app/services/embedding_service.py` |
| Redis cache keys | `backend/app/cache/redis_client.py` |
| DB schema | `backend/app/db/models.py` |
| DB init (pgvector, full-text, trigram) | `backend/app/db/init_db.py` |
| Auth routes | `backend/app/auth/routes.py` |
| JWT + bcrypt | `backend/app/auth/security.py` |
| Seeding + cache invalidation | `backend/app/services/seeding.py` |
| 24h scheduler | `backend/app/scheduler.py` |
| Frontend API client | `frontend/src/api/client.ts` |
| Auth state | `frontend/src/auth/AuthContext.tsx` |
