# Woolly — The Plain-English Interview Guide

This document explains everything about the Woolly project in simple language, with lots of
metaphors. The goal: after reading this, you can confidently explain the project in a
software engineering interview and defend any layer of it. Read it top to bottom once, then
skim the "Interview cheat sheet" at the end before you walk in.

---

## 1. The 30-second pitch (memorize this)

> "Woolly is a full-stack web app that helps knitters and crocheters find patterns using
> plain-English search. Instead of matching exact keywords like a normal search box, it
> understands the *meaning* of what you type — so 'cozy winter sweater' finds relevant
> patterns even if none of them literally contain those words. It pulls pattern data from
> Ravelry (the big crafting site), runs the search using AI embeddings stored in a
> PostgreSQL vector database, caches results in Redis for speed, and shows them in a polished
> React front end. The whole thing runs in Docker."

That's the elevator pitch. The rest of this doc unpacks every phrase in it.

**The core problem it solves:** Ravelry's own search is keyword-based and frustrating. If you
search "quick gift for beginners," it looks for those exact words. Woolly understands
*intent*. That "meaning-based search" is the headline technical feature.

---

## 2. The big-picture metaphor: a restaurant

The easiest way to hold the whole system in your head is to imagine a **restaurant**:

- **The front end (React)** is the *dining room* — the pretty part the customer sees and
  interacts with. Menus, tables, lighting.
- **The back end (FastAPI)** is the *kitchen* — where the actual work happens. The customer
  never goes in here; they just send orders and receive plates.
- **The database (PostgreSQL)** is the *pantry/walk-in fridge* — long-term storage of
  ingredients (pattern data).
- **The cache (Redis)** is the *warming shelf* right by the pass — food that was just cooked
  and can be handed out instantly if someone orders the same thing again.
- **Ravelry's API** is the *wholesale supplier* — where the kitchen originally sourced its
  ingredients.
- **Docker** is the *building itself with standardized rooms* — so you can rebuild the exact
  same restaurant anywhere (your laptop, a cloud server) without surprises.

Keep this metaphor in your back pocket. Every technical piece below maps onto it.

---

## 3. What "full-stack monorepo" means

**Full-stack** = you built both halves: the part users see (front end) and the part that does
the thinking (back end).

**Monorepo** = "mono" (one) + "repo" (repository/project folder). Both halves live in **one**
project folder instead of two separate ones. Metaphor: a duplex house — two units (frontend,
backend) under one roof, sharing a front door. Easier to keep them in sync.

The folder layout:

```
woolly/
├── docker-compose.yml     # the master switch that starts everything at once
├── backend/               # the kitchen (Python)
├── frontend/              # the dining room (React/TypeScript)
└── PRD files/             # the design + planning documents (not code)
```

---

## 4. The tech stack, translated

| The buzzword | What it actually is | Metaphor |
|---|---|---|
| **Python + FastAPI** | The language + framework for the back end | The kitchen and its layout/workflow |
| **React + TypeScript** | The library + language for the front end | The dining room and its furniture |
| **PostgreSQL** | The main database | The walk-in pantry |
| **pgvector** | A PostgreSQL add-on for "meaning math" | A special shelf in the pantry organized by *similarity* |
| **Redis** | An in-memory cache (super fast temporary storage) | The warming shelf by the pass |
| **sentence-transformers** | The AI model that turns text into numbers | A translator that converts sentences into "meaning coordinates" |
| **Docker / docker-compose** | Packaging + orchestration | Prefab standardized rooms + one master switch |
| **Ravelry API** | The external data source | The wholesale supplier |
| **Vite** | The front-end dev server + build tool | The tool that instantly rebuilds the dining room when you rearrange it |

If someone asks "why these?", short honest answers:
- **FastAPI**: fast to write, gives you free auto-generated API docs, great for async I/O.
- **React**: industry standard for interactive UIs, huge ecosystem.
- **PostgreSQL + pgvector**: one database can do both normal data *and* AI vector search — no
  need for a separate specialized vector database.
- **Redis**: dead simple, incredibly fast, perfect for caching.
- **Local AI model**: it's free and private — no paying OpenAI per search.

---

## 5. The star of the show: semantic search (this is what impresses interviewers)

This is the feature to talk about most. Take your time understanding it — it's the heart of
the project.

### 5.1 The problem with normal search

