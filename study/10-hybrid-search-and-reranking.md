# 10 — Hybrid Search & Reranking

**The headline feature: how Woolly finds the right patterns through a two-stage pipeline.**

This is the most important file for interview prep. If you can explain this pipeline fluently,
you demonstrate real search-engineering depth — not just "I called an embedding API."

Read `03-semantic-search-embeddings.md` and `04-pgvector-vector-databases.md` first if you
haven't already. This file builds on both.

---

## The problem with any single search method

Each retrieval method has blind spots:

| Method | Great at | Bad at |
|---|---|---|
| **Semantic (vector)** | Natural-language intent ("cozy winter sweater" → chunky pullover) | Exact designer names, rare terms, brand-style names like "PetiteKnit" |
| **Keyword (BM25)** | Exact words in titles/descriptions/tags | Synonyms, intent, paraphrasing |
| **Designer trigram** | Brand names with no spaces ("Petite Knit" → PetiteKnit) | General semantic queries with no designer signal |

**Woolly's answer:** combine all three in stage 1 (hybrid retrieval), then use a cross-encoder
in stage 2 (reranking) to pick the truly best matches from the candidate pool.

**Interview one-liner:**
> "I use a two-stage search pipeline. Stage 1 is fast hybrid retrieval over the whole corpus —
> vector similarity, PostgreSQL full-text ranking, and designer trigram matching fused with
> weighted scores. Stage 2 is a cross-encoder that re-scores query-document pairs together on
> the top ~60 candidates. The API caches the full ranked list so pagination is free."

---

## The two-stage pipeline: overview

```
User query + filters
        │
        ▼
┌───────────────────────────────────────────────────────────┐
│  STAGE 1: Hybrid Retrieval (fast, runs over corpus)       │
│  backend/app/search/hybrid_search.py                       │
│                                                            │
│  ┌─────────────┐  ┌─────────────┐  ┌──────────────────┐  │
│  │  Semantic   │  │  Keyword    │  │  Designer        │  │
│  │  (pgvector) │  │  (BM25/FTS) │  │  (pg_trgm)       │  │
│  │  weight 0.6 │  │  weight 0.25│  │  weight 0.15     │  │
│  └──────┬──────┘  └──────┬──────┘  └────────┬─────────┘  │
│         └────────────────┼───────────────────┘             │
│                          ▼                                 │
│              Weighted score fusion → top 60 candidates     │
└──────────────────────────┬────────────────────────────────┘
                           │
                           ▼
┌───────────────────────────────────────────────────────────┐
│  STAGE 2: Cross-Encoder Reranking (accurate, small pool) │
│  backend/app/services/reranking_service.py                 │
│                                                            │
│  Score (query, "Pattern Name by Designer. Description")    │
│  pairs together → reorder → filter by relevance threshold  │
│  → return top 50 with rerank_score + relevance_label     │
└──────────────────────────┬────────────────────────────────┘
                           │
                           ▼
              Cache full list in Redis (30 min)
                           │
                           ▼
              API slices page via offset/limit → JSON
```

See the orchestrator at: `backend/app/search/pipeline.py`

---

## Stage 1: Hybrid retrieval in detail

### The three "legs"

**Leg 1 — Semantic (60% weight):**
- Embed the query with the bi-encoder (`all-MiniLM-L6-v2`)
- Query pgvector for the top 100 nearest patterns by cosine distance
- Scores are max-normalized to [0, 1] within the semantic candidate pool

**Leg 2 — Keyword / BM25 (25% weight):**
- PostgreSQL full-text search on the `search_vector` column (`tsvector` type)
- Uses `plainto_tsquery('english', :query)` to tokenize the query
- Ranks with `ts_rank(search_vector, query)` — PostgreSQL's BM25-like scoring
- GIN index on `search_vector` makes this fast

**Leg 3 — Designer trigram (15% weight):**
- Strips whitespace from query and designer name: `"Petite Knit"` → `"petiteknit"`
- Uses `pg_trgm` similarity function
- Threshold 0.4 — catches exact brand matches (1.0) and typos (~0.62)
- Why needed: full-text search tokenizes "petite knit" as `petit & knit`, which never
  matches the single token `petiteknit`

### Score fusion

Each leg's scores are max-normalized within that leg's pool, then combined:

```
combined_score = (semantic_norm × 0.6 + keyword_norm × 0.25 + designer_norm × 0.15)
                 / sum_of_active_weights
```

**Key detail — weight renormalization:** If a pattern only appears in the designer leg (not
semantic or keyword), the active weights are renormalized. A designer-only exact match isn't
structurally capped at 0.15 — it can score 1.0 if it's the only signal.

