# Woolly Study Plan — Iteration 1 Roadmap

This folder contains one deep-dive file per concept implemented in Woolly (Weeks 1 & 2).
The goal is to go from "I built this with help" to "I can explain every layer, defend every
decision, and answer follow-up questions cold."

Each file is self-contained. You can study them in any order, but the sequence below is
designed so each topic builds on the previous one.

**Time estimate:** 8–10 focused study sessions (45–60 min each). Don't try to do it all at
once — two sessions per day is the sweet spot.

---

## The Files in This Folder

| File | Topic | Priority |
|---|---|---|
| `01-full-stack-architecture.md` | How the whole system fits together | Must-know |
| `02-fastapi-backend.md` | The Python server (FastAPI, async, routing) | Must-know |
| `03-semantic-search-embeddings.md` | The star feature — AI meaning-based search | Must-know |
| `04-pgvector-vector-databases.md` | How vectors are stored and searched in Postgres | Must-know |
| `05-postgresql-sqlalchemy.md` | The database and how Python talks to it | Must-know |
| `06-redis-caching.md` | The speed layer (Redis cache) | Strong to know |
| `07-docker-containerization.md` | Running the app anywhere, reliably | Strong to know |
| `08-external-apis-design-patterns.md` | Talking to Ravelry + key code patterns | Strong to know |
| `09-react-typescript-frontend.md` | The UI layer (React, TypeScript, Vite) | Good to know |

---

## Recommended Study Sessions

### Session 1 — The big picture (45 min)
**File:** `01-full-stack-architecture.md`

Start here. Before diving into any specific piece, you need a clear mental model of how
everything connects. This session answers: "What does each piece of Woolly actually do,
and how do they talk to each other?"

**Goal by end of session:** You can draw the system on a whiteboard and explain what each
box does and what travels between them.

**Sample question you should be able to answer:**
> "Walk me through what happens from the moment a user types a search query to the moment
> they see results."

---

### Session 2 — The server (45 min)
**File:** `02-fastapi-backend.md`

The FastAPI backend is the brain of the operation. This session covers how the server
receives requests, validates data, orchestrates work, and sends responses back.

**Goal by end of session:** You can explain what FastAPI is, why Python's `async` matters
for a web server, what Pydantic schemas do, and what "dependency injection" means in plain
English.

**Sample questions:**
> "Why did you use FastAPI over Flask or Django?"
> "What does async/await actually buy you in a web server?"
> "What is Pydantic and why is it useful?"

---

### Session 3 — Semantic search: the concept (60 min)
**File:** `03-semantic-search-embeddings.md`

This is the most important session. The semantic search is the headline technical feature
and the thing interviewers will probe the hardest. Read it slowly, twice if needed.

**Goal by end of session:** You can explain what an embedding is to a non-technical person,
explain cosine similarity without formulas, explain why Woolly does NOT use OpenAI, and
walk through exactly what happens when a user submits a search.

**Sample questions:**
> "Explain how your semantic search works."
> "What is an embedding? What is a vector?"
> "Why not just use keyword search? What's the difference?"
> "What is cosine similarity and why does it work for text?"
> "Why did you choose all-MiniLM-L6-v2?"

---

### Session 4 — pgvector and the vector database (45 min)
**File:** `04-pgvector-vector-databases.md`

Builds directly on Session 3. Once you understand embeddings, this covers how Woolly
actually *stores* and *searches* them using PostgreSQL + the pgvector extension.

**Goal by end of session:** You can explain what pgvector adds to PostgreSQL, what an
IVFFlat index is (the drawer-dividers analogy), what "approximate nearest neighbor" means,
and when you'd use a dedicated vector database vs pgvector.

**Sample questions:**
> "What is pgvector? Why not use a dedicated vector database like Pinecone?"
> "What is an IVFFlat index and why does Woolly use it?"
> "What does 'approximate nearest neighbor' mean and what's the trade-off?"
> "How would the search scale to 1 million patterns?"

---

### Session 5 — The database (45 min)
**File:** `05-postgresql-sqlalchemy.md`

Covers relational databases, the `patterns` table schema, and how SQLAlchemy (the ORM)
lets Python code talk to PostgreSQL without writing raw SQL everywhere.

**Goal by end of session:** You can explain the `patterns` table schema and *why* each
column exists, what an ORM is (the translation layer analogy), and what a database session
is.