Normal ("keyword") search is like a **librarian who only does exact-word matching**. Ask for
"comfy sweater" and if a book's title says "cozy pullover," the librarian shrugs — no word
matched. Useless, even though those mean the same thing.

### 5.2 The idea: turn meaning into numbers ("embeddings")

Computers can't compare *meanings*, but they're great at comparing *numbers*. So the trick is:
**convert every piece of text into a list of numbers that represents its meaning.** That list
of numbers is called an **embedding** (or a "vector").

**Metaphor — the meaning map:** Imagine a giant map where every possible phrase is a pin.
Phrases with similar meaning get pinned close together. "Cozy sweater," "warm pullover," and
"snug jumper" all end up in the same neighborhood. "Race car" is on the other side of town.

Each pin's location is described by coordinates. On a real map you'd need 2 numbers (latitude,
longitude). Meaning is way more complex, so Woolly uses **384 numbers** per phrase. (You can't
picture 384 dimensions — nobody can — but the math works the same as 2D: things close together
are similar.)

The tool that does this conversion is an AI model called **`all-MiniLM-L6-v2`** (from the
`sentence-transformers` library). Think of it as a **translator that reads a sentence and
gives you its GPS coordinates on the meaning map.** It runs locally on your own machine — free
and private, no external API calls.

Relevant code (the translator):

```33:36:backend/app/services/embedding_service.py
def embed_text(text: str) -> list[float]:
    """Return a 384-dimensional embedding for the given text."""
    vector = get_model().encode(text, normalize_embeddings=True)
    return vector.tolist()
```

### 5.3 How Woolly uses it — two phases

**Phase A — Preparation (done ahead of time, called "seeding"):**
Woolly fetches ~500 real patterns from Ravelry, and for each one, runs its text (name +
description + tags) through the translator to get its 384-number embedding. It saves the
pattern *and* its embedding into the PostgreSQL database. Metaphor: **pinning every pattern
onto the meaning map ahead of time**, so they're ready to search.

This happens in a one-time script, `backend/scripts/seed_patterns.py`. It's run manually — not
automatically — which is a legitimate design choice for this stage of the project.

**Phase B — Searching (happens live when a user types):**
1. User types "cozy winter sweater."
2. Woolly runs *that phrase* through the same translator → gets its coordinates on the map.
3. Woolly asks the database: **"which pattern pins are closest to this spot?"**
4. It returns the nearest ones, ranked by closeness.

The "closeness" measurement is called **cosine similarity** — don't overthink it, it's just a
standard way to measure "how close are these two points in meaning-space." Closer = more
similar. The code turns it into a `similarity_score` from 0 to 1 (higher = better match).

Relevant code (the actual search):

```25:37:backend/app/search/semantic_search.py
    query_vector = embed_text(query)

    db.execute(text(f"SET LOCAL ivfflat.probes = {IVFFLAT_PROBES}"))

    # cosine_distance = 1 - cosine_similarity; ORDER BY distance == most similar first
    distance = Pattern.embedding.cosine_distance(query_vector)
    rows = (
        db.query(Pattern, distance.label("distance"))
        .filter(Pattern.embedding.isnot(None))
        .order_by(distance)
        .limit(limit)
        .all()
    )
```

In English: *"Turn the query into coordinates, then get the patterns ordered from closest to
farthest, and give me the top N."*

### 5.4 The clever database bit ("pgvector" and the index)

Storing 384-number lists and comparing them fast is a specialized job. Rather than bolt on a
whole separate "vector database" product, Woolly uses **pgvector**, an extension that teaches
regular PostgreSQL how to store and compare these vectors. **One database, two jobs** —
simpler to run and reason about. Good thing to mention as a pragmatic decision.

There's also an **index** (called IVFFlat). An index is like the **tabbed dividers in a
recipe binder** — instead of flipping through all 500 patterns one by one, the database can
jump roughly to the right section. It's *approximate* (trades a tiny bit of accuracy for a lot
of speed), which is why the code bumps up a setting called `probes` to 10 — that tells it to
check a few nearby sections so it doesn't miss good matches on a small dataset. If asked "what
would you improve," you can say: on a small 500-row set the index barely matters, but it's the
right foundation for scaling to millions of patterns.

---

## 6. Walking through one search, end to end (the "data flow" answer)

Interviewers love "walk me through what happens when a user does X." Here's the full journey,
with the restaurant metaphor:

1. **User types "cozy winter sweater" and hits enter.** (Customer places an order in the
   dining room.)
