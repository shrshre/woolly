# 03 — Semantic Search & Embeddings

**The foundation: how Woolly turns text into meaning-coordinates — and how that fits into
the larger hybrid + reranking pipeline.**

This is still a must-know topic. Embeddings power the semantic leg of hybrid search, and
understanding bi-encoders vs cross-encoders is essential for explaining the full pipeline.
Read `10-hybrid-search-and-reranking.md` after this file for the complete picture.

---

## The problem with normal (keyword) search

Ravelry already has a search bar. So why build Woolly?

Ravelry's search is **keyword-based** — it looks for your exact words in the pattern's
title, description, and tags. This works fine when you know the exact words designers use.
But real searches don't work that way.

**Imagine searching "no seaming required."** A user means: "I want a pattern knitted in
one piece so I don't have to sew parts together at the end." But designers don't write
"no seaming required" in their pattern titles — they say things like "seamless," "top-down,"
"worked in the round," or "knit flat and seamed (optional)."

Keyword search for "no seaming required" returns nothing useful, because *none of those
words match*. The human understands the intent — the search engine doesn't.

**Woolly's goal:** understand intent, not just words. This is called **semantic search**.

---

## What "semantic" means

"Semantic" comes from "semantics" — the meaning of words rather than the words themselves.

- **Keyword search:** compares the *characters* in your query to the *characters* in
  documents. Does the string "winter" appear in this document? Yes/no.
- **Semantic search:** compares the *meaning* of your query to the *meaning* of documents.
  Does "winter" mean something similar to what this document is about? The model can decide
  that "chunky pullover" is semantically close to "cozy winter sweater" even though they
  share zero words.

---

## The core idea: text as coordinates in space

Here's the fundamental breakthrough that makes semantic search possible:

**We can turn any piece of text into a list of numbers such that similar texts produce
similar numbers.**

This list of numbers is called an **embedding** or a **vector**.

### The 2D map analogy (start here)

Imagine a giant map. Every phrase or piece of text gets placed at a specific (x, y)
coordinate based on its *meaning*:

```
                                    ↑  craft/clothing
                    (sweater, 8.5)  •   • (cardigan, 8.2)
             (pullover, 7.9)  •
                                        • (vest, 7.1)
                                •  (hat, 5.2)
 ────────────────────────────────────────────────────→  warm/cozy
                                •  (mittens, 4.8)
                    (socks, 3.9)  •
                                        • (dishcloth, 1.1)
                    (amigurumi, 0.5)  •
                                    ↓
```

Things that mean similar things end up near each other. "Sweater," "cardigan," and
"pullover" are clustered. "Hat" and "mittens" are in the same neighborhood. "Dishcloth"
and "amigurumi" are far away in a different corner.

When a user searches "cozy winter sweater," you compute its coordinates on this map and
then answer: "what patterns are closest to this point?" Those are your results.

**Real embeddings aren't 2D.** You can't visualize them — Woolly uses 384 dimensions.
But the intuition is identical: similar things are close together, dissimilar things are
far apart. The math (cosine similarity) works the same regardless of how many dimensions
you have.

---

## What is a vector?

A **vector** is just a list of numbers. In math, a vector defines a point (or direction)
in space.

- A 2D vector: `[3.5, 7.2]` (x, y coordinates)
- A 3D vector: `[3.5, 7.2, -1.8]` (x, y, z coordinates)
- A 384D vector: `[0.12, -0.34, 0.91, 0.02, ..., -0.15]` (384 numbers)

An **embedding** is a vector specifically designed to represent meaning. The 384 numbers
don't individually mean anything interpretable (you can't say "dimension 42 = level of
warmth"). The model learned during training what arrangement of numbers puts similar texts
close together — we just trust it to do that.

---

## How a model "learns" (training vs inference)

Interviewers mix these up on purpose. Know the difference cold.

### Training (Woolly does **not** do this)

Someone else (Microsoft / the HuggingFace community) already:

1. Took millions of sentence pairs ("A dog runs" ↔ "A puppy is running" = similar).
2. Adjusted millions of internal knobs (**weights**) until similar sentences got nearby
   coordinates and dissimilar ones got far apart.
3. Saved those knobs as a **pretrained model** file (~90MB).

**Metaphor:** training is writing a textbook by studying for years. Woolly buys the
finished textbook — it does not rewrite the chapters.

### Inference (what Woolly does)

At runtime Woolly only **runs** the frozen model:

```
text in → model → 384 floats out
```

No learning happens during a search. Same input → same embedding (given the model and
`normalize_embeddings=True`).

**Interview line:** "I use pretrained models for inference only — there is no training
pipeline in this repo."

---

## What lives inside the model (intuition, not math)

Woolly uses **transformers** via the `sentence-transformers` library. You do not need the
equations — you need the story:

