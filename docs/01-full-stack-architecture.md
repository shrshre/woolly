# 01 — Full-Stack Architecture

**The big picture: how does Woolly's whole system fit together?**

Before drilling into any single piece, you need a clear mental map of the whole thing.
Every interview starts here, because interviewers test whether you understand the *system*,
not just the part you touched.

---

## What "full-stack" actually means

"Full-stack" just means you built *both* halves of a web application:

- **Front end** — the half the user sees and clicks on (the browser)
- **Back end** — the half that does the thinking, stores data, and enforces rules (the server)

Most modern web apps are split this way because it lets each half do what it's best at.
The browser is great at rendering beautiful, interactive UIs. The server is great at
storing data securely, running expensive computations, and talking to external services.

**Analogy — the restaurant:** the front end is the dining room (pretty, customer-facing).
The back end is the kitchen (does the real work, the customer never sees it). They
communicate through a waiter (the API). You built both rooms *and* defined the waiter's
communication protocol.

---

## The four services (what's running at once)

When you run `docker-compose up` on Woolly, four separate programs start at the same time
and work together:

```
┌─────────────────────────────────────────────────────────────┐
│                     User's browser                          │
│              (visits http://localhost:5173)                  │
└───────────────────────┬─────────────────────────────────────┘
                        │  HTTP requests / JSON responses
                        ▼
┌─────────────────────────────────────────────────────────────┐
│               React frontend (Vite dev server)              │
│                    localhost:5173                            │
│  - Renders the search UI                                    │
│  - Sends search queries to the backend                      │
└───────────────────────┬─────────────────────────────────────┘
                        │  HTTP requests / JSON responses
                        ▼
┌─────────────────────────────────────────────────────────────┐
│               FastAPI backend (Python/Uvicorn)              │
│                    localhost:8000                            │
│  - Receives text queries (+ filters, pagination)            │
│  - Receives photo uploads for visual search               │
│  - Checks Redis cache (text search)                       │
│  - Text: hybrid retrieval → cross-encoder reranking     │
│  - Visual: CLIP image embedding → nearest photos          │
│  - Auth (JWT cookies), saved patterns, projects           │
│  - Returns results as JSON                                  │
└─────────────┬──────────────────────────┬────────────────────┘
              │                          │
              ▼                          ▼
┌─────────────────────┐   ┌──────────────────────────────────┐
│  Redis (cache)      │   │  PostgreSQL + pgvector (database) │
│  localhost:6379     │   │  localhost:5432                   │
│  - Saves full ranked  │   │  - Stores 500+ patterns           │
│    text lists 30 min  │   │  - 384-dim text embeddings        │
│                       │   │  - 512-dim CLIP image embeddings  │
│                       │   │  - Full-text search (BM25)        │
│                       │   │  - Designer trigram matching      │
│                       │   │  - Users, saved patterns, projects│
└─────────────────────┘   └──────────────────────────────────┘
```

Each box is a separate process (a separate container in Docker). They talk to each other
over a private network.

---

## What "monorepo" means and why it matters

**Monorepo** = "mono" (one) + "repository" (codebase folder). Both the front end
(`frontend/`) and back end (`backend/`) live inside *one* project folder instead of two
separate GitHub repos.

**Analogy:** a duplex apartment. Two separate living units (front end, back end) under one
roof. They have their own interiors, but they share an address and a front door (the
project root).

**Why this is a useful choice for an interview:**
- Easier to keep front-end and back-end code in sync (one `git commit` can touch both)
- Simpler for a small team or solo developer
- One `docker-compose.yml` can start everything together
- Shared documentation, shared `.env` file

**The trade-off (shows nuance):** At large scale, monorepos need tooling (Turborepo, Nx)
to prevent slow builds. For a project at Woolly's current stage, it's the right call.

---

## How the pieces talk: REST APIs and HTTP

The front end and back end communicate through an **API** (Application Programming
Interface). Specifically, Woolly uses a **REST API** over **HTTP** — the same protocol
your browser uses to load any webpage.