2. **The React front end** calls the back end at `GET /patterns/semantic-search?q=cozy...`.
   (Waiter carries the order ticket to the kitchen.)
   - Code: `frontend/src/api/client.ts` → `searchPatterns()`.
3. **The back end first checks Redis (the cache).** "Have I answered this exact search
   recently?" (Chef glances at the warming shelf.)
   - **Cache HIT** → return the saved answer instantly. Done. (Grab the ready plate.)
   - **Cache MISS** → keep cooking.
4. **Convert the query to an embedding** using the local AI model. (Translate the order into
   meaning-coordinates.)
5. **Query PostgreSQL/pgvector** for the closest pattern pins. (Fetch the best-matching
   ingredients from the pantry.)
6. **Save the answer to Redis** with a 30-minute expiry, so the next identical search is
   instant. (Put a copy on the warming shelf.)
7. **Send the results back** as JSON to the front end.
8. **React renders pattern cards** — image, title, designer, difficulty badge, free/paid
   badge, and a "View on Ravelry" link. (Waiter plates it beautifully and serves it.)

The code that orchestrates steps 3–7:

```89:114:backend/app/api/patterns.py
    cache_key = semantic_cache_key(query)
    cached = await get_cached(cache_key)
    if cached is not None:
        return SemanticSearchResult.model_validate_json(cached)

    try:
        rows = run_semantic_search(db, query, limit=limit)
    except Exception as exc:  # DB down, patterns table missing, etc.
        logger.error("Semantic search failed: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="Semantic search is unavailable. Has the database been seeded?",
        ) from exc
```

---

## 7. Caching with Redis (the speed trick)

**What it is:** Redis stores answers in memory (RAM) instead of on disk, which makes it
lightning fast. Woolly saves each search result in Redis keyed by the search text.

**Metaphor:** the warming shelf by the kitchen pass. The first person to order the soup waits
for it to be cooked (slow path: AI + database). The next five people who order the same soup
get it handed over instantly from the shelf. After 30 minutes the shelf is cleared (the result
"expires," called a **TTL** — time to live) so data doesn't get stale.

**Why it matters in an interview:** it shows you think about performance and cost. Running the
AI model and hitting the database on *every* identical search would be wasteful.

**A nice detail to mention:** the caching is written to **fail gracefully**. If Redis is down,
the code logs a warning and just does the slow path instead of crashing. Resilience.

```31:41:backend/app/cache/redis_client.py
async def get_cached(key: str) -> str | None:
    try:
        value = await get_redis().get(key)
    except redis.RedisError as exc:
        logger.warning("Redis GET failed (%s); falling through to Ravelry.", exc)
        return None
```

There are actually **two caches** with different expiry times:
- Ravelry keyword search results: 1 hour.
- Semantic search results: 30 minutes.

---

## 8. Talking to Ravelry (the external data source)

Ravelry is the huge existing site for knitters/crocheters. Woolly doesn't own pattern data —
it borrows it through Ravelry's **API** (Application Programming Interface — basically a
official "data vending machine" that other apps are allowed to request from).

Key design decisions worth explaining:

- **Woolly never hosts pattern files or images.** It stores only *metadata* (name, designer,
  link, etc.) and links back to Ravelry, respecting Ravelry's terms. Images load directly from
  Ravelry's servers. Metaphor: Woolly is a **matchmaker/directory**, not a store — it points
  you to the pattern, it doesn't sell it.

- **The Ravelry client is hidden behind an "interface."** This is a professional pattern worth
  name-dropping. There's an abstract `PatternProvider` "contract," and `RavelryClient` fulfills
  it. Metaphor: the kitchen orders from "a supplier" through a standard order form — if you
  later switch suppliers (e.g. change from basic login to full OAuth when users link their own
  accounts), you just swap the supplier; the rest of the kitchen doesn't change. This is the
  **swappable boundary** principle.

```52:56:backend/app/services/ravelry_client.py
class PatternProvider(ABC):
    """Interface boundary for pattern search providers (swappable auth/backends)."""

    @abstractmethod
    async def search_patterns(self, query: str, page_size: int = 20) -> PatternSearchResult: ...
```

- **Real error handling.** The client distinguishes between "Ravelry is down" (503), "we got
  rate-limited" (429), and "our credentials are bad" (502), and reports each clearly instead
  of a generic crash. Interviewers like seeing this.

---

## 9. The back end in a bit more depth (FastAPI)

**FastAPI** is the Python framework that defines the kitchen's "order windows" — the URLs the
front end can call. Each URL is called an **endpoint** or **route**.

The three endpoints:

| Endpoint | What it does | Restaurant analogy |
|---|---|---|
| `GET /health` | Returns `{"status": "ok"}` — a heartbeat check | "Are you open?" sign |
| `GET /patterns/search` | Keyword search proxied straight from Ravelry (Week 1 feature) | Order from the supplier directly |
| `GET /patterns/semantic-search` | The AI meaning-based search (the star) | The house specialty |

A few professional patterns present in the back end you can mention:

- **Dependency injection** (`Depends(...)`): instead of each function creating its own database
  connection or settings, FastAPI "hands them" what they need. Metaphor: a **prep cook who
  places the right tools and ingredients at your station** before you start, rather than you
  running to fetch them. Makes code easier to test and swap.

- **Startup lifecycle (`lifespan`)**: when the app boots, it sets up the database and
  **pre-loads the AI model once** (loading it takes a few seconds). Metaphor: **turning on the
  ovens and prepping the mise en place before opening**, so no customer waits for warm-up. The
  model is loaded as a **singleton** — one shared copy for the whole app, protected so two
  requests don't try to load it at once.

```20:27:backend/app/main.py
@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        init_db()
    except Exception as exc:
        logger.warning("Database init failed (%s); semantic search will be unavailable.", exc)
    get_model()  # load the embedding model once at startup, not per request
    yield
```

- **12-factor / environment-based config**: no passwords or server addresses are hardcoded.
  They come from environment variables (a `.env` file locally). Metaphor: the recipe says "add
  salt to taste" rather than baking a fixed amount in — so the same code runs on your laptop or
  in the cloud just by changing the settings, not the code. This is what people mean by
  "AWS-ready."

- **Pydantic schemas**: these define the exact shape of data going in and out (e.g. a pattern
  *must* have an id and name). Metaphor: a **standardized order ticket format** so the kitchen
  and dining room never miscommunicate. Bonus: it auto-generates interactive API docs at
  `/docs`.

---

## 10. The front end in a bit more depth (React)

The front end is a **single-page app** built with React + TypeScript, bundled by Vite.

- **Single-page** means there's really one screen (`App.tsx`) — the search page. No multi-page
  navigation yet. Metaphor: a one-room café, not a multi-floor building.

- **Components** are reusable UI building blocks. Woolly has:
  - `SearchBar` — the input box.
  - `PatternCard` — one result (image, title, designer, badges, save button, Ravelry link).
  - `Badge` — the little colored difficulty/price pills.
  - `SkeletonCard` — a gray placeholder shown *while loading* so the page doesn't look frozen.
    Metaphor: the **"your food is being prepared" placeholder** — feels faster even if it isn't.

- **State** (the app's memory of what's happening) is kept simple with React's built-in
  `useState`: the current query, the results, whether it's loading, and any error. No heavy
  state-management library — appropriate for the app's size. Metaphor: a **small notepad** at
  the host stand rather than a full reservation computer system.

- **Talking to the back end**: one typed function, `searchPatterns()`, in
  `frontend/src/api/client.ts`. It calls the semantic-search endpoint and knows how to surface
  friendly errors.

- **The design system**: there's a deliberate visual identity ("cozy artisan" — burgundy +
  cream, serif titles). All colors are hardcoded hex so it looks identical everywhere and never
  accidentally inherits a browser's dark mode. This is documented in
  `PRD files/woolly-design-doc.md`.

**Honest caveat to know:** the "Save to library," "Sign in," "My library," and "Projects"
buttons are **visual placeholders** — they don't do anything yet because user accounts aren't
built. If asked, say so plainly; it's a scoped MVP.

---

## 11. Docker (how it all runs together)

**Docker** packages each service into a **container** — a self-contained box with everything
it needs (correct language version, libraries, etc.) so it runs identically on any machine.
Metaphor: a **shipping container** — standardized on the outside, so any port (any computer)
can handle it regardless of what's inside.

**docker-compose** is the **master switch**. One command, `docker-compose up`, starts all four
containers at once and wires them together:
1. Back end (FastAPI kitchen)
2. Front end (React dining room)
3. PostgreSQL (pantry)
4. Redis (warming shelf)

