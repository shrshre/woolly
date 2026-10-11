# Backlog

## Bugs

### Search

- [ ] **Bookmark icon does not show up**
- [ ] **"hat to match my mittens" returns mittens** — Top 3 are mitten patterns (cross-encoder > 0.99); the reranker rewards "mittens" and misses that the wanted object is a hat. Found by `search-negative-002`. Labeled nDCG@10 0.60; real hat-and-mitten sets sit at ranks 4–5. Fix in the iterate phase against that score.
- [ ] **Keyword leg drops out on natural-language queries** — `plainto_tsquery` requires every word to match, so "dishcloth for the kitchen", "something for my dog", and "blanket for the couch" match 0 / 3 / 5 patterns. When keyword and designer legs are empty, hybrid falls back to vector-only. Try OR semantics (`websearch_to_tsquery` or OR-joined `to_tsquery`) and measure on the labeled set before shipping.
- [ ] **"blanket for the couch" returns no throws** — Corpus has 61 throws; only one reaches any variant's top 10. Vector/hybrid return baby blankets; production returns a cardigan and mittens (see reranker item). Labeled in `search-intent-016`.
- [ ] **Reranker loses to vector-only on some intent queries** — Production beats vector-only overall (nDCG@10 0.888 vs 0.826) but loses on "blanket for the couch", "granny square bag", "oversized cardigan", and crochet blanket / paid. Cross-encoder rewards description phrase overlap over what the pattern is. Ideas: blend stage-1 into rerank score, or rerank on name + category + tags.
- [ ] **7% of relevant patterns never reach the reranker** — `candidate_recall@60` is 0.928; as low as 0.71 for "fingerless mittens" and 0.76 for "baby blanket". Raising `RERANK_POOL` or fixing the keyword leg should show up here first.
- [ ] **First request after deploy pays ~2.6 s to load the reranker** — Cross-encoder loads lazily (~500 MB saved at boot); first search measured 2,879 ms in `rerank` vs warm p50 240 ms. Options: load in lifespan if Railway memory allows, or warm with one dummy rerank after startup.
- [ ] **Rerank is ~75% of search latency** — Uncached: rerank p50/p95 240/288 ms of total 319/373 ms. Latency work starts with `RERANK_POOL` (60) or a smaller cross-encoder, measured against the search eval nDCG floor.

### Ask Woolly

- [ ] **Extraction still invents `difficulty` and `free` filters** — Gift-for-beginner becomes `difficulty: beginner`; "paid is fine" becomes `free: false`. Prompt rules failed on `gpt-4o-mini` (`ask-filter-004`, `ask-filter-006`). Craft is already guarded in code; these need a similar check or soft filters.
- [ ] **Answer model gets numeric comparisons wrong** — Called 3.8/10 "similar" to 2.3/10 (`ask-followup-001`); also mis-compared warmth vs yarn weight (`ask-intent-004`). Ideas: tell the prompt lower rating is easier and to state both numbers, or sort context so comparisons are by position.
- [ ] **Named pattern that isn't retrieved gets silently swapped** — Asked about Hitchhiker; answer discusses "Hitchin' a Ride" as if it were the one named (`ask-adversarial-005`). Rule: if the user names a pattern and it isn't in context, say so first.
- [ ] **Hitchhiker only reaches rank 5 for its own name** — Retrieval returns "Hitchin' a Ride" first; real Hitchhiker isn't in the corpus. Title queries for famous patterns depend on seeding — see corpus coverage.
- [ ] **Follow-up citations reuse numbers** — Each answer renumbers `[1]`, `[2]`…, so a follow-up's `[1]` is a different pattern. Low priority; UI shows cards by name.
- [ ] **Extraction is as slow as writing the answer** — Uncached: `extract` p50/p95 1,214/2,172 ms vs answer 1,752/2,052. Ideas: skip extraction when no filter words and no history, lower `max_tokens`, or cache extraction separately.

### Eval & data

- [ ] **Automatic grounding checks catch none of the real failures** — Unsupported numbers/names were 0 for 0 against hand labels; unfaithful answers used real facts but oversold, mis-compared, or swapped. Next: LLM judge measured against the 31 hand labels.
- [ ] **Some designer names are Ravelry handles** — 186 patterns show lowercase handles (e.g. `tincanknits`) instead of display names. Search still finds them; cards look wrong. Low priority: map known handles or use profile name from the API.
- [ ] **Corpus coverage is lopsided** — Of 16,536 patterns: 1,234 vests, 412 mid-calf socks, but only 3 dishcloths, 7 bags, 4 toys, no granny-square bags. Seeding uses free-text `SEED_CATEGORIES` words, not Ravelry category filters. Log per-query yields and seed with category filters.

## Features

### UI

- [ ] **Desktop two-column layout** — On desktop only, use horizontal space with a two-column composition (e.g. search / results or main content + sidebar). Keep a single-column stack on mobile.
- [ ] **Make the UI look better**

### Product

- [ ] Add username
- [ ] Add freeform patterns in the library
- [ ] Improve search
- [ ] Connect to the user's current Ravelry account
- [ ] Public project pages
- [ ] **Stitch counter:** count every 10 stitches instead of every row

## Done

### Bugs fixed

- [x] Ask: unrated difficulty described as "very easy" (context omitted difficulty unless > 0)
- [x] Ask: extraction picked `category: Other` and retrieved junk (stop extracting category)
- [x] Ask: extraction inferred `craft: Knitting` for "cozy oversized sweater" (keep craft only if named)
- [x] Degraded results cached for full TTL (serve but don't cache; mark `fallbacks`)
- [x] Zero-result searches logged 0 ms latency (always record wall time)
- [x] `/health` said ok with DB down (ping Postgres + Redis; 503 when degraded)
- [x] Failed searches left no `search_events` record
- [x] Eval designer check didn't strip spaces

### Shipped features

- [x] **Recommendations engine** — Taste-vector recs with popularity fallback. Later: collaborative filtering, click feedback in the taste vector.
- [x] **Visual search** — Photo → similar pattern (CLIP). Later: text-to-image via CLIP, ANN on `image_embedding`.
