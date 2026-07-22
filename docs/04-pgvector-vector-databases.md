# 04 — pgvector & Vector Databases

**How Woolly stores and searches 384-dimensional embeddings inside PostgreSQL.**

This builds directly on `03-semantic-search-embeddings.md`. If you haven't read that,
do it first — the concepts here won't make sense without it.

---

## The problem: regular databases can't handle "find the closest" queries

A regular database is great at exact lookups and range queries:
- "Give me all patterns where `is_free = true`" → easy
- "Give me the pattern where `ravelry_id = 12345`" → easy
- "Give me all patterns with `difficulty < 3`" → easy

But "give me the 10 patterns whose 384-number embedding is closest to this other
384-number embedding" is a completely different kind of question. Regular SQL has no
built-in operator for that. You'd have to write a very ugly query that computes distances
to every row, which is slow and doesn't scale.

This is what **vector databases** solve. They're built from the ground up for one thing:
storing vectors and finding nearest neighbors fast.

---

## Two options: dedicated vector store vs pgvector

When you need vector search, you have two main paths:

### Option A: Dedicated vector database (Pinecone, Weaviate, Qdrant, Chroma)

A completely separate database built only for vector search. It has excellent performance
for this specific task.

**Pros:** Built and optimized specifically for vectors. Scales extremely well. Feature-rich
(filtering, metadata storage, namespaces).

**Cons:** Adds a *fourth* piece of infrastructure to run and maintain. Your structured
data (pattern name, designer, description) lives in PostgreSQL; your embeddings live in the
vector store. You have to keep them in sync. Two databases = two failure points.

### Option B: pgvector (Woolly's choice)

A PostgreSQL **extension** that adds vector capabilities to your existing PostgreSQL database.
You keep all your data — structured fields *and* embeddings — in one place.

**Pros:** One database, all data. No sync problem. Simpler infrastructure. PostgreSQL's
mature transaction system and query planner still apply. Great for datasets under a few
million rows.

**Cons:** Not as performant as dedicated solutions at extreme scale. Slightly more limited
in vector-specific features.

**Why Woolly chose pgvector:** At 500–5,000 patterns, pgvector is more than sufficient.
Adding a fourth infrastructure piece (a dedicated vector DB) before you need it is
premature complexity. The PRD explicitly says "one database, two jobs — simpler to run
and reason about."

**Good interview answer:** "I chose pgvector over a dedicated vector store because at
my current dataset size (500 patterns), the performance is equivalent and keeping one
database is simpler operationally. Pinecone would be worth considering if the dataset
grows to millions of patterns or if query volume gets high enough to bottleneck
PostgreSQL."

---

## What pgvector actually is

pgvector is a PostgreSQL extension — a plug-in that adds new capabilities to PostgreSQL.
In Woolly, it's one of three search indexes in the same database (alongside full-text GIN
and designer trigram GIN). The semantic leg of hybrid search uses pgvector.

pgvector adds:

1. **A new data type:** `vector(384)` — a column that stores a list of 384 floats
2. **New operators:** `<=>` (cosine distance), `<->` (Euclidean distance), `<#>` (dot product)
3. **New index types:** IVFFlat and HNSW — specialized indexes for fast nearest-neighbor search