### What HTTP is (really simply)

HTTP is a request-response language. The browser (or front end) sends a **request** and
the server sends back a **response**. Every request has:

- A **method** — what kind of action (`GET` = read, `POST` = create, `PUT/PATCH` = update,
  `DELETE` = delete)
- A **URL** — which resource you're acting on (`/patterns/semantic-search`)
- Optional **query parameters** — extra filters tacked onto the URL (`?q=cozy+sweater`)
- Optional **body** — data sent with the request (not used for GET)

Every response has:
- A **status code** — a number that signals success or failure (200 = OK, 404 = not found,
  500 = server broke)
- A **body** — usually JSON data in modern APIs

### Woolly's endpoints

| What the front end sends | What it's asking | What comes back |
|---|---|---|
| `GET /health` | "Are you alive?" | `{"status": "ok"}` |
| `GET /patterns/search?q=hat` | "Keyword search for hat via Ravelry" | List of pattern objects |
| `GET /patterns/semantic-search?q=cozy+sweater&craft=knitting&offset=0&limit=10` | "Hybrid search + rerank, with filters and pagination" | Ranked pattern list with `rerank_score`, `total` |
| `POST /patterns/visual-search` (multipart image file) | "Find patterns whose photos look like this" | Ranked pattern list (CLIP similarity as `rerank_score`) |
| `GET /patterns/filters` | "What craft/category options exist?" | `{crafts: [...], categories: [...]}` |
| `POST /auth/register` | "Create an account" | User object + httpOnly JWT cookie |
| `POST /auth/login` | "Log in" | User object + cookie |
| `GET /auth/me` | "Who am I?" | User object or 401 |
| `POST /patterns/{id}/save` | "Bookmark this pattern" | 204 (auth required) |
| `GET /users/me/library` | "My saved patterns" | Pattern list (auth required) |
| `GET /projects` | "My WIP projects" | Project list (auth required) |

**Analogy for REST:** think of URLs as addresses for resources. `GET /patterns/search` is
like calling a library's phone number and saying "search for X." The library (back end)
looks it up and reads you the results. That's it.

---

## What JSON is

**JSON** (JavaScript Object Notation) is the format both sides use to talk to each other.
It's just text that looks like a Python dictionary:

```json
{
  "query": "cozy winter sweater",
  "patterns": [
    {
      "id": 12345,
      "name": "Chunky Ribbed Pullover",
      "designer": "Jane Smith",
      "free": true,
      "ravelry_url": "https://www.ravelry.com/patterns/library/chunky-ribbed-pullover"
    }
  ],
  "total": 1
}
```

The back end produces this JSON. The front end receives it and uses it to render pattern
cards on screen. JSON is universal — any language can read and write it — which is why
it became the standard.

---

## The request lifecycle: one full search, step by step

This is the answer to the classic "walk me through what happens" question.

**Step 1:** User types "cozy winter sweater" and presses enter.

**Step 2:** The React front end runs `searchPatterns("cozy winter sweater")` in
`frontend/src/api/client.ts`. This sends an HTTP request:
```
GET http://localhost:8000/patterns/semantic-search?q=cozy+winter+sweater
```

**Step 3:** The FastAPI back end receives the request. It checks Redis: "Have I computed the
full ranked list for this query + filters recently?"
- If **yes (cache hit):** slice the cached list for the requested page. Super fast.
- If **no (cache miss):** keep going.

**Step 4 (cache miss) — Stage 1, hybrid retrieval:** Three search legs run in parallel inside
PostgreSQL:
- **Semantic:** embed the query, find nearest neighbors via pgvector
- **Keyword:** full-text search (BM25) on the `search_vector` column
- **Designer:** trigram similarity on designer names (catches "Petite Knit" → PetiteKnit)
Scores are fused with weights (0.6 / 0.25 / 0.15) → top 60 candidates.

**Step 5 — Stage 2, reranking:** A cross-encoder scores each (query, pattern) pair together
and reorders the candidates. Returns up to 50 results with `rerank_score` and relevance labels.

