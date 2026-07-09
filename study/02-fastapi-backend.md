# 02 — The FastAPI Backend

**The kitchen: how the Python server receives work, does it, and sends answers back.**

---

## What is a web framework?

When you write a web server, you have to solve a lot of boring, repetitive problems:
- How do I listen for incoming HTTP requests?
- How do I parse the URL to know which function to call?
- How do I validate that the data coming in is the right shape?
- How do I send a JSON response with the right headers?
- How do I document the API so others know how to use it?

A **web framework** solves all of these for you so you can focus on your actual logic.

**FastAPI** is Woolly's framework. It's a Python library that:
1. Lets you define routes (which URL does what)
2. Automatically validates incoming data and query parameters
3. Automatically serializes your response objects to JSON
4. Auto-generates interactive API documentation at `/docs`
5. Is built for `async` Python (more on that below)

**Why FastAPI over Flask or Django?**
- **Flask** is older and simpler, but has no built-in data validation or auto-docs — you
  bolt those on separately.
- **Django** is "batteries included" but is opinionated and heavyweight — great for big CMS-
  style apps, overkill for a lean API.
- **FastAPI** hits the sweet spot: modern, fast, has Pydantic built in for validation,
  auto-generates documentation, and is designed for async code from the ground up.

Good interview answer: "FastAPI is modern, gives you automatic request validation via
Pydantic, generates Swagger docs automatically, and is built for async I/O — which matters
when your server is waiting on external calls to Redis, PostgreSQL, and Ravelry."

---

## Async and await — why it matters for a server

This is one of the most commonly misunderstood concepts. Let's nail it.

### The problem: waiting

A web server handles many requests at once. Some of those requests require *waiting* — for
a database query to come back, for Redis to respond, for Ravelry's API to reply. Waiting
takes time (milliseconds, but they add up).

**Synchronous (blocking) approach:** the server handles one request at a time. While waiting
for the database, it just... sits there. The next request has to queue up. Analogy: **one
cashier at a grocery store** — handles one customer fully before calling "next."

**Asynchronous (non-blocking) approach:** while waiting for the database, the server goes
and handles another request. When the database responds, it picks up where it left off.
Analogy: **a waiter at a restaurant** — takes order 1, hands it to the kitchen, takes order
2, hands it to the kitchen, then delivers food to table 1 when the kitchen calls out.
The waiter never just *sits there* — they're always doing something while waiting.

### How Python's async/await works

`async def` defines a function that *can be paused* while waiting. `await` is the pause
point — "pause here and let something else run until this is ready."

```python
# Synchronous — blocks the whole server while Redis responds
def get_cached(key):
    return redis.get(key)  # nothing else can run during this call

# Asynchronous — other requests can be handled while waiting for Redis
async def get_cached(key):
    return await redis.get(key)  # yield control while waiting, resume when done
```

The `await` keyword is only allowed inside `async def` functions. FastAPI knows how to
run these correctly using Python's **event loop** — a scheduler that keeps track of which
async functions are paused and resumes them when their wait is done.

**Key insight for interviews:** async doesn't make individual operations faster. A Redis
call still takes the same time. What it does is let the server *do other work in the
meantime* instead of staring at the wall, which dramatically increases how many requests
per second it can handle.

---

## Routing — mapping URLs to functions

A **route** is a mapping: "when someone sends `GET /patterns/search`, run this function."

In FastAPI:

```python
router = APIRouter(prefix="/patterns", tags=["patterns"])

@router.get("/search")
async def search_patterns(q: str = Query(..., min_length=1)):
    # this runs when GET /patterns/search?q=... is received
    ...
```

The `@router.get("/search")` is a **decorator** — it registers the function below it as the
handler for that URL. `prefix="/patterns"` means all routes in this router are prefixed with
`/patterns`, so `/search` becomes `/patterns/search`.

**Query parameters** (`?q=...`) are declared as function arguments. FastAPI automatically
reads them from the URL and passes them in. If `min_length=1` is violated (empty query),
FastAPI automatically returns a 422 error — you don't have to write that validation yourself.