To use it, you run:
```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

That's it. After that, you can use `vector` as a column type in any table.

In Woolly's `patterns` table:
```sql
embedding vector(384)
```

This stores the 384-float embedding for each pattern. The `(384)` specifies the dimension
— every vector in this column must have exactly 384 numbers.

---

## The cosine distance operator: `<=>`

pgvector adds the `<=>` operator between two vectors. It computes **cosine distance**
(1 - cosine similarity).

```sql
-- "give me the 10 patterns most similar to this query vector, ordered by closeness"
SELECT name, embedding <=> '[0.12, -0.34, 0.91, ...]'::vector AS distance
FROM patterns
WHERE embedding IS NOT NULL
ORDER BY distance ASC
LIMIT 10;
```

Smaller distance = more similar. ORDER BY distance ASC = most similar first.

In SQLAlchemy (Python ORM), this looks like:
```python
distance = Pattern.embedding.cosine_distance(query_vector)
rows = db.query(Pattern, distance.label("distance")).order_by(distance).limit(10).all()
```

The pgvector Python package teaches SQLAlchemy how to use the `<=>` operator, so you
write Python and it generates the right SQL.

---

## The IVFFlat index: making search fast

Without an index, "find the closest vector" means comparing your query to *every single row*
in the table — a full table scan. For 500 patterns that's fast. For 500,000 patterns it
would be seconds.

An **index** is a data structure that helps the database find things faster without
scanning everything.

### The drawer-dividers analogy

Imagine you have 500 recipe cards randomly mixed in a big box. To find "recipes similar
to chicken alfredo," you'd have to read every card. Slow.

Now imagine you sort the cards into 100 dividers/sections by general flavor profile:
- Dividers 1-10: Italian/pasta
- Dividers 11-20: Asian
- Dividers 21-30: Mexican
- ... and so on.

Now you can go directly to the Italian/pasta section (10 cards) and compare there instead
of all 500. Much faster.

IVFFlat does the same thing with vectors. "IVF" = Inverted File — it divides the vector
space into **clusters** (the drawers), and for each query, only checks the nearest few
clusters instead of all vectors.

### The `lists` parameter

```sql
CREATE INDEX IF NOT EXISTS patterns_embedding_idx
    ON patterns USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);
