# Product Requirements Document: Woolly

**Version:** 0.1 (Week 1 Scaffold)
**Owner:** Shreya Sanapala
**Status:** Active — Week 1 build only

---

## ⚠️ Scope Notice for Claude Code

**Build ONLY the Week 1 deliverables defined in Section 7.** The full product vision, roadmap, and future architecture are documented in this PRD so you understand the direction and scaffold accordingly — but do **not** implement anything beyond Week 1. Do not build semantic search, embeddings, the project tracker, the stitch counter, the pixel grid maker, user accounts, or AWS deployment in this run. Structure the codebase so those things can be added cleanly later, but leave them unimplemented.

If you find yourself about to write embedding logic, vector search, React UI beyond a bare results display, or any AWS config, stop — that is out of scope for this run.

---

## 1. Overview

Woolly is a full-stack web application that serves as a crafting companion for fiber artists (crochet and knitting). It combines pattern discovery, project tracking, and in-progress crafting tools into a single product, replacing the fragmented workflow crafters use today (Ravelry for patterns, notes apps for counts, Pinterest for inspiration, physical notebooks for tracking).

The headline technical feature is a **semantic search layer** over the Ravelry pattern API, allowing natural-language pattern discovery that Ravelry's own keyword search does not support. Additional differentiating features include a voice-activated stitch counter and a colorwork pixel grid maker.

**This PRD scopes the Week 1 foundation only:** project scaffolding and Ravelry API integration. Everything else is documented as future context.

---

## 2. Goals & Non-Goals

### Goals (overall product)
- Provide semantic, intent-based pattern search over Ravelry data
- Give crafters a single place to track works-in-progress (WIPs)
- Offer in-craft tools (voice stitch counter, colorwork grid maker) that drive daily active usage
- Ship a real, deployed product with real users from the fiber arts community

### Non-Goals
- Woolly does **not** host or sell pattern files. It is a discovery and companion layer. All pattern purchases redirect to Ravelry or the designer's own site.
- Woolly does **not** reproduce or cache pattern *content* (instructions, PDFs). It caches search results and metadata only, per Ravelry API terms.
- Woolly is not a marketplace or a social network first — social features are secondary and additive.

---

## 3. Target Users

- Crochet and knitting enthusiasts who find Ravelry's search frustrating
- Crafters who currently juggle multiple tools to manage projects
- Active members of communities like r/crochet, r/knitting, and Ravelry forums

---

## 4. Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python, FastAPI |
| Database | PostgreSQL (with pgvector extension — *future*) |
| Cache | Redis |
| ORM | SQLAlchemy |
| Frontend | React + TypeScript |
| Embeddings (future) | sentence-transformers, `all-MiniLM-L6-v2`, run **locally** (no external embedding API) |
| Auth | JWT (basic email/password for MVP); Ravelry **basic read-only auth** for API access |
| Containerization | Docker + docker-compose |
| Eventual deployment | AWS (ECS/EC2 for API, RDS for PostgreSQL, ElastiCache for Redis, S3 for project photos, CloudFront for frontend) |

### Important stack decisions
- **Embeddings run locally**, not via a paid API. Use `all-MiniLM-L6-v2` (384-dimensional vectors). *(Future — not Week 1.)*
- **Deployment is local Docker now, but the structure must be AWS-ready** so migration is smooth. Use environment-based configuration (no hardcoded localhost values), 12-factor principles, and keep the app stateless where possible.
- **Ravelry auth is basic read-only** for the MVP. The code should isolate the Ravelry client behind a service/interface boundary so it can be swapped to **OAuth later** (when users link their own Ravelry accounts for real-user launch).
- **Monorepo** structure: backend and frontend live in one repository.

---

## 5. Repository Structure (Monorepo)

Scaffold the repository with this shape. Folders for future features may be created empty or with placeholder READMEs, but **do not implement their contents** this run.

```
woolly/
├── docker-compose.yml
├── .env.example
├── README.md
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── app/
│   │   ├── main.py                # FastAPI entrypoint
│   │   ├── config.py              # env-based settings (AWS-ready, no hardcoded values)
│   │   ├── api/
│   │   │   └── patterns.py        # Week 1: /patterns/search proxy route
│   │   ├── services/
│   │   │   └── ravelry_client.py  # Week 1: Ravelry API client (basic auth), behind an interface
│   │   ├── cache/
│   │   │   └── redis_client.py    # Week 1: Redis connection + helpers
│   │   ├── db/                    # placeholder for future SQLAlchemy models
│   │   ├── search/                # placeholder for future embedding/semantic search
│   │   └── auth/                  # placeholder for future JWT user auth
│   └── tests/
│       └── test_ravelry_client.py
└── frontend/
    ├── Dockerfile
    ├── package.json
    ├── tsconfig.json
    └── src/
        ├── App.tsx                # Week 1: minimal — calls search endpoint, lists raw results
        ├── api/
        │   └── client.ts          # Week 1: typed fetch wrapper for backend
        └── components/            # placeholder for future UI components
```

---

## 6. Data & API Notes (Week 1)

