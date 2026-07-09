# Product Requirements Document: Woolly — Week 3+
**Version:** 1.0  
**Status:** Active  
**Title:** Search Quality, Corpus Expansion & Observability  
**Depends on:** Week 1 (Ravelry API integration) + Week 2 (semantic search, auth, project tracker, stitch counter)

---

## ⚠️ Scope Notice for Cursor

This PRD is broken into four phases in priority order. Complete and verify each phase before starting the next. Do not implement all phases in one session — each phase has a definition of done that must be verified first.

**Phase order:**
1. Corpus expansion + automated seeding
2. Hybrid retrieval (semantic + keyword BM25)
3. Two-stage reranking pipeline
4. Observability + search analytics

Do not implement A/B testing infrastructure, domain-specific model fine-tuning, or a dedicated vector store in this cycle. Those are documented in the future roadmap section.

---

## 1. Context & Goals

Week 2 delivered a working semantic search proof-of-concept: real intent matching over a local vector index, filters, caching, and a wired-up UI. The honest assessment of where it falls short:

- **Too small:** ~500 patterns vs Ravelry's full catalog. Most real queries hit the edges of the seed set.
- **Pure vector only:** No keyword matching means exact queries ("Tin Can Knits cardigan") underperform. No reranking means low-quality matches can appear in top results.
- **No visibility:** No search analytics, no relevance signals in the UI, no way to know if search is getting better or worse.

This PRD fixes all three. By the end, Woolly will have a production-grade search architecture that is genuinely interesting to explain in interviews and useful enough for real crafters.

---

## 2. Embedding Model Decision

**Keep all-MiniLM-L6-v2 as the primary embedding model. Do not switch to OpenAI.**

Rationale:
- The interview story of running embeddings locally is stronger than calling an API
- No external dependency means no outage risk and no per-query cost
- Quality is sufficient for craft pattern semantic search
- The architecture gains are from hybrid retrieval and reranking, not from a better embedding model

**Optional second-stage:** OpenAI `text-embedding-3-small` may be used exclusively for reranking (Phase 3) — called only on top-20 candidates, not for first-stage retrieval. This keeps costs near-zero while improving final result ordering. If OpenAI is unavailable, the system falls back gracefully to vector-only ranking.

---

## 3. Phase 1 — Corpus Expansion + Automated Seeding

### Goal
Grow from ~500 patterns to 5,000+ patterns. Add automated incremental seeding so the corpus stays fresh without manual re-runs.

### Why This Matters
At 500 patterns, many real queries return few or no relevant results. 5,000 patterns covers the most popular patterns across all major craft categories and makes the search feel genuinely useful to real crafters.

### 3.1 Expanded Seed Strategy

Update `scripts/seed_patterns.py`:

**Seed across all major Ravelry categories:**
```
Sweaters, Cardigans, Pullovers, Vests, Shawls, Wraps,
Hats, Mittens, Gloves, Socks, Scarves, Cowls,
Baby/Children, Toys, Home/Kitchen, Bags, Blankets/Afghans,
Amigurumi, Dishcloths, Accessories
```

**For each category, seed by:**
- Most popular (sort by `best_match`, `projects`, `rating`)
- Both knitting and crochet
- Mix of free and paid patterns

**Target:** 5,000 patterns minimum. The Ravelry API allows pagination — seed 100 patterns per request across 50+ queries.

**Idempotent:** Re-running the script skips patterns already in the DB (upsert on `ravelry_id`). Safe to run multiple times.

**Rate limiting:** 0.5s sleep between API calls. Log progress every 100 patterns.

### 3.2 Richer Embedding Text

Currently embeddings are generated from: `name + description + tags`

Expand to include more fields from `raw_data`:
```python
def build_pattern_text(pattern: dict) -> str:
    parts = [
        pattern.get("name", ""),
        pattern.get("description", ""),
        " ".join(pattern.get("tags", [])),
        pattern.get("craft", ""),
        pattern.get("difficulty", ""),
        pattern.get("category", ""),
        pattern.get("yarn_weight", ""),  # from raw_data
        pattern.get("needle_size", ""),  # from raw_data
    ]
    return " ".join(p for p in parts if p).strip()
```

