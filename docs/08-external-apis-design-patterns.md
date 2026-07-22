# 08 — External APIs & Software Design Patterns

**Talking to Ravelry + the key code patterns that make Woolly extensible and professional.**

This file covers two related things:
1. How Woolly communicates with the Ravelry API (an external service Woolly doesn't control)
2. The key software design patterns used throughout the codebase

Design patterns are reusable solutions to common problems. Knowing their names and being
able to spot them in your code is a strong signal in interviews.

---

## Part 1: Talking to the Ravelry API

### What is an external API?

Ravelry has a database of over a million knitting and crochet patterns. Woolly doesn't
have its own pattern database (that would take years to build). Instead, it connects to
Ravelry's **API** — a set of URLs that Ravelry exposes so other apps can request their
data.

**Analogy:** Ravelry is a **wholesale supplier**. Woolly is a boutique that doesn't
manufacture its own products — it orders from the supplier. The API is the phone number and
order form you use to call the supplier.

### HTTP Basic Authentication

To use Ravelry's API, Woolly authenticates with **HTTP Basic Auth** — the simplest form
of authentication. It sends a username and password with every request:

```
Authorization: Basic base64(username:password)
```

The username and password are Woolly's *app credentials* (not a user's personal credentials).
They're stored in environment variables (`RAVELRY_USERNAME`, `RAVELRY_PASSWORD`) and
never hardcoded.

In code (using `httpx`, an async HTTP client):

```python
response = await client.get(
    url,
    params=params,
    auth=(self._username, self._password)  # httpx handles base64 encoding
)
```

**Why basic auth for now?** It's the simplest option Ravelry offers. The PRD notes this
will eventually become Ravelry OAuth — so individual users can link their personal Ravelry
accounts. The code is structured to make that swap easy (see the interface pattern below).

### The `httpx` library

Woolly uses `httpx` instead of Python's built-in `urllib` or the popular `requests`
library because:
- `httpx` supports `async/await` natively — `requests` does not
- This is important because the Ravelry call happens inside an `async def` route handler
- Waiting for Ravelry's response with async allows the server to handle other requests
  meanwhile

```python
async with httpx.AsyncClient(timeout=10.0) as client:
    response = await client.get(url, params=params, auth=(...))
```

The `timeout=10.0` means "if Ravelry doesn't respond within 10 seconds, give up and raise
an error." Without a timeout, a slow Ravelry could hang the server indefinitely.

### Error handling: translating HTTP codes into meaningful exceptions

Ravelry can fail in different ways, and each failure should produce a different, clear
response to the user. Woolly defines custom exception classes:

```python
class RavelryError(Exception): ...
class RavelryUnavailableError(RavelryError): ...  # 5xx from Ravelry
class RavelryRateLimitError(RavelryError): ...    # 429 - too many requests
class RavelryAuthError(RavelryError): ...         # 401 - credentials wrong
```

And maps them to HTTP status codes:

```python
if response.status_code == 401:
    raise RavelryAuthError("Ravelry rejected the configured credentials.")
if response.status_code == 429:
    raise RavelryRateLimitError("Ravelry rate limit exceeded.")
if response.status_code >= 500:
    raise RavelryUnavailableError(f"Ravelry returned a server error.")
```

Then in the route handler:
```python
try:
    result = await provider.search_patterns(query)
except RavelryRateLimitError as exc:
    raise HTTPException(status_code=429, detail=str(exc))
except RavelryAuthError as exc:
    raise HTTPException(status_code=502, detail=str(exc))
except RavelryUnavailableError as exc:
    raise HTTPException(status_code=503, detail=str(exc))
```

**Why this layering?** The Ravelry client speaks "Ravelry errors." The API route speaks
"HTTP status codes." The exception classes translate between them. This keeps the Ravelry
client focused on talking to Ravelry — it doesn't need to know about HTTP codes. And the
route handler focused on HTTP — it doesn't need to know about Ravelry specifics. Clean
separation.

### What Woolly stores and what it doesn't

Per Ravelry's API terms of service, Woolly:
- ✅ Stores **metadata** (name, designer, permalink, free/paid, difficulty)
- ✅ Stores the **URL** to the pattern's image on Ravelry (never the image itself)
- ✅ Links to Ravelry for every "View on Ravelry" click
- ❌ Does NOT store pattern instructions, PDFs, or full content
- ❌ Does NOT host images