Why this matters: "**it works on my machine**" problems mostly disappear. Anyone can clone the
repo and run the entire stack with one command. It's also the stepping stone to deploying on
the cloud (AWS) later — the structure is already container-based.

---

## 12. What's built vs. what's planned (be honest — it's a strength)

This project was built in deliberate weekly stages. Knowing exactly where the line is makes
you look disciplined, not unfinished.

**Built and working:**
- Dockerized full stack (one command to run everything).
- Ravelry keyword search proxy with Redis caching.
- **Local AI embeddings + pgvector semantic search** (the headline feature).
- A seeding script that fetches ~500 patterns and embeds them.
- A polished React search UI with the full design system.

**Planned but not built (intentionally out of scope for now):**
- User accounts / login (JWT auth).
- Actually saving patterns to a personal library.
- Filters (craft type, difficulty, category).
- A project tracker for works-in-progress.
- A voice-activated stitch counter (Web Speech API).
- A colorwork "pixel grid" maker.
- Cloud deployment on AWS.

If an interviewer pushes on the unbuilt parts, the winning answer is:
> "Those are on the roadmap. I intentionally scoped tightly so every layer I built I can fully
> explain and defend. The architecture already anticipates them — for example, the Ravelry
> client sits behind an interface so adding user OAuth later won't require rewrites."

---

## 13. Design principles you can name-drop

These are real principles this codebase follows. Dropping them signals maturity:

- **Swappable boundaries / interfaces** — the Ravelry client and the embedding model both sit
  behind small, replaceable interfaces (supplier can be swapped without redoing the kitchen).
- **Cache-aside pattern** — check the cache first, compute on miss, then store the result.
- **Graceful degradation** — if Redis or the database fails, the app logs a warning and keeps
  working instead of crashing.
- **12-factor config** — all settings via environment variables; nothing secret hardcoded.
- **Separation of concerns** — routes, services, database, cache, and search each live in their
  own module. (Different stations in the kitchen, each with one job.)
- **Idempotent setup** — the database initialization can run repeatedly without breaking
  anything ("create it if it doesn't already exist").

---

## 14. Likely interview questions + short answers

**Q: What's the hardest/most interesting part?**
A: Semantic search. Turning free-text into 384-dimensional embeddings, storing them in
PostgreSQL via pgvector, and ranking results by cosine similarity — so search understands
meaning, not just keywords.

**Q: Why embeddings instead of just keyword search?**
A: Keyword search misses synonyms and intent. "Quick gift for beginners" should match easy,
fast patterns even if those exact words aren't in the pattern text. Embeddings capture meaning.

**Q: Why run the AI model locally instead of using OpenAI?**
A: Cost and privacy. `all-MiniLM-L6-v2` is small, free, and runs on the server with no
per-request API fees or sending data to a third party. Trade-off: slightly less powerful than
a huge hosted model, but more than enough for short pattern text.

**Q: How do you keep it fast?**
A: Redis caching (repeat searches are instant), pre-loading the AI model once at startup rather
than per request, and a pgvector index for approximate nearest-neighbor search.

**Q: How would this scale to millions of patterns?**
A: The pgvector index (IVFFlat) already supports that; I'd tune the index parameters, batch the
embedding/seeding as a background job instead of a manual script, and possibly move to a
dedicated vector store if needed. Redis and the stateless back end scale horizontally.

**Q: What would you build next?**
A: User accounts (JWT), persisting the "save to library" feature, and search filters. The code
is structured so these slot in cleanly.

**Q: What does "the Ravelry client is behind an interface" buy you?**
A: I can swap basic auth for OAuth (so users link their own Ravelry accounts) or even change
data sources entirely, without touching the API routes that depend on it.

---

## 15. One-paragraph summary (say this if you only have a minute)

> "Woolly is a Dockerized full-stack app — React/TypeScript front end, Python/FastAPI back end,
> PostgreSQL and Redis — that does meaning-based ('semantic') search over knitting and crochet
> patterns from Ravelry. It converts both the patterns and the user's query into AI embeddings
> using a local model, stores them in PostgreSQL with the pgvector extension, and ranks results
> by cosine similarity so the search understands intent rather than exact keywords. Redis caches
> results for speed, the external data source is hidden behind a swappable interface, and the
> whole system runs with a single `docker-compose up`. I scoped it in tight weekly milestones so
> I can explain and defend every layer."

---

*Tip: read sections 1, 5, 6, and 15 out loud a couple of times. Those four cover ~80% of what
you'll be asked.*