**The router pattern:** instead of dumping all routes into `main.py`, Woolly defines routes
in `backend/app/api/patterns.py` and registers the router in `main.py`:

```python
app.include_router(patterns_router)
```

This keeps things organized — like having one section of a restaurant menu per cuisine
type, rather than a chaotic single list.

---

## Pydantic — the data validator and schema definer

**Pydantic** is a Python library for defining the shape of data. You describe what a piece
of data should look like, and Pydantic validates it, converts types automatically, and
generates documentation.

**Analogy:** an order ticket format at a restaurant. The kitchen says "every order ticket
MUST have: table number (integer), item names (list of strings), and whether it's allergic-
free (boolean)." If a waiter brings a ticket missing the table number, the kitchen rejects
it immediately with a clear error — rather than cooking the food and then wondering where
to send it.

In Woolly, Pydantic models define the shape of every API response:

```python
class PatternSummary(BaseModel):
    id: int
    name: str
    designer: str | None = None   # optional — can be None
    ravelry_url: str | None = None
    photo_url: str | None = None
    free: bool | None = None

class PatternSearchResult(BaseModel):
    query: str
    patterns: list[PatternSummary]
    total: int | None = None
```

When a route function returns a `PatternSearchResult`, FastAPI automatically:
- Validates that all required fields are present
- Converts the object to JSON
- Sets the correct `Content-Type: application/json` header

**Inheritance:** Woolly extends `PatternSummary` for semantic search results:

```python
class SemanticPatternSummary(PatternSummary):
    similarity_score: float
    description: str | None = None
    difficulty: str | None = None
```

This adds extra fields without rewriting the base. Classic object-oriented inheritance —
the child gets everything the parent has, plus its own extras.

---

## Dependency injection — the prep cook analogy

**Dependency injection** is a pattern where instead of a function *creating* its own
dependencies (database connection, settings, etc.), those dependencies are *handed to it*
from the outside.

**Analogy:** at a restaurant, the line cook doesn't go to the walk-in fridge and get their
own ingredients for every dish. A prep cook (the dependency injector) has already prepped
and staged everything at their station. The line cook just uses what's in front of them.

FastAPI's `Depends()` system does this. Look at a route:

```python
@router.get("/semantic-search")
async def semantic_search_patterns(
    q: str = Query(...),
    db: Session = Depends(get_db),          # DB session handed in
    settings: Settings = Depends(get_settings),  # config handed in
):
```

`get_db` is a function that opens a database session and yields it. FastAPI runs it for
you and hands the session to `semantic_search_patterns`. When the request is done, FastAPI
runs the cleanup code in `get_db` (closing the session).

**Why this is good:**
1. **Testability:** in tests you can swap `get_db` for a fake database without changing
   the route at all.
2. **No repeated boilerplate:** every route that needs the database just asks for it —
   nobody writes "connect to the database" manually in each function.
3. **Swappability:** the Ravelry client is injected via `Depends(get_pattern_provider)`,
   so you can swap it for a different implementation later (e.g. OAuth) by changing one
   function.

---

## Startup lifecycle — loading things before the first request

Some things should happen *once* when the server starts, not on every request:
- Enable pgvector, create the database tables
- Load the AI embedding model (takes 3-5 seconds)

FastAPI provides a **lifespan** hook for this:

```python
@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        init_db()           # create tables, enable pgvector extension
    except Exception as exc:
        logger.warning("Database init failed; semantic search will be unavailable.")
    get_model()             # load the AI model — done once, shared forever
    yield                   # server is running — handle requests
    # cleanup code goes here (after yield, when server shuts down)
```

The `yield` is the dividing line: everything *before* yield runs at startup; everything
*after* yield runs at shutdown; the server handles requests *while* yielded.

**Why pre-load the model?** The `all-MiniLM-L6-v2` model takes 3-5 seconds to load. If
you loaded it per request, the first search after every server restart would be 5 seconds
slow. Loading it once at startup means all requests get a pre-warmed model instantly.

---

## Error handling — clear signals, not crashes