The `PatternSummary` Pydantic class even has a docstring noting this: "Search-result
metadata only — never pattern content, per Ravelry API terms."

---

## Part 2: Software Design Patterns

Design patterns are named solutions to common design problems. Woolly uses several
intentionally. Know these cold.

---

### Pattern 1: Interface / Abstract Base Class (ABC)

**The problem:** Woolly currently authenticates with Ravelry using basic auth (a single
shared username/password). In the future, users will link their own Ravelry accounts, which
requires OAuth (a more complex flow). If the code that calls Ravelry is scattered everywhere,
switching to OAuth means changing many files.

**The solution:** define an **interface** (in Python: an Abstract Base Class) that
describes *what* the Ravelry client can do, without specifying *how* it does it. Then any
code that needs to search patterns calls the interface — not the concrete implementation.

```python
class PatternProvider(ABC):
    """Interface boundary — swap this out when moving to OAuth."""
    @abstractmethod
    async def search_patterns(self, query: str, page_size: int = 20) -> PatternSearchResult:
        ...
```

`RavelryClient` implements this interface:
```python
class RavelryClient(PatternProvider):
    async def search_patterns(self, query, page_size=20) -> PatternSearchResult:
        # the actual implementation using basic auth
        ...
```

The route handler doesn't import `RavelryClient` — it receives a `PatternProvider`:
```python
def get_pattern_provider(settings) -> PatternProvider:
    return RavelryClient(username=settings.ravelry_username, ...)
```

To switch to OAuth: write `OAuthRavelryClient(PatternProvider)` and change
`get_pattern_provider()` to return it. The route handler doesn't change at all.

**Analogy:** you plug into a **standard electrical outlet** (the interface). Whether
the power comes from the grid, a solar panel, or a generator (the implementations) doesn't
matter to your laptop — it just needs the standard plug. The outlet interface is the
contract; what's behind it is swappable.

**Interview term:** "swappable boundary" or "program to an interface, not an implementation."
This is the Dependency Inversion Principle from SOLID design principles.

---

### Pattern 2: Singleton

**The problem:** loading `all-MiniLM-L6-v2` takes 3-5 seconds. Calling it once per request
would make every search 5 seconds slow.

**The solution:** load the model **once** and store it in a module-level variable. Every
subsequent call to `get_model()` returns the same already-loaded instance.

```python
_model = None
_model_lock = threading.Lock()

def get_model():
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:  # double-check after acquiring lock
                _model = SentenceTransformer(MODEL_NAME)
    return _model
```

This is the **Singleton pattern** — a class (or object) where only one instance ever exists,
shared by all callers.

The `threading.Lock()` and double-check are for thread safety: if two requests arrive
simultaneously and both check `_model is None` before either has loaded it, only one thread
acquires the lock and does the loading. The other waits, then checks again and finds it loaded.

**Redis uses the same pattern:**
```python
_redis: redis.Redis | None = None

def get_redis() -> redis.Redis:
    global _redis
    if _redis is None:
        _redis = redis.from_url(...)
    return _redis
```

One Redis connection, shared by all requests.

**Analogy:** a single whiteboard in a shared office. Everyone who needs to write something
uses the same whiteboard — you don't buy a new one for each person. The lock is like a
"one person at a time" rule for erasing and rewriting.

---

### Pattern 3: Cache-Aside

Already covered thoroughly in `06-redis-caching.md`. Short version: check cache → on miss,
compute → store in cache. This is a named pattern worth knowing.

**Also called:** lazy loading, look-aside cache.

---

### Pattern 4: 12-Factor App Configuration

The **12-Factor App** is a methodology for building software-as-a-service apps that are
easy to run anywhere (locally, staging, production) without code changes.

The relevant factor for Woolly is **Factor III: Config** — "Store config in the
environment."

Config = anything that varies between deployment environments:
- Database URL (local Docker vs AWS RDS)
- Redis URL
- Ravelry credentials
- CORS origins

Woolly stores all of this in environment variables, read by a `Settings` class:

```python
# backend/app/config.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    ravelry_username: str = ""
    ravelry_password: str = ""
    database_url: str = "postgresql://woolly:woolly@localhost:5432/woolly"
    redis_url: str = "redis://localhost:6379/0"
    cors_origins: str = "http://localhost:5173"
    search_cache_ttl_seconds: int = 3600
    semantic_cache_ttl_seconds: int = 1800

    class Config:
        env_file = ".env"
```