Patterns appear in the final pool if they match *any* leg (OR logic), ranked by combined score.

### Semantic-only fallback

Before running the full hybrid SQL, Woolly checks if keyword and designer legs would return
anything:

```python
keyword_n, designer_n = _leg_match_counts(db, query, ...)
if keyword_n == 0 and designer_n == 0:
    return semantic_search(db, query, limit, ...)  # pure vector fallback
```

**Why:** For niche natural-language queries ("something for my cat"), keyword and designer
legs add noise, not signal. Skipping the expensive hybrid SQL and going straight to semantic
search is faster and equally good.

See: `backend/app/search/hybrid_search.py`

---

## Filters: applied before ranking

Filters (craft, difficulty tier, free/paid, category) are SQL `WHERE` clauses applied
*before* vector ranking and *inside* each hybrid leg's CTE.

```python
# backend/app/search/filters.py
DIFFICULTY_RANGES = {
    "beginner": (0.0, 3.5),
    "intermediate": (3.5, 6.5),
    "advanced": (6.5, 10.0),
}
```

**Why before ranking:** "Top 10 beginner sweaters" should mean the 10 most similar patterns
*among beginners* — not the 10 most similar patterns globally with beginners filtered out
afterward.

Difficulty is stored as Ravelry's 0–10 float string (e.g. `"3.2"`), cast to float in SQL.

---

## Stage 2: Cross-encoder reranking

### Bi-encoder vs cross-encoder — know this cold

| | Bi-encoder (embedding model) | Cross-encoder (reranker) |
|---|---|---|
| **How it works** | Embeds query and document *separately* | Scores query + document *together* as one input |
| **Speed** | Fast (~20ms per text) | Slow (~5–10ms per pair) |
| **Accuracy** | Good for retrieval (recall) | Much better for ranking (precision) |
| **Scale** | Can run over entire corpus | Only feasible on small candidate sets |
| **Woolly model** | `all-MiniLM-L6-v2` | `cross-encoder/ms-marco-MiniLM-L-6-v2` |

**Analogy:** the bi-encoder is like comparing two people's GPS coordinates — fast, works at
scale, but misses nuance. The cross-encoder is like having both people sit in the same room
and asking "how well do these two actually get along?" — much more accurate, but you can only
do it for a small group.

### What the reranker does

1. Takes up to 60 candidates from hybrid search
2. Builds text pairs: `(query, "Pattern Name by Designer. First 200 chars of description")`
3. Runs `CrossEncoder.predict(pairs)` — outputs raw logits
4. Applies sigmoid to map logits to 0–1 (`rerank_score`)
5. Assigns labels: "Strong match" (>0.7), "Good match" (>0.4), "Possible match"
6. Filters out scores below 0.1, but keeps at least 3 results (never returns empty purely
   due to threshold)

### Graceful degradation

```python
try:
    results = reranking_service.rerank(query, candidates, top_n=max_results)
except Exception:
    results = candidates[:max_results]  # hybrid results, no rerank_score
```

If the reranker fails, search still works — users get hybrid-ranked results without
`rerank_score` or `relevance_label`. Search must never break because stage 2 is down.

See: `backend/app/services/reranking_service.py`

---

## Caching and pagination strategy

The API does **not** re-run the pipeline for every page. Instead:

1. Pipeline runs once → produces up to 50 ranked results
2. Full list cached in Redis keyed by `query + filters`
3. Each page request slices `full[offset:offset+limit]` from the cached list

```python
# backend/app/api/patterns.py
cache_key = semantic_cache_key(query, craft=craft, difficulty=difficulty, free=free, category=category)
full = run_search_pipeline(...)  # or load from cache
page = full[offset : offset + limit]
```

**Why this design:**
- Page 2 of the same search is a cache HIT — no AI, no DB
- Relevance order is consistent across pages (rank 11 is always rank 11)
- "Load more" doesn't recompute — it just slices deeper into the cached list

Cache key example:
- Query: `"cozy sweater"`, craft: `knitting`, free: `true`
- Key: `semantic:cozy sweater:craft=knitting:free=true`

---

## The full end-to-end flow (say this out loud)

**Step 1:** User types "petite knit cardigan", selects craft=knitting, presses search.

**Step 2:** React calls `GET /patterns/semantic-search?q=petite+knit+cardigan&craft=knitting`.

**Step 3:** FastAPI checks Redis for key `semantic:petite knit cardigan:craft=knitting`.
- **Cache hit:** slice the cached list, return page. Done.
- **Cache miss:** continue.