Re-embed all existing patterns after this change (run seed script with `--re-embed` flag).

### 3.3 Scheduled Re-seeding

Add a background job that runs the seed script on a schedule:
- Use APScheduler (already a FastAPI-compatible Python library)
- Runs every 24 hours
- Fetches only new patterns (patterns added to Ravelry since last seed)
- Clears Redis cache after seeding so new patterns are immediately discoverable
- Logs run duration and pattern count to a `seed_runs` table

```sql
CREATE TABLE seed_runs (
    id          SERIAL PRIMARY KEY,
    started_at  TIMESTAMP DEFAULT NOW(),
    finished_at TIMESTAMP,
    patterns_added INTEGER DEFAULT 0,
    patterns_updated INTEGER DEFAULT 0,
    status      TEXT DEFAULT 'running' -- running / completed / failed
);
```

### 3.4 Phase 1 Definition of Done
- `seed_patterns.py --limit 5000` completes without errors and populates 5,000+ patterns
- Each pattern has a non-null embedding
- Searching "beginner hat" returns 10 varied, relevant results (not the same 3 patterns repeated)
- Background scheduler runs and logs to `seed_runs` table
- Cache is cleared after each seed run
- Re-seeding is idempotent (running twice doesn't duplicate patterns)

---

## 4. Phase 2 — Hybrid Retrieval (Semantic + Keyword BM25)

### Goal
Combine vector similarity search with PostgreSQL full-text search (BM25) so that both semantic intent AND exact keyword matches work well.

### Why This Matters
Pure vector search fails on exact queries. Searching "Tin Can Knits" or "Stephen West" should surface that designer's patterns at the top. Searching "Harvest Cardigan" should find that exact pattern. Currently, the embedding model has to infer intent from the query — it can't do exact matching. Hybrid retrieval fixes this.

### 4.1 Add Full-Text Search Column

```sql
-- Add tsvector column for full-text search
ALTER TABLE patterns ADD COLUMN IF NOT EXISTS search_vector tsvector;

-- Populate it
UPDATE patterns SET search_vector = to_tsvector('english',
    coalesce(name, '') || ' ' ||
    coalesce(designer, '') || ' ' ||
    coalesce(description, '') || ' ' ||
    coalesce(array_to_string(tags, ' '), '')
);

-- Index it
CREATE INDEX IF NOT EXISTS patterns_search_vector_idx
    ON patterns USING GIN (search_vector);

-- Auto-update on insert/update via trigger
CREATE OR REPLACE FUNCTION update_search_vector()
RETURNS trigger AS $$
BEGIN
    NEW.search_vector := to_tsvector('english',
        coalesce(NEW.name, '') || ' ' ||
        coalesce(NEW.designer, '') || ' ' ||
        coalesce(NEW.description, '') || ' ' ||
        coalesce(array_to_string(NEW.tags, ' '), '')
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER patterns_search_vector_update
    BEFORE INSERT OR UPDATE ON patterns
    FOR EACH ROW EXECUTE FUNCTION update_search_vector();
```

### 4.2 Hybrid Search Query

Replace the pure vector search with a hybrid query that combines both scores:

```python
def hybrid_search(
    query: str,
    filters: dict,
    limit: int = 20,  # fetch more candidates for reranking
    semantic_weight: float = 0.7,
    keyword_weight: float = 0.3,
) -> list[dict]:
    query_embedding = embedding_service.embed_text(query)
    
    # Combined query: semantic score + BM25 score, normalized and weighted
    sql = """
        WITH semantic AS (
            SELECT id,
                   1 - (embedding <=> :query_embedding) AS semantic_score
            FROM patterns
            WHERE embedding IS NOT NULL
            {filter_clause}
            ORDER BY embedding <=> :query_embedding
            LIMIT 100
        ),
        keyword AS (
            SELECT id,
                   ts_rank(search_vector, plainto_tsquery('english', :query)) AS keyword_score
            FROM patterns
            WHERE search_vector @@ plainto_tsquery('english', :query)
            {filter_clause}
        )
        SELECT p.*,
               COALESCE(s.semantic_score, 0) * :semantic_weight +
               COALESCE(k.keyword_score, 0) * :keyword_weight AS combined_score
        FROM patterns p
        LEFT JOIN semantic s ON p.id = s.id
        LEFT JOIN keyword k ON p.id = k.id
        WHERE s.id IS NOT NULL OR k.id IS NOT NULL
        ORDER BY combined_score DESC
        LIMIT :limit
    """
```

**Weight rationale:**
- 70% semantic / 30% keyword works well for natural language queries
- For exact-match queries (designer names, pattern names), keyword score dominates naturally
- Weights can be tuned based on search analytics data (Phase 4)

### 4.3 Graceful Degradation

If the full-text query returns no keyword matches (very niche query), fall back to pure semantic:
```python
if not keyword_results:
    return pure_semantic_search(query, filters, limit)
```

### 4.4 Update API Route

Update `GET /patterns/semantic-search` to use hybrid search internally. No API contract changes — same parameters, same response shape. Frontend requires no changes.

### 4.5 Phase 2 Definition of Done
- Searching "Tin Can Knits" returns Tin Can Knits patterns in top 3 results
- Searching "cozy winter sweater" still returns semantically relevant results (not just exact keyword matches)
- Searching a nonsense string returns empty results gracefully (no 500 error)
- Both semantic and keyword scores are present in the internal result objects (even if not yet shown in UI)
- The Ravelry keyword proxy fallback still works

---

## 5. Phase 3 — Two-Stage Reranking Pipeline

### Goal
Add a reranking step after hybrid retrieval that reorders the top-20 candidates using a cross-encoder model, dramatically improving result quality for ambiguous queries.

### Why This Matters for Interviews
This is the most technically sophisticated piece of the whole project and the thing that separates "I used pgvector" from "I built a production search pipeline." Two-stage retrieval (ANN + reranking) is how Google, Bing, and every serious search product works. Being able to explain why is a strong signal.

**The architecture:**
```
Stage 1 (Fast): Hybrid retrieval → top 20 candidates
      ↓
Stage 2 (Accurate): Cross-encoder reranker → reordered top 10
      ↓
Return top 10 to user
```

Stage 1 is fast (vector index + BM25, sub-10ms). Stage 2 is slower but only runs on 20 candidates, keeping total latency acceptable (~100-200ms on CPU).

### 5.1 Cross-Encoder Reranker

**Model:** `cross-encoder/ms-marco-MiniLM-L-6-v2` from sentence-transformers

Unlike bi-encoders (which embed query and document separately), a cross-encoder takes the query and document together and outputs a relevance score directly. This is much more accurate but too slow to run over thousands of documents — hence the two-stage approach.

```python
# services/reranking_service.py
from sentence_transformers import CrossEncoder

class RerankingService:
    def __init__(self):
        self.model = CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')
    
    def rerank(self, query: str, candidates: list[dict], top_n: int = 10) -> list[dict]:
        pairs = [(query, self._pattern_to_text(p)) for p in candidates]
        scores = self.model.predict(pairs)
        
        ranked = sorted(
            zip(candidates, scores),
            key=lambda x: x[1],
            reverse=True
        )
        
        results = []
        for pattern, score in ranked[:top_n]:
            pattern["rerank_score"] = float(score)
            results.append(pattern)
        
        return results
    
    def _pattern_to_text(self, pattern: dict) -> str:
        return f"{pattern['name']} by {pattern['designer']}. {pattern['description'][:200]}"
```

Load the cross-encoder as a singleton at startup, same pattern as the embedding service.

### 5.2 Updated Search Pipeline

```python
async def search(query: str, filters: dict, limit: int = 10) -> list[dict]:
    # Stage 1: hybrid retrieval, fetch 2x candidates
    candidates = await hybrid_search(query, filters, limit=limit * 2)
    
    if not candidates:
        return []
    
    # Stage 2: rerank candidates
    results = reranking_service.rerank(query, candidates, top_n=limit)
    
    return results
```

### 5.3 Similarity Score in UI

Now that results have a meaningful rerank score, surface it subtly in the UI:

- Add a thin colored relevance bar at the bottom of each card (burgundy, width proportional to score)
- On hover: show "Strong match" / "Good match" / "Possible match" label based on score threshold
- Do not show the raw number — just the qualitative signal

This is a small UI change but makes the search feel more trustworthy to real users and gives you something concrete to talk about in interviews ("I surfaced relevance signals in the UI so users could understand why results appeared").

### 5.4 Score Thresholds

```python
def relevance_label(score: float) -> str:
    if score > 0.7:   return "Strong match"
    if score > 0.4:   return "Good match"
    return "Possible match"
```

Filter out results below a minimum threshold (0.1) to prevent clearly irrelevant results from appearing.

### 5.5 Phase 3 Definition of Done
- Two-stage pipeline works end to end (hybrid → rerank → return)
- Rerank score is present in API response
- Relevance indicator visible in card UI on hover
- Results below threshold 0.1 are filtered out
- Total search latency under 500ms for a cold cache query (measure this)
- Latency logged per request so you have data

---

## 6. Phase 4 — Observability + Search Analytics

### Goal
Add the instrumentation to know whether search is actually good. This is the difference between "I built a search engine" and "I measured and improved a search engine" — the latter is a much stronger interview story.

### Why This Matters
Without analytics you can't answer "how do you know it's working?" in an interview. With analytics you can say "save rate on top-3 results is 23%, click-through to Ravelry is 41%, and both improved after I added reranking." That's a compelling story.

### 6.1 Search Events Table

```sql
CREATE TABLE search_events (
    id              SERIAL PRIMARY KEY,
    session_id      TEXT NOT NULL,       -- anonymous session token
    user_id         INTEGER REFERENCES users(id) ON DELETE SET NULL,
    query           TEXT NOT NULL,
    filters         JSONB DEFAULT '{}',
    result_count    INTEGER,
    top_result_id   INTEGER REFERENCES patterns(id) ON DELETE SET NULL,
    latency_ms      INTEGER,
    cache_hit       BOOLEAN DEFAULT FALSE,
    search_type     TEXT DEFAULT 'hybrid', -- hybrid / semantic / keyword
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE TABLE result_interactions (
    id              SERIAL PRIMARY KEY,
    search_event_id INTEGER REFERENCES search_events(id) ON DELETE CASCADE,
    pattern_id      INTEGER REFERENCES patterns(id) ON DELETE CASCADE,
    position        INTEGER NOT NULL,     -- 1-indexed position in results
    action          TEXT NOT NULL,        -- 'save' / 'ravelry_click' / 'card_expand'
    rerank_score    FLOAT,
    created_at      TIMESTAMP DEFAULT NOW()
);
```

### 6.2 Logging in the Search Pipeline

Log every search event after results are returned:

```python
async def log_search_event(
    session_id: str,
    user_id: int | None,
    query: str,
    filters: dict,
    results: list[dict],
    latency_ms: int,
    cache_hit: bool,
):
    # Fire and forget — don't block the response
    asyncio.create_task(_write_search_event(...))
```

Log every user interaction (save, Ravelry click) with position and score.

### 6.3 Key Metrics to Track

| Metric | Why It Matters |
|---|---|
| Queries per day | Usage baseline |
| Cache hit rate | Redis efficiency |
| Average latency (ms) | Performance |
| Zero-result rate | Corpus coverage gaps |
| Click-through rate (CTR) | Are results relevant? |
| Save rate on top-3 | Are top results good? |
| Most common queries | What users actually want |
| Most common zero-result queries | Where to expand corpus |

### 6.4 Internal Analytics Endpoint

Add a simple `GET /admin/analytics` endpoint (admin-only, not user-facing) that returns:

```json
{
  "queries_today": 142,
  "cache_hit_rate": 0.67,
  "avg_latency_ms": 187,
  "zero_result_rate": 0.08,
  "top_queries": ["chunky cardigan", "beginner hat", ...],
  "zero_result_queries": ["lace weight gloves size 6", ...]
}
```

This is your feedback loop for corpus expansion — zero-result queries tell you exactly which categories to seed next.

### 6.5 Pagination

Add pagination to the search results:

Backend:
```
GET /patterns/semantic-search?q=...&limit=10&offset=0
```

Frontend:
- "Load more" button below results (simpler than page numbers, works better on mobile)
- Appends next page to existing results
- Disabled when no more results

### 6.6 Empty State Guidance

When a search returns 0 results, don't just show nothing. Show actionable guidance:

```
No patterns found for "lace weight fingerless gloves size 6"

Try:
• Removing some filters
• Searching "fingerless gloves" (broader)
• Searching "lace weight accessories"
```

The suggestions should be generated dynamically by stripping filters and simplifying the query, not hardcoded.

### 6.7 Phase 4 Definition of Done
- Every search query writes a row to `search_events`
- Every save and Ravelry click writes a row to `result_interactions`
- `GET /admin/analytics` returns real data
- Pagination works — "Load more" returns next page of results
- Zero-result searches show actionable guidance
- Cache hit rate is visible in analytics

---

## 7. Interview Talking Points

Study this section before any interview where Woolly comes up.

**"Walk me through your search architecture."**
"It's a two-stage pipeline. Stage one is hybrid retrieval — I combine vector cosine similarity using pgvector with PostgreSQL full-text BM25 ranking, weighted 70/30 toward semantic. This handles both intent-based queries and exact keyword matches like designer names. Stage one returns 20 candidates. Stage two is a cross-encoder reranker — unlike the bi-encoder that embeds query and document separately, the cross-encoder takes them together and produces a direct relevance score. Much more accurate but too slow to run over thousands of documents, which is why you do it only on the 20 candidates from stage one. Final output is the top 10 reranked results."

**"Why hybrid instead of pure semantic?"**
"Pure vector search fails on exact queries. If a user searches 'Tin Can Knits' they want that designer's patterns at the top — the embedding model can't guarantee that because it's optimizing for semantic similarity, not exact match. BM25 handles exact matching naturally. The combination gets you the best of both."

**"How do you know your search is actually good?"**
"I instrumented every search event — query, latency, cache hit, result count — and every user interaction — save, click-through to Ravelry, position in results. I track save rate on top-3 results as my primary quality signal. After adding reranking, save rate improved from X% to Y%. Zero-result queries tell me where to expand the corpus next."

**"What would you do at scale?"**
"A few things. First, IVFFlat is an approximate nearest neighbor index — at 100k+ patterns I'd tune the lists parameter or move to HNSW which has better recall at scale. Second, I'd move embedding generation to an async background queue so seeding doesn't block. Third, if PostgreSQL became a bottleneck for vector search I'd evaluate dedicated vector stores like Pinecone or Weaviate, though pgvector handles millions of vectors fine with proper indexing. Fourth, I'd fine-tune the embedding model on craft-specific text to improve domain relevance."

**"Why not just use OpenAI embeddings?"**
"I chose to run all-MiniLM-L6-v2 locally for a few reasons: no external dependency means no outage risk and no per-query cost, the model is small enough to run on CPU with acceptable latency, and for a craft pattern domain the quality difference vs a paid API is marginal. The bigger quality gains came from hybrid retrieval and reranking, not from a better embedding model."

---

## 8. Future Roadmap (Context Only — DO NOT BUILD)

### A/B Testing Infrastructure
Run semantic-only vs hybrid vs hybrid+reranking simultaneously for different user segments. Use LaunchDarkly feature flags to control which pipeline each user hits. Compare save rates across variants. This directly applies Shreya's professional LaunchDarkly experience to a personal project — strong interview story.

### Domain-Specific Model Fine-Tuning
Fine-tune all-MiniLM-L6-v2 on craft pattern data using contrastive learning. Requires a labeled dataset of (query, relevant pattern, irrelevant pattern) triplets. Could be generated from save history once you have enough users. Adds significant interview depth.

### Similar Patterns Feature
"Users who saved this also saved..." style recommendations. Implement as collaborative filtering over the `saved_patterns` table once there's enough user data. Can also do item-item similarity using the existing embeddings — patterns with similar vectors.

### AWS Deployment
ECS + RDS + ElastiCache + S3 + CloudFront. Do after the app is working and has real users. No point paying for AWS infra on a half-built product.

### Freemium Tier Gating
Feature flags via LaunchDarkly controlling access to advanced features (pixel grid maker, image-to-grid, unlimited saves). Stripe integration deferred until there is validated user demand.