Good servers don't crash when bad things happen. They return a clear status code and a
helpful message.

FastAPI has `HTTPException` for this:

```python
try:
    rows = run_semantic_search(db, query, limit=limit)
except Exception as exc:
    logger.error("Semantic search failed: %s", exc)
    raise HTTPException(
        status_code=503,
        detail="Semantic search is unavailable. Has the database been seeded?"
    )
```

The status codes Woolly uses:

| Code | Meaning | When Woolly uses it |
|---|---|---|
| 200 | OK | Successful response |
| 400 | Bad Request | Empty query string |
| 422 | Validation Error | Pydantic catches bad input (automatic) |
| 429 | Too Many Requests | Ravelry rate-limited us |
| 502 | Bad Gateway | Ravelry rejected our credentials |
| 503 | Service Unavailable | DB is down, not seeded, or Ravelry is unreachable |

**Analogy:** a good restaurant doesn't disappear into the kitchen when an order is wrong —
they come back out and say "I'm sorry, we're out of that tonight, can I suggest something
else?" Clear, informative, professional.

---

## The OpenAPI docs — your free API documentation

FastAPI automatically generates interactive API documentation at `http://localhost:8000/docs`
(called Swagger UI). You can open it in a browser, see all endpoints, see their parameters
and response shapes, and even send real requests directly from the browser to test.

This is generated entirely from your code — you write the routes and Pydantic models, and
FastAPI produces the docs for free. No separate documentation to maintain.

**Interview tip:** mention this. "FastAPI auto-generates Swagger docs from my code, so the
API is self-documenting. This is useful during development and also for any future
consumers of the API."

---

## How all the backend pieces fit together

```
incoming HTTP request: GET /patterns/semantic-search?q=cozy+sweater
         │
         ▼
   main.py (FastAPI app)
         │ middleware (CORS check)
         ▼
   api/patterns.py — semantic_search_patterns()
         │
         ├─→ redis_client.get_cached()       [cache check]
         │        │ miss
         │        ▼
         ├─→ semantic_search.py              [embed + query]
         │        │
         │        ├─→ embedding_service.embed_text()    [AI model]
         │        └─→ db session + pgvector query       [database]
         │
         ├─→ redis_client.set_cached()       [save result]
         │
         └─→ SemanticSearchResult (Pydantic model) → JSON response
```

Each module has one job. The route handler (`patterns.py`) orchestrates but doesn't do
the detailed work itself. The detailed work lives in `semantic_search.py`,
`embedding_service.py`, and `redis_client.py`. This is **separation of concerns**.

---

## Interview questions for this topic

**Q: Why FastAPI over Flask or Django?**
A: "FastAPI is built for async Python from the ground up, has Pydantic for automatic
request validation and schema definition, auto-generates OpenAPI/Swagger docs, and has
great dependency injection support. Flask would have required bolting on all of that. Django
is too heavy for a lean API."

**Q: What does async/await actually do for a web server?**
A: "It lets the server handle multiple requests concurrently without multiple threads. While
one request is waiting for a Redis or database response, the event loop picks up another
request. This means a single-threaded Python process can serve many more requests per
second than a blocking synchronous server."

**Q: What is Pydantic and why is it useful?**
A: "Pydantic lets you define the shape of data as Python classes with type annotations.
FastAPI uses it to automatically validate incoming request data, convert types, generate
JSON responses, and produce API documentation. The benefit is that the API contract is
enforced automatically — you don't write validation code by hand."

**Q: What is dependency injection and where does Woolly use it?**
A: "Dependency injection is when a function receives its dependencies from the outside
rather than creating them itself. FastAPI's `Depends()` system injects database sessions,
app settings, and the Ravelry client into route handlers. This makes routes easier to test
(you can swap real dependencies for fakes) and eliminates boilerplate."

**Q: What happens when the server starts up?**
A: "The lifespan hook runs: first it initializes the database (creates tables, enables
pgvector), then it pre-loads the sentence-transformers embedding model. Both happen once at
startup so no request ever waits for that overhead. If the database init fails, the server
still starts — it just logs a warning and skips semantic search."