`pydantic-settings` reads values from the environment (or `.env` file) automatically.
The same code runs locally (reads from `.env`), in CI (reads from CI secrets), and in
production (reads from AWS environment variables).

**Why this is important for interviews:** it shows you think about deployment from day one,
not as an afterthought. "AWS-ready" means the code doesn't need to change to run in the cloud.

---

### Pattern 5: Graceful Degradation

**The principle:** when a non-critical component fails, the system should continue working
at reduced functionality rather than failing completely.

Woolly applies this in two places:

**Redis failure → fall through to real computation:**
```python
async def get_cached(key):
    try:
        return await get_redis().get(key)
    except redis.RedisError:
        logger.warning("Redis GET failed; falling through.")
        return None  # treat as cache miss → app still works, just slower
```

**Database init failure → backend still starts:**
```python
try:
    init_db()
except Exception as exc:
    logger.warning("Database init failed; semantic search will be unavailable.")
    # server still starts — keyword search and health check still work
```

**Analogy:** a restaurant where the espresso machine breaks. The restaurant doesn't close —
they apologize, serve coffee from a French press instead, and fix the machine. Degraded
service > no service.

---

### Pattern 6: Separation of Concerns

Each module in Woolly has exactly one job:

| Module | Job |
|---|---|
| `api/patterns.py` | Handle HTTP requests — validation, routing, error translation |
| `services/ravelry_client.py` | Talk to Ravelry's API |
| `services/embedding_service.py` | Run the AI model to create embeddings |
| `search/semantic_search.py` | Query pgvector for nearest neighbors |
| `cache/redis_client.py` | Read and write to Redis |
| `db/models.py` | Define the database schema |
| `db/session.py` | Manage database connections |

No module does two jobs. This means:
- When the Ravelry auth changes → you change only `ravelry_client.py`
- When the embedding model changes → you change only `embedding_service.py`
- When the caching strategy changes → you change only `redis_client.py`

**Analogy:** a kitchen where every station has one job. The grill station doesn't plate the
food. The pastry section doesn't make sauces. Each station can be improved, replaced, or
retrained without disrupting the others.

**Interview term:** "separation of concerns" or "single responsibility principle" (the S
in SOLID).

---

### Idempotence (bonus pattern)

An operation is **idempotent** if running it multiple times produces the same result as
running it once. Woolly uses this in two places:

1. **Database init:** `CREATE TABLE IF NOT EXISTS` — run it 100 times, same result as once.
2. **Seeding:** the seed script skips patterns that already have embeddings. Run it twice,
   no duplicates, same DB state.

**Analogy:** pressing the elevator button ten times vs once — the elevator still comes once.
The extra presses do nothing.

---

## Interview questions for this topic

**Q: What is the interface pattern and why did you use it for the Ravelry client?**
A: "The `PatternProvider` abstract base class defines a contract: any implementation must
provide `search_patterns()`. `RavelryClient` implements it with basic auth today. When we
move to OAuth, I write a new class that implements the same interface and swap it in
`get_pattern_provider()`. No other code changes. This is the dependency inversion principle
— depend on the abstraction, not the implementation."

**Q: What is a singleton and where does Woolly use one?**
A: "A singleton is a class/object where only one instance exists for the lifetime of the
application. Woolly uses it for both AI models — the bi-encoder and cross-encoder — each
taking 3-5 seconds to load, so we load once at startup and share across all requests. The
Redis client connection is also a singleton — one connection pool shared by all requests."

**Q: What is the 12-factor app?**
A: "A methodology for building deployable applications. The relevant factor for Woolly is
'store config in the environment' — all secrets, URLs, and settings come from environment
variables, not hardcoded values. This means the same code runs locally (with `.env`) and
in AWS (with ECS task environment variables) without any changes."

**Q: How do you handle errors from external APIs?**
A: "I translate HTTP status codes into domain-specific exception types:
`RavelryRateLimitError` for 429, `RavelryAuthError` for 401, `RavelryUnavailableError`
for 5xx. The route handler catches these and maps them to appropriate HTTP responses for
the client. This keeps the Ravelry client focused on Ravelry, and the route handler
focused on HTTP — neither knows about the other's concerns."

**Q: What is graceful degradation?**
A: "When a non-critical component fails, the system continues working at reduced capability
rather than failing completely. If Redis is down, Woolly falls through to the real
computation — users get slower responses, not errors. If the database init fails, the
server still starts and the health endpoint still works."