**Sample questions:**
> "Walk me through your database schema."
> "What is an ORM? Why use one?"
> "Why is `raw_data` stored as JSONB?"
> "What does 'idempotent' mean in the context of database setup?"

---

### Session 6 — Redis caching (40 min)
**File:** `06-redis-caching.md`

Covers why caching exists, how Woolly's cache-aside pattern works, and the graceful
degradation strategy when Redis goes down.

**Goal by end of session:** You can explain cache-aside in one sentence, explain what TTL
means and how Woolly chose its TTL values, and explain what happens when Redis is
unavailable.

**Sample questions:**
> "How does your caching layer work?"
> "What is cache-aside?"
> "What happens if Redis goes down?"
> "Why two different TTLs for keyword vs semantic search?"

---

### Session 7 — Docker (40 min)
**File:** `07-docker-containerization.md`

Covers what Docker is, why it solves real problems, and how `docker-compose` orchestrates
the four Woolly services.

**Goal by end of session:** You can explain the difference between an image and a container,
explain what `docker-compose up` does, and explain why Docker makes local dev and eventual
cloud deployment easier.

**Sample questions:**
> "Why Docker? What problem does it solve?"
> "What's the difference between a Dockerfile and docker-compose.yml?"
> "How would you deploy this on AWS?"

---

### Session 8 — External APIs and code patterns (45 min)
**File:** `08-external-apis-design-patterns.md`

Covers talking to the Ravelry API, error handling, and the key software design patterns
used throughout Woolly (interface/ABC, singleton, 12-factor config, graceful degradation).

**Goal by end of session:** You can explain why the Ravelry client is behind an "interface,"
what the 12-factor app principle means for Woolly's config, and why the embedding model is
a singleton.

**Sample questions:**
> "What is the interface pattern and why did you use it for the Ravelry client?"
> "What is a singleton and where does Woolly use one?"
> "What does '12-factor app' mean?"
> "How do you handle errors from external APIs?"

---

### Session 9 — The front end (40 min)
**File:** `09-react-typescript-frontend.md`

Covers the React UI layer. Since the back end is Woolly's core, this is lower priority —
but knowing it lets you speak to the full stack confidently.

**Goal by end of session:** You can explain React components and state, what TypeScript adds
over JavaScript, what Vite is, and how the front end calls the back end.

**Sample questions:**
> "Walk me through your React architecture."
> "What does TypeScript add? Why not plain JavaScript?"
> "What is a skeleton loading state and why is it good UX?"

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
   → Sessions 3 + 4 combined.

2. **"What happens end to end when a user searches?"**
   → Session 1 + Session 2 gives you the skeleton, Sessions 3/4/6 fill in the organs.

3. **"Why did you make [X] decision?"** (usually about embeddings, pgvector, or Redis)
   → Every session has a "why this, not that" section. Decisions are the most important
   things to explain.

4. **"How would this scale?"**
   → Sessions 3, 4, and 6 all have a scaling section.

5. **"What would you build next?"**
   → You know the answer: hybrid retrieval (BM25 + vectors), reranking, auth, and
   observability — all in the Week 3 PRD.

---

## Cheat Sheet: the One Sentence Per Topic

Commit these to memory. Each is a launchpad for a longer explanation.

- **Full-stack app:** "A React front end talks to a FastAPI back end, which reads from PostgreSQL and caches in Redis — all running locally via Docker."
- **Semantic search:** "I convert both patterns and queries into 384-number meaning-coordinates using a local AI model, then find the closest ones in a PostgreSQL vector column."
- **pgvector:** "A PostgreSQL extension that lets you store vectors and search by cosine similarity — nearest-neighbor search inside a regular database."
- **IVFFlat index:** "An approximate index that divides the vector space into clusters so the database doesn't scan every row for every query."
- **Redis cache:** "I save each search result in Redis for 30 minutes so identical queries are served instantly without re-running the AI or database."
- **Docker:** "Each service runs in an identical, isolated container so the app runs the same on any machine and deploys cleanly to the cloud."
- **Interface pattern:** "The Ravelry client sits behind an abstract contract so I can swap auth methods later without touching the API routes."
- **Singleton:** "The AI model is loaded once when the server starts and shared across all requests, because loading it per-request would take 5 seconds each time."
- **12-factor config:** "All secrets and server addresses come from environment variables — nothing is hardcoded — so the same code runs locally and in the cloud."