**Step 4:** `pipeline.search()` runs hybrid retrieval:
- Semantic leg: embed query, pgvector nearest-neighbor with craft filter
- Keyword leg: `search_vector @@ plainto_tsquery('petite knit cardigan')`
- Designer leg: trigram similarity on stripped names — "petiteknit" matches PetiteKnit
- Fuse scores, return top 60 candidates

**Step 5:** Cross-encoder reranks all 60 pairs, returns top 50 with `rerank_score`.

**Step 6:** Full list saved to Redis for 30 minutes.

**Step 7:** First page (offset=0, limit=10) sliced and returned as JSON.

**Step 8:** React renders `PatternCard` components with relevance bars and labels.

---

## Why these weights (0.6 / 0.25 / 0.15)?

Not magic — they're a starting point based on what each leg is best at:

- **Semantic dominates** because Woolly's core value is intent-based discovery
- **Keyword gets meaningful weight** because exact terms matter (pattern names, techniques)
- **Designer is smaller** because it's a specialized signal — powerful when relevant, noisy
  when not

**Interview nuance:** "I'd tune these with offline evaluation — measure NDCG or MRR on a
labeled query set and adjust weights. The current values prioritize semantic recall while
letting keyword and designer signals break ties and catch exact matches."

---

## Database infrastructure supporting hybrid search

Set up in `backend/app/db/init_db.py`:

| Feature | SQL | Purpose |
|---|---|---|
| pgvector + IVFFlat | `CREATE INDEX ... ivfflat (embedding vector_cosine_ops)` | Fast semantic leg |
| Full-text search | `search_vector tsvector` + GIN index + update trigger | Fast keyword leg |
| Trigram extension | `CREATE EXTENSION pg_trgm` + GIN index on designer | Fast designer leg |

The `search_vector` column is auto-populated by a PostgreSQL trigger on INSERT/UPDATE from
name + designer + description + tags.

---

## Interview questions for this topic

**Q: Walk me through your search architecture.**
A: "Two-stage pipeline. Stage 1 is hybrid retrieval: I combine pgvector semantic search,
PostgreSQL full-text BM25 ranking, and pg_trgm designer name matching with weighted score
fusion. I pull 60 candidates. Stage 2 is a cross-encoder reranker that scores query-document
pairs together for much higher precision. The full ranked list up to 50 results is cached in
Redis per query and filter combination, and the API paginates by slicing that cached list.
If the reranker fails, hybrid results pass through unchanged."

**Q: Why hybrid instead of pure semantic search?**
A: "Pure semantic misses exact matches — designer names like PetiteKnit, specific technique
terms, pattern titles with unusual wording. Keyword search catches those. But keyword search
misses intent and paraphrasing, which semantic handles. Combining them gives better recall
than either alone. The cross-encoder then improves precision on the merged candidate set."

**Q: What is reranking and why not run it over the whole database?**
A: "Reranking uses a cross-encoder that scores the query and document together — much more
accurate than separate embeddings, but too slow to run on thousands of patterns per query.
So I only rerank the ~60 candidates from hybrid retrieval. This is the standard production
pattern: fast bi-encoder retrieval for recall, slow cross-encoder for precision."

**Q: What's the difference between a bi-encoder and a cross-encoder?**
A: "A bi-encoder embeds query and document independently, then compares vectors — fast,
scalable, good for finding candidates. A cross-encoder feeds query and document into the
same model and outputs a relevance score — slow, but captures interactions between query
terms and document terms that separate embeddings miss. Woolly uses both: bi-encoder for
retrieval, cross-encoder for reranking."

**Q: How do filters work with vector search?**
A: "Filters are SQL WHERE clauses applied before ranking in every leg of hybrid search.
For semantic search, that means pgvector only considers patterns matching the filter when
finding nearest neighbors — so 'beginner knitting sweaters' returns the most similar
patterns within that filtered set, not globally similar patterns with beginners filtered out
after."

**Q: How would you evaluate and improve search quality?**
A: "Build a labeled evaluation set — 50–100 real queries with expected relevant patterns.
Measure NDCG@10 and MRR. A/B test weight changes, probe counts, rerank pool size. Add
query logging to find zero-result queries. Consider learning-to-rank if I get enough
click-through data. The pipeline is modular — I can swap legs or weights without touching
the API contract."

**Q: How would this scale to 100,000+ patterns?**
A: "Stage 1 scales with better indexes — tune IVFFlat lists/probes or switch to HNSW. The
hybrid SQL query gets heavier, so I'd consider pre-filtering by category/craft before
vector search. Stage 2 stays the same — reranking 60–100 candidates is constant time
regardless of corpus size. I'd move seeding to a distributed queue and add read replicas
for search queries. If PostgreSQL became a bottleneck, the search layer is isolated enough
to swap in a dedicated vector store without changing the API."