**Step 6:** Save the full ranked list in Redis for 30 minutes (keyed by query + filters).

**Step 7:** Slice the first page (`offset=0, limit=10`) and send as JSON to the front end.

**Step 8:** React renders a `PatternCard` for each pattern, with relevance bars and labels.
Page 2 is a cache hit — no recompute.

That's the whole journey. For the deep dive, read `10-hybrid-search-and-reranking.md`.
Practice saying this out loud until it's fluent.

### Visual search lifecycle (photo upload)

**Step 1:** User clicks the photo button and picks an image.

**Step 2:** React POSTs the file as multipart form data to
`/patterns/visual-search` (see `visualSearchPatterns` in `client.ts`).

**Step 3:** FastAPI validates type/size, then CLIP embeds the image (lazy-loads the
~600MB model on first use). Embedding uses a **multi-crop blend**: full frame + center
crop, so matching prefers the garment, not the background.

**Step 4:** Postgres finds nearest neighbors on `image_embedding` (512-dim) via cosine
distance. No hybrid legs, no cross-encoder, no Redis cache — one modality, one stage.

**Step 5:** JSON comes back shaped like text results (`rerank_score` = CLIP similarity)
so the same `PatternCard` UI works. Analytics logs `search_type="visual"`.

Deep dive: `12-visual-search-clip.md`.

---

## CORS — what it is and why Woolly needs it

**CORS** = Cross-Origin Resource Sharing. This is a browser security rule that says:
"A webpage loaded from address A is not allowed to make requests to address B — unless
address B explicitly says it's okay."

In Woolly's case:
- The front end is at `http://localhost:5173`
- The back end is at `http://localhost:8000`

These are different "origins" (different ports = different origins). Without CORS config,
the browser would block the front end from calling the back end — even though they're both
on your machine.

The fix in `backend/app/main.py`:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,  # ["http://localhost:5173"]
    allow_methods=["*"],
    allow_headers=["*"],
)
```

This tells the browser: "The back end at port 8000 gives permission to be called from
localhost:5173." The browser accepts this and allows the requests.

**Analogy:** CORS is like a club's guest list policy. The front end wants to get into the
back end's "club." By default the bouncer (browser) says no because they're from a different
address. The `allow_origins` config is the back end texting the bouncer: "yeah, let
localhost:5173 in."

In production, you'd list your real deployed front-end URL instead.

---

## Environment variables and the `.env` file

Woolly's config (database passwords, Ravelry credentials, Redis URL) is never hardcoded
in the source code. Instead it's stored in a `.env` file:

```
RAVELRY_USERNAME=my_app_username
RAVELRY_PASSWORD=secret_password
DATABASE_URL=postgresql://woolly:woolly@db:5432/woolly
REDIS_URL=redis://redis:6379/0
```

**Why not hardcode?** Three reasons:
1. **Security:** you'd accidentally commit your passwords to GitHub.
2. **Flexibility:** the same code runs locally (pointing to localhost) and in production
   (pointing to AWS) just by changing the `.env` file — no code changes needed.
3. **Best practice:** this is the "12-factor app" principle. More in
   `08-external-apis-design-patterns.md`.

The `.gitignore` file lists `.env` so it's never committed. The `.env.example` file shows
the shape (with empty values) so teammates know what variables to provide.

---

## The monorepo folder structure

```
woolly/
├── docker-compose.yml        # master switch — starts all 4 services
├── .env                      # secrets (never committed)
├── .env.example              # shape of .env (safe to commit)
├── README.md                 # how to run it
│
├── backend/                  # Python / FastAPI
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app/
│       ├── main.py           # entrypoint, lifespan (text AI models + scheduler)
│       ├── config.py         # env vars → Settings
│       ├── scheduler.py      # 24h incremental re-seed
│       ├── api/
│       │   ├── patterns.py   # text search, visual search, save, filters
│       │   ├── projects.py   # project CRUD
│       │   └── users.py      # library endpoint
│       ├── auth/
│       │   ├── routes.py     # register, login, logout, me
│       │   ├── security.py   # bcrypt + JWT
│       │   └── dependencies.py # get_current_user
│       ├── services/
│       │   ├── ravelry_client.py
│       │   ├── embedding_service.py  # bi-encoder (text stage 1)
│       │   ├── reranking_service.py  # cross-encoder (text stage 2)
│       │   ├── clip_service.py       # CLIP visual search (lazy load)
│       │   └── seeding.py            # fetch, embed, upsert, image backfill, clear cache
│       ├── search/
│       │   ├── pipeline.py         # orchestrates hybrid → rerank (text only)
│       │   ├── hybrid_search.py    # vector + BM25 + designer fusion
│       │   ├── semantic_search.py  # pure vector (fallback)
│       │   └── filters.py          # SQL filter helpers
│       ├── cache/
│       │   └── redis_client.py
│       └── db/
│           ├── models.py     # Pattern (+ image_embedding), User, Project, …
│           ├── session.py
│           └── init_db.py    # pgvector, full-text, trigram, image column
│
└── frontend/                 # React / TypeScript / Vite
    ├── Dockerfile
    ├── package.json
    └── src/
        ├── App.tsx           # React Router, providers, routes
        ├── api/client.ts     # typed fetch wrapper (auth, search, visual, projects)
        ├── auth/
        │   ├── AuthContext.tsx
        │   └── SavedPatternsContext.tsx
        ├── pages/
        │   ├── Home.tsx      # text search + photo upload + filters + pagination
        │   ├── Library.tsx   # saved patterns (protected)
        │   ├── Projects.tsx  # WIP tracker (protected)
        │   ├── StitchCounter.tsx
        │   ├── Login.tsx / SignUp.tsx
        │   └── GridMaker.tsx
        ├── components/
        │   ├── SearchBar.tsx, FilterBar.tsx, PatternCard.tsx
        │   ├── Nav.tsx, ProtectedRoute.tsx, SkeletonCard.tsx
        │   └── ...
        └── styles.css