```

`lists = 100` means "divide the vector space into 100 clusters." This is a tuning
parameter:
- Too few lists → each cluster is too big → still slow
- Too many lists → hard to know which cluster to look in → misses good matches
- Rule of thumb: `lists = rows / 1000` (capped at a few hundred)

For 500 patterns, 100 lists is actually more clusters than needed — but it's fine.
It's set up so the index structure is correct for when the dataset grows.

### The `probes` parameter

```python
db.execute(text("SET LOCAL ivfflat.probes = 10"))
```

`probes = 10` tells the index: "when searching, check the 10 nearest clusters instead
of just the 1 nearest." This is the accuracy vs. speed trade-off:

- `probes = 1` → super fast, but might miss good matches (approximate)
- `probes = 10` → a bit slower, but much higher recall (still approximate, but more accurate)
- `probes = lists` → exact, but now it's a full scan (defeats the purpose)

Woolly uses 10 because the dataset is small enough that 10 probes are fast AND gives much
better recall than the default of 1. The comment in the code explains this:
```python
# IVFFlat is approximate: with lists=100 and a small seed set (~500 rows),
# the default of probing 1 list can return fewer than `limit` results.
```

---

## Approximate nearest neighbor (ANN): the trade-off

IVFFlat is an **approximate** nearest-neighbor algorithm. This means it might not always
find the *mathematically* closest vector — it finds results that are very close but not
guaranteed to be the absolute best.

**This is fine for search.** In a keyword search, "wrong" means returning garbage. In
vector search, "approximate" means returning the 8th most similar pattern when the 7th
was theoretically more similar. Users can't tell the difference. The speed gain from
ANN vs. exact search is enormous.

This trade-off is well understood and universally accepted in production search systems.
Google, Spotify, YouTube — all use ANN algorithms. Mention it to show you understand the
nuance.

---

## HNSW: the other index type (mentioned for context)

**HNSW** (Hierarchical Navigable Small World) is the other major index algorithm in
pgvector (added later). It generally has better recall than IVFFlat at the same speed,
but uses more memory to build.

pgvector added HNSW support in version 0.5. For Woolly's dataset size, IVFFlat is
completely adequate. But if an interviewer asks "what would you change at scale?" —
"I'd evaluate switching from IVFFlat to HNSW as the dataset grows, since HNSW tends to
have better recall characteristics at larger scales" is a strong answer.

---

## Putting it all together: the full vector search query

Here's what happens in the database when a semantic search runs:

1. **Input:** query vector `[0.12, -0.34, 0.91, ...]` (384 numbers)

2. **Index lookup:** pgvector uses the IVFFlat index to find which of the 100 clusters
   the query vector falls into. With `probes = 10`, it checks the 10 nearest clusters
   instead of just 1.

3. **Distance calculation:** within those clusters, it computes cosine distance from the
   query vector to each pattern's stored embedding.

4. **Sort and limit:** returns the 10 patterns with the smallest distance (most similar).

5. **Back to Python:** Woolly converts `distance` to `similarity_score = 1 - distance`
   (so higher = better) and sends the results back.

The total time for this query: sub-10ms on a 500-pattern dataset. Even at 10,000 patterns
with the IVFFlat index, it stays well under 50ms.

---

## The `raw_data` JSONB column: a detail worth explaining

The `patterns` table has a column:
```sql
raw_data JSONB
```

This stores the complete, unprocessed JSON response from Ravelry's API for each pattern.
Why?

1. **Future-proofing:** if you decide to add a new field to the embedding later (like
   `yarn_weight`), the raw data is already there — you don't need to re-query Ravelry.
   Just run a new embed pass over `raw_data`.

2. **Debugging:** you can always look at the original source to understand why a pattern
   was embedded a certain way.

3. **Flexibility:** Ravelry's API has dozens of fields. Rather than trying to predict all
   the ones you'll ever need and creating columns for all of them, you store the full
   payload and parse out what you need.

`JSONB` (JSON Binary) is PostgreSQL's binary-encoded JSON format — faster to query
than plain text JSON and supports indexing.

---

## Interview questions for this topic

**Q: What is pgvector?**
A: "pgvector is a PostgreSQL extension that adds a `vector` data type, similarity search
operators like `<=>` for cosine distance, and specialized indexes for fast nearest-neighbor
search. It lets me do ML-style vector search inside a regular PostgreSQL database without
running a separate vector store."

**Q: Why not use a dedicated vector database like Pinecone?**
A: "At Woolly's current scale (500-5,000 patterns), pgvector is more than sufficient and
keeping one database is operationally simpler — no sync problem between structured data
and embeddings. If the dataset grew to millions of patterns and query volume became a
bottleneck, I'd evaluate dedicated vector stores. The architecture already isolates the
search layer, so it could be swapped without touching the API."

**Q: What is IVFFlat?**
A: "IVFFlat is an approximate nearest-neighbor index. It divides the vector space into
clusters — think drawer dividers — so instead of comparing the query to every row, it
only checks the nearest clusters. The `probes` parameter controls how many clusters to
check, trading accuracy for speed. I set it to 10 to improve recall on a small dataset."

**Q: What does 'approximate' mean in approximate nearest neighbor?**
A: "It means the index might not return the mathematically closest vectors in all cases —
it returns very close results very fast. In practice, the difference between the 7th and
8th most similar pattern is imperceptible to a user. ANN is the standard approach in
every production search system — exact search over millions of vectors is too slow."

**Q: How does the `<=>` operator work?**
A: "It's provided by pgvector. It computes cosine distance between two vector columns.
Cosine distance is 1 minus cosine similarity — so 0 means identical, 1 means completely
different. Sorting by this value ascending gives you the most similar patterns first."

**Q: How would this scale to 100,000 patterns?**
A: "I'd tune the `lists` parameter in the IVFFlat index (rule of thumb: rows/1000), and
potentially switch to HNSW which tends to have better recall at larger scale. I'd also
move the seeding pipeline to an async background job. If PostgreSQL's query throughput
became a bottleneck, I'd evaluate a dedicated vector store, but pgvector handles millions
of vectors fine with proper indexing."
