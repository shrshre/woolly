# 03 — Semantic Search & Embeddings

**The star feature: how Woolly understands meaning, not just words.**

This is the most important topic to understand deeply. It's the whole point of the project,
and it's what interviewers will probe hardest. Read this twice.

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

Loading the model takes 3-5 seconds. If you loaded it per search request, every search
would be 5 seconds slow. That's unacceptable.

Solution: load it **once at startup** and share that one loaded model across all requests.
This is the **singleton pattern** — one instance, shared globally.

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

Not everything in the database is worth embedding. Woolly extracts the most meaningful
text from each pattern and concatenates it into one string before embedding:

```python
def build_pattern_text(pattern: dict) -> str:
    parts = [
        pattern.get("name") or "",          # "Chunky Ribbed Pullover"
        pattern.get("description") or "",   # long description text
        " ".join(pattern.get("tags") or []) # "sweater ribbing seamless cozy"
    ]
    return " ".join(part for part in parts if part).strip()
```

Result: `"Chunky Ribbed Pullover A warm ribbed pullover worked seamlessly from the top down sweater ribbing seamless cozy"`

This combined string is what gets embedded. The intuition: the richer and more complete
the text, the better the embedding captures the pattern's true meaning.

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
This is called **seeding**. It's done by a manual script: `backend/scripts/seed_patterns.py`.

### The seeding flow

```
seed_patterns.py --limit 500
      │
      ├─→ Run 15 broad queries against Ravelry API
      │     ("sweater", "hat", "shawl", "amigurumi", "socks", ...)
      │     → collect up to 500 unique pattern IDs
      │
      ├─→ For each pattern ID:
      │     1. Call Ravelry's pattern detail endpoint → get full data
      │     2. build_pattern_text() → concatenate name + description + tags
      │     3. embed_text() → run through the AI model → 384 numbers
      │     4. UPSERT into PostgreSQL
      │          (if pattern already exists, update it; don't duplicate)
      │
      └─→ Done. 500+ patterns now have embeddings in the DB.
```

**Idempotency:** the script skips patterns that already have embeddings
(`WHERE embedding IS NOT NULL`). Run it twice — it picks up from where it left off
without creating duplicates. This is a professional property: operations you can safely
repeat without side effects.

**Rate limiting:** there's a 0.3-second sleep between Ravelry API calls to avoid triggering
Ravelry's rate limiter. Thoughtful, not just grabbing everything as fast as possible.

---

## The live search flow: step by step

Once patterns are seeded, this is what happens on every search:

```python
def semantic_search(db: Session, query: str, limit: int = 10) -> list[dict]:
    # Step 1: convert the user's query to an embedding
    query_vector = embed_text(query)
    # query_vector is now [0.12, -0.34, 0.91, ...] — 384 numbers

    # Step 2: tell PostgreSQL to check more index clusters (better recall)
    db.execute(text("SET LOCAL ivfflat.probes = 10"))

    # Step 3: find patterns with the smallest cosine distance to the query vector
    distance = Pattern.embedding.cosine_distance(query_vector)
    rows = (
        db.query(Pattern, distance.label("distance"))
        .filter(Pattern.embedding.isnot(None))  # only seeded patterns
        .order_by(distance)                     # closest first
        .limit(limit)                           # top N
        .all()
    )

    # Step 4: format results, convert distance to similarity score
    results = []
    for pattern, dist in rows:
        results.append({
            "name": pattern.name,
            "similarity_score": round(1.0 - float(dist), 4),  # 0-1, higher = better
            # ... other fields
        })
    return results
```

See the actual code at: `backend/app/search/semantic_search.py`

The `<=>` operator (cosine distance) is provided by pgvector. It's what makes this
whole thing work inside regular PostgreSQL.

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

## What makes this technically impressive (interview framing)

If you've internalized all of the above, frame it this way in an interview:

> "Instead of keyword matching, I convert both patterns and search queries into 384-
> dimensional vector embeddings using a locally-run sentence-transformers model. The
> embedding model was trained to place semantically similar text geometrically close in
> vector space. I store embeddings in PostgreSQL using pgvector, and at query time I
> embed the user's query with the same model and find the nearest-neighbor patterns using
> cosine similarity. This means 'cozy winter sweater' can surface 'chunky ribbed pullover
> in the round' even though they share no words."

That answer signals: you understand AI/ML concepts, you made conscious infrastructure
decisions (local vs. API), you can explain the math intuitively, and you connect the
technical choice to the product goal.

---

## Interview questions for this topic

**Q: Explain how your semantic search works.**
A: See the framing paragraph directly above. Practice it verbatim.

**Q: What is an embedding/vector?**
A: "A vector is a list of numbers that represents the meaning of a piece of text.
The model was trained so that similar texts produce similar vectors — they end up close
together in 384-dimensional space. It's like GPS coordinates for meaning."

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