1. Text is split into **tokens** (roughly words/subwords).
2. Each token becomes a numeric representation.
3. **Attention** lets every word look at every other word in the sentence — so "seamless"
   can influence how "pullover" is understood in context.
4. The model compresses the whole sentence into **one** 384-number vector.

**Metaphor:** a book club. Every person (word) listens to every other person, then the
group writes a single summary paragraph (the embedding). Short, but it captures the vibe
of the whole discussion.

You never implement attention from scratch here. You call:

```python
vector = get_model().encode(text, normalize_embeddings=True)
```

---

## The AI model: all-MiniLM-L6-v2

Woolly uses a pre-trained model called **all-MiniLM-L6-v2** from the `sentence-transformers`
library to convert text into embeddings.

**Breaking down the name:**
- `all-` = trained on many different datasets (not domain-specific)
- `MiniLM` = "Mini Language Model" — a compact, efficient architecture
- `L6` = 6 transformer layers (the transformer is the core AI architecture; 6 layers = a
  good speed/quality balance)
- `v2` = second version

**Why this model specifically?**

| Factor | Detail |
|---|---|
| **Free** | Open source, hosted on HuggingFace — no API key, no cost per query |
| **Runs locally** | Runs on CPU inside your Docker container — no external dependency |
| **Fast** | ~20ms to embed one text string — acceptable for real-time search |
| **Small** | ~90MB download — can run on any machine |
| **384 dimensions** | Small enough to be fast, large enough to capture meaning well |
| **Proven** | Widely used benchmark model for semantic search tasks |

**The alternative (and why Woolly didn't use it):** OpenAI's `text-embedding-3-small`
is more powerful, but costs money per API call, adds latency (network round-trip), and
adds a dependency on an external service that can go down. The PRD explicitly chose
local embeddings because "the interview story of running embeddings locally is stronger
than calling an API" — and the quality gap isn't worth the trade-offs for this domain.

---

## The singleton pattern: load once, share forever

Loading the bi-encoder takes 3-5 seconds. The cross-encoder takes another 3-5 seconds. If
you loaded either per search request, every search would be painfully slow.

Solution: load both **once at startup** and share across all requests. This is the
**singleton pattern** — one instance, shared globally. Woolly uses it in two places:

| Model | File | Purpose |
|---|---|---|
| Bi-encoder (`all-MiniLM-L6-v2`) | `embedding_service.py` | Embed queries and patterns (stage 1) |
| Cross-encoder (`ms-marco-MiniLM-L-6-v2`) | `reranking_service.py` | Score query-document pairs (stage 2) |

```python
_model = None
_model_lock = threading.Lock()

def get_model():
    global _model
    if _model is None:
        with _model_lock:      # thread-safe: only one thread does the loading
            if _model is None:
                _model = SentenceTransformer(MODEL_NAME)
    return _model
```

The double `if _model is None` check (called "double-checked locking") is for thread
safety: even if two requests arrive simultaneously, only one loads the model; the other
waits for the lock and then sees the model is already loaded.

See the actual code at: `backend/app/services/embedding_service.py`

---

## Building the text to embed

Garbage in → garbage geometry. Woolly does **not** embed raw Ravelry JSON. It builds a
deliberate string in `build_pattern_text`:

```python
def build_pattern_text(pattern: dict) -> str:
    raw = pattern.get("raw_data") or {}
    parts = [
        pattern.get("name") or "",
        pattern.get("designer") or "",
        pattern.get("description") or "",
        " ".join(pattern.get("tags") or []),
        pattern.get("craft") or "",
        pattern.get("difficulty") or "",
        pattern.get("category") or "",
        pattern.get("yarn_weight") or _yarn_weight_from_raw(raw),
        pattern.get("needle_size") or _needle_sizes_from_raw(raw),
    ]
    return " ".join(part for part in parts if part).strip()
```

**Why so many fields?** Queries like `"worsted weight beginner hat"` or `"PetiteKnit
cardigan"` need those signals in the vector — not only poetic description prose.
`raw_data` (JSONB) keeps the full Ravelry payload so you can change this function later
and **re-embed without re-fetching** (`re_embed_existing` in `seeding.py`).

---

## Cosine similarity: how "closeness" is measured

Once both the query and the patterns are embeddings (lists of 384 numbers), you need a
way to measure how "close" two embeddings are. The measurement used is **cosine similarity**.

### The intuition (no math needed)

Imagine two arrows (vectors) sticking out from the center of a circle:

```
         •  "cozy sweater" (query)
        /
       /   ← small angle = similar meaning
      /
center────•  "chunky pullover" (close match)

center────────────────────────────•  "cat toy" (far away, large angle)
```

Cosine similarity measures the **angle** between two vectors. A small angle (arrows
pointing in nearly the same direction) = high similarity. A large angle (arrows pointing
away from each other) = low similarity.

- Cosine similarity of 1.0 = identical meaning (angle = 0°)
- Cosine similarity of 0.0 = completely unrelated (angle = 90°)
- Cosine similarity of -1.0 = opposite meaning (angle = 180°)

Woolly uses **cosine distance** = `1 - cosine_similarity`. So distance 0 = identical,
distance 1 = completely unrelated. The database is sorted by distance ascending — smallest
distance (most similar) first.

**Why cosine and not regular Euclidean (straight-line) distance?** Cosine similarity
compares *direction*, not magnitude. Two texts might embed to vectors of very different
lengths, but if they point in the same direction they're still semantically similar. The
direction matters; the scale doesn't. This is a deliberate mathematical choice that works
better for text.

---

## The seeding pipeline: preparing the database

Before semantic search can work, you need patterns in the database *with* embeddings.
This is called **seeding**. Shared code lives in `backend/app/services/seeding.py`,
invoked by the CLI (`backend/scripts/seed_patterns.py`) and a **24h incremental
scheduler**.

### The seeding flow

```
run_seed(limit=..., incremental=False|True)
      │
      ├─→ Write seed_runs row (status=running)
      │
      ├─→ Optional: re_embed_existing() from raw_data (no Ravelry calls)
      │
      ├─→ collect_pattern_ids()
      │     Full: ~25 categories × popularity sorts × knitting/crochet
      │     Incremental: sort=date per category; stop when a page is all-known
      │
      ├─→ For each new pattern ID:
      │     1. GET /patterns/{id}.json from Ravelry
      │     2. extract_fields() → columns + tags + raw_data
      │     3. build_pattern_text() → embed_text() → 384 numbers
      │     4. UPSERT on ravelry_id
      │
      └─→ Mark seed_runs completed/failed; clear_search_caches()
```

**Idempotency:** upserts key on `ravelry_id`, so re-running never duplicates rows.
Already-embedded IDs are skipped when collecting new ones.

**Rate limiting:** `0.5s` sleep between Ravelry calls, with retries/backoff on HTTP 429.

Treat seeding as the **index build** for search — quality is bounded by what you embed
and when you invalidate Redis. Deeper indexing detail: `10-hybrid-search-and-reranking.md`.

---

## The live search flow: where semantic search fits today

Semantic search is no longer the only search path. It's one leg of hybrid retrieval, and
the fallback when keyword and designer legs have no matches. But the core pgvector query
is the same:

```python
def semantic_search(db, query, limit=10, craft=None, difficulty=None, free=None, category=None):
    query_vector = embed_text(query)
    db.execute(text(f"SET LOCAL ivfflat.probes = {IVFFLAT_PROBES}"))
    distance = Pattern.embedding.cosine_distance(query_vector)
    q = db.query(Pattern, distance.label("distance")).filter(Pattern.embedding.isnot(None))
    # filters applied in SQL before ranking ...
    rows = q.order_by(distance).limit(limit).all()
```

In production, this function is called:
1. As the **semantic leg** inside `hybrid_search.py` (top 100 candidates)
2. As a **fallback** when keyword and designer legs return zero matches
3. Never as the sole search path (unless the fallback triggers)

See: `backend/app/search/semantic_search.py` and `10-hybrid-search-and-reranking.md`

---

## Semantic search vs RAG (know this distinction cold)

Interviewers often ask about this. The short version:

| | Woolly (semantic search) | RAG |
|---|---|---|
| **Purpose** | Find and rank existing items | Generate a new, custom answer |
| **Output** | A ranked list of real pattern cards | Freshly written prose |
| **Uses an LLM?** | No — only a local embedding model | Yes — a large language model (GPT, Claude) |
| **Failure mode** | Might rank a mediocre match slightly too high | Can hallucinate (make things up) |

**Semantic search is the *retrieval* half of RAG.** RAG would take Woolly's top results,
paste their text into a prompt, and have an LLM write a custom paragraph answering the
user's question. Woolly stops before that step — by design.

**Why not RAG?** The product goal is *discovery* — users want to find a real, purchasable
pattern to buy on Ravelry, not get a paragraph about patterns. A hallucinated description
of a non-existent pattern would be worse than useless. The correct tool is semantic
retrieval, not generation.

---

## The normalize_embeddings=True detail

In the `embed_text` function:

```python
vector = get_model().encode(text, normalize_embeddings=True)
```

**Normalization** scales every embedding vector to have a length of exactly 1 (unit vector).
Why? When all vectors have the same length, cosine distance and Euclidean distance give
the same ranking. This makes the math a bit simpler and the search a bit faster. It also
means all similarity scores are in a clean 0-to-1 range that's easy to reason about.

---

## Bi-encoder vs cross-encoder — the key distinction

Woolly uses **two different kinds** of AI models. Interviewers will ask about this.

### Bi-encoder (stage 1) — `all-MiniLM-L6-v2`

```
query  ──encode──►  q_vec
doc    ──encode──►  d_vec     (docs encoded once at seed time!)
compare q_vec ↔ d_vec with cosine similarity
```

- Query and document are embedded **separately**.
- Pattern embeddings are **precomputed** and stored in Postgres.
- At search time you only embed the query (~20ms), then do nearest-neighbor lookup.
- Fast enough for the whole corpus.

### Cross-encoder (stage 2) — `cross-encoder/ms-marco-MiniLM-L-6-v2`

```
[query + document text] ──together──► single relevance score
```

- Sees query and document **in the same forward pass**.
- Captures interactions separate embeddings miss (e.g. brand-style names).
- Too slow for thousands of patterns → only runs on ~60 candidates.
- Trained on MS MARCO (Bing-style query↔passage relevance); transfers well enough to
  pattern blurbs.

### Metaphor that sticks

| Model | Metaphor |
|---|---|
| Bi-encoder | **Speed dating** — glance at GPS profiles of everyone in the city, shortlist 60. |
| Cross-encoder | **Coffee chat** — sit with those 60 and decide who actually fits. |

Production search almost always looks like: cheap recall → expensive precision.

See `reranking_service.py` and `10-hybrid-search-and-reranking.md` for the full pipeline.

---

## What makes this technically impressive (interview framing)

If you've internalized all of the above, frame it this way in an interview:

> "I built a two-stage search pipeline. Stage 1 uses a bi-encoder to embed queries and
> patterns into 384-dimensional vectors, combined with PostgreSQL full-text search and
> designer trigram matching in a weighted hybrid retrieval step. Stage 2 uses a cross-encoder
> that scores query-document pairs together on the top candidates — much more accurate than
> vector similarity alone. Both models run locally in Docker with no external API dependency.
> This means 'cozy winter sweater' surfaces 'chunky ribbed pullover in the round' even though
> they share no words, while 'Petite Knit' still finds that designer's patterns exactly."

That answer signals: you understand AI/ML concepts at depth (bi-encoder vs cross-encoder),
you made conscious infrastructure decisions (local vs API, hybrid vs pure semantic), and you
connect technical choices to product goals.

---

## Interview questions for this topic

**Q: Explain how your semantic search works.**
A: See the framing paragraph directly above — but emphasize it's now one leg of a hybrid
pipeline with cross-encoder reranking on top. Don't describe it as pure vector search.

**Q: What is the difference between a bi-encoder and a cross-encoder?**
A: "A bi-encoder embeds query and document separately, then compares vectors — fast and
scalable, good for finding candidates. A cross-encoder scores them together — slow but much
more accurate, only feasible on a small pool. Woolly uses the bi-encoder for hybrid
retrieval and the cross-encoder for reranking the top 60 candidates."

**Q: What is an embedding/vector?**
A: "A vector is a list of numbers that represents the meaning of a piece of text.
The model was trained so that similar texts produce similar vectors — they end up close
together in 384-dimensional space. It's like GPS coordinates for meaning."

**Q: Training vs inference — which does Woolly do?**
A: "Training adjusts model weights on huge datasets — I don't do that. Inference runs
the frozen pretrained model to turn text into vectors or relevance scores. Both of my
models are HuggingFace downloads used inference-only."

**Q: What is cosine similarity?**
A: "It measures the angle between two vectors. A small angle means the texts point in the
same direction in meaning-space — they're semantically similar. A large angle means they're
unrelated. I compute it with pgvector's `<=>` operator and sort by smallest distance first."

**Q: Why run the model locally instead of using OpenAI?**
A: "Three reasons: cost (no per-query API fees), reliability (no external dependency that
can go down), and privacy (query text never leaves my server). The quality trade-off is
marginal for pattern text — all-MiniLM-L6-v2 is well-proven for semantic search tasks."

**Q: What's the difference between semantic search and RAG?**
A: "Semantic search retrieves and ranks existing items by meaning. RAG adds a generative
step on top: it takes the retrieved items and feeds them to an LLM to write a custom
answer. Woolly is semantic search only — the product goal is finding a real pattern to buy,
not generating a description of one."

**Q: Why not just use keyword search?**
A: "Keyword search fails on natural-language intent queries. 'No seaming required' should
match patterns described as 'seamless top-down' — but those share zero words. Semantic
search handles this because the embedding model was trained to recognize intent, not
just character patterns."

**Q: How would this scale to a million patterns?**
A: "The IVFFlat index is already designed for approximate nearest-neighbor search at scale.
I'd tune the `lists` parameter as the dataset grows, monitor recall quality, and potentially
move to an HNSW index (better recall at very large scale) or a dedicated vector store like
Pinecone or Weaviate if PostgreSQL became a bottleneck. The embedding pipeline would move
to an async background queue instead of a manual script."