```

Each folder is a **concern** (a responsibility). Notice how the back end organizes by what
something *does* — `services/` for external integrations, `search/` for search logic,
`db/` for database, `api/` for HTTP routes. This is called **separation of concerns** and
it makes the code much easier to navigate, test, and change.

---

## Interview questions for this topic

**Q: Walk me through your system architecture.**
A: "Woolly is a monorepo with a React front end and a FastAPI back end. Text search uses
a two-stage pipeline: hybrid retrieval combining pgvector semantic search, PostgreSQL
full-text BM25, and designer trigram matching, then cross-encoder reranking on the top
candidates. The full ranked list is cached in Redis per query and filters; pagination
slices that cache. Separately, visual search lets users upload a photo — CLIP embeds it
and we find nearest pattern photos in a 512-d pgvector column. Text models load at
startup; CLIP loads lazily because it's heavy. Auth uses JWT in httpOnly cookies for
saved patterns and project tracking. A background scheduler re-seeds patterns every 24
hours. Everything runs in Docker via docker-compose."

**Q: Why a monorepo?**
A: "For a project at this scale with one developer, a monorepo keeps front end and back end
synchronized, lets docker-compose start everything together, and reduces overhead from
managing two separate repos. At larger scale with multiple teams, you'd weigh the build-time
trade-offs more carefully."

**Q: What is CORS and why does Woolly need it?**
A: "CORS is a browser security rule that blocks web pages from making requests to different
origins (domain + port combinations). My front end on port 5173 and back end on port 8000
are different origins, so I configure the FastAPI CORS middleware to explicitly allow
requests from the front-end origin."

**Q: What travels between the front end and back end?**
A: "HTTP requests and JSON responses. The front end sends GET requests with query parameters,
and the back end responds with JSON objects containing pattern data. The shapes of these
objects are defined as Pydantic models on the back end and as TypeScript interfaces on the
front end, so both sides agree on the contract."