### Ravelry API
- Register at `ravelry.com/pro/developer` and create an app with **basic authentication, read-only access**.
- Endpoints needed for Week 1: `patterns/search.json`. (Future: `patterns/{id}.json`, `pattern_categories`.)
- Store credentials in environment variables (`RAVELRY_USERNAME`, `RAVELRY_PASSWORD` or API key/secret per Ravelry's scheme). Never commit them. Provide them in `.env.example` as empty placeholders.
- **Attribution & caching:** credit Ravelry, link back to pattern pages, and cache only search result metadata (not pattern content). Review Ravelry's API terms before expanding caching behavior.

### Redis caching
- Cache `patterns/search` responses keyed by the normalized query string.
- TTL: 1 hour is acceptable for Week 1 (pattern data changes infrequently).

---

## 7. ✅ WEEK 1 DELIVERABLES (Build These Only)

**End-of-week goal:** Ravelry pattern data flows through the FastAPI backend (cached in Redis) to a minimal React frontend that displays raw results. Auth and search intelligence come later.

1. **Project scaffolding**
   - Monorepo per Section 5
   - `docker-compose.yml` running four-ish services as needed: backend (FastAPI), frontend (React dev server), PostgreSQL, Redis. PostgreSQL can run even though it's unused this week, so the structure is ready.
   - `.env.example` with all required environment variables as empty placeholders
   - A `README.md` with local setup instructions (how to run `docker-compose up`, where to put Ravelry credentials)
   - Environment-based config in `backend/app/config.py` — no hardcoded hosts/ports/secrets (AWS-ready)

2. **Ravelry API integration**
   - `ravelry_client.py`: a service-layer client using **basic read-only auth**, isolated behind a clean interface so it can be swapped to OAuth later
   - A `GET /patterns/search?q=...` FastAPI route that proxies Ravelry's pattern search
   - Redis caching of search responses (1-hour TTL), keyed by query
   - Basic error handling (Ravelry down, bad/empty query, rate limit response)
   - One simple test in `tests/` confirming the client parses a search response correctly (can mock the HTTP call)

3. **Minimal frontend**
   - A single search input that calls `GET /patterns/search`
   - Display raw results as a plain list (pattern name + designer is enough). **Ugly is acceptable** — no styling work, no pattern cards, no filters. This exists only to confirm the end-to-end pipeline works.
   - Typed API client in `frontend/src/api/client.ts`

### Week 1 Definition of Done
- `docker-compose up` brings up the full stack locally
- Searching a term in the frontend returns real Ravelry patterns via the backend
- A repeated identical search is served from Redis cache (verifiable in logs)
- Ravelry credentials are read from env vars, not hardcoded
- The repo structure anticipates future features without implementing them

---

## 8. Future Roadmap (Context Only — DO NOT BUILD)

This section exists so the scaffold is structured intelligently. **None of this is in scope for the current run.**

### Week 2 — Semantic Search
- Add pgvector extension to PostgreSQL
- `patterns` table with a `vector(384)` embedding column
- Local embedding pipeline using `sentence-transformers` / `all-MiniLM-L6-v2`
- Seed ~500–1000 patterns and generate embeddings
- Cosine-similarity search via pgvector `<=>` operator, returning top results

### Week 3 — Search UI
- Polished pattern cards (name, designer, difficulty, image linked from Ravelry, "View on Ravelry" button)
- Filters: craft type, difficulty, category (filter in SQL, then rank by similarity)
- Loading/empty/error states

### Week 4 — Accounts + Library + Deploy
- JWT email/password auth (carry over from existing ticketing-platform boilerplate)
- Save patterns to a personal library (`saved_patterns` join table)
- Deploy publicly

### Month 2 — Project Tracker + Voice Stitch Counter
- Project tracker: pattern + yarn + needle/hook + per-session notes + progress % + WIP photos; statuses (queue / active / hibernating / finished)
- Voice-activated stitch counter using the Web Speech API (commands: "count", "next row", "undo", "reset"); counts saved to the active project

### Month 3+ — Differentiation & Scale
- Colorwork pixel grid maker (canvas-based, manual painting; export PNG/PDF)
- Image-to-grid conversion (color quantization + downsampling — the ML feature)
- Recommendations from saved-pattern history (collaborative filtering)
- Minimal social: opt-in public project pages with comments/hearts (organic growth mechanism)
- **AWS deployment**: ECS/EC2 + RDS + ElastiCache + S3 + CloudFront
- **Ravelry OAuth** so users can link their own accounts
- **Freemium model**: free tier (search, limited saved patterns, stitch counter); paid tier (~$4–6/mo: unlimited saves, pixel grid maker, image-to-grid, photo uploads, public sharing). Feature-gating via feature flags (LaunchDarkly). Stripe integration deferred until there is validated user demand.

---

## 9. Engineering Principles

- **Honesty in scope:** build only what's defined; leave placeholders clearly marked.
- **Swappable boundaries:** the Ravelry client and (future) embedding provider sit behind interfaces so auth methods and models can change without rewrites.
- **AWS-ready from day one:** env-based config, stateless services, Dockerized — so the eventual cloud migration is mechanical, not a rewrite.
- **Understand before extending:** each iteration should be small enough to fully read and explain. (This is intentional — the developer wants to defend every layer in interviews.)