# Evals

Offline quality checks for text search, Ask Woolly, and visual search. Each suite is a JSONL
file of hand-written cases that runs through the same functions the API calls and prints a
scoreboard. Nothing is written to the database.

## Run

With the stack up (`docker-compose up`) and the corpus seeded:

```bash
# All suites. Ask replays recorded model responses, so no API key is needed.
docker-compose exec -e GIT_SHA=$(git rev-parse --short HEAD) backend python -m evals.run

# One suite, a search ablation, or a slice
docker-compose exec backend python -m evals.run --suite search --variant vector
docker-compose exec backend python -m evals.run --suite search --tag designer -v
docker-compose exec backend python -m evals.run --suite ask --case ask-followup-001

# Ranked results with ravelry ids, for one query
docker-compose exec backend python -m evals.label "cozy winter sweater" --craft Knitting

# Judging pool for writing relevant_ids: top 10 of every variant, sorted by id, ranks hidden
docker-compose exec backend python -m evals.label --pool --new-only

# Hold an ablation to the production floors (exits 1, proving the gate trips)
docker-compose exec backend python -m evals.run --suite search --variant vector --enforce-floors
```

`--variant` stops the search pipeline early: `vector` (pgvector only), `hybrid` (no
rerank), or `production` (hybrid + cross-encoder, the default).

## Ask: recorded responses and judgments

Ask makes two model calls per case. `--llm` picks where the replies come from:

| Mode | Behavior | Key needed |
|---|---|---|
| `replay` (default) | Answer from `fixtures/llm.jsonl` (tracked). A request that isn't recorded errors the case with "re-record" | No |
| `record` | Reuse recorded replies whose request is unchanged, call the model for the rest, and save | Yes |
| `live` | Call the model for everything, save nothing | Yes |

A recording is keyed by a hash of the model, messages, token limit, temperature, and JSON
mode. Changing a prompt, the corpus, or retrieval changes the context the model sees, so
the old reply no longer matches and the case errors instead of scoring a stale answer.

Faithfulness is judged by hand. `datasets/ask_judgments.jsonl` holds one verdict per
answer (`faithful`, `unfaithful`, or `refused`), pinned to a hash of the exact answer
text. After a re-record:

```bash
docker-compose exec backend python -m evals.run --suite ask --llm record
docker-compose exec backend python -m evals.review --unjudged   # each new answer next to its context
# add a line per answer to datasets/ask_judgments.jsonl, then:
docker-compose exec backend python -m evals.run --suite ask
```

The `judged` floor is 1.0, so the run fails until every answer has a verdict. The rubric
is in `judgments.py` and `docs/19-rag-evaluation.md`.

Each run writes `evals/results/<timestamp>-<suite>-<variant>.json` (gitignored). It holds
every case's checks and top results, plus the git sha, corpus counts, model names, pipeline
weights, and a sha256 of each dataset file.

## What counts as a regression

`thresholds.json` sets per-suite floors on summary metrics (`pass_rate`, any metric name
from the scoreboard, or `latency_p50_ms` / `latency_p95_ms` as ceilings). Floors apply to
the `production` variant, or to any variant with `--enforce-floors`. The search floors sit
just below the labeled baseline (production nDCG@10 0.888, floor 0.85). Re-baseline only on
purpose, when the dataset or corpus changes.

| Exit code | Meaning |
|---|---|
| 0 | Every floor held |
| 1 | A floor was breached; the scoreboard says which |
| 2 | The run couldn't start: bad dataset or judgments, database down, no fixture file to replay, or no API key for `--suite ask --llm record/live` |

Compare two runs only when their dataset hashes match. A changed case file means a new
baseline.

A case is **skipped**, not failed, when the corpus can't contain the answer: no pattern
named like the expected `title`, no patterns by the `designer`, no rows matching the
filters, or a missing image. Skips don't count toward the pass rate. Errors do.

## Adding a case

Add a line to `datasets/<suite>.jsonl`. Unknown keys are rejected, so a typo fails the
run instead of passing silently.

```json
{"id": "search-title-009", "suite": "search", "input": {"query": "Sophie Shawl"}, "expect": {"title": "Sophie Shawl", "title_max_rank": 1}, "tags": ["exact-title"]}
```

| Suite | `input` | `expect` keys |
|---|---|---|
| search | `query`, optional `filters` (`craft`, `category`, `difficulty`, `free`) | `relevant_ids`, `min_ndcg@10`, `terms_any`, `terms_k`, `min_term_precision`, `title`, `title_max_rank`, `designer`, `designer_min_share`, `forbid_ids`, `forbid_terms`, `forbid_k`, `min_results` |
| visual | `image` (path under `evals/`, e.g. `images/hat.jpg`) | same as search |
| ask | `message`, optional `history` | `search_query_terms`, `filters`, `filters_absent`, `filters_relaxed`, `expect_no_results`, `cites`, `answer_forbid_terms`, `retrieval` (a nested search `expect` scored on the cited patterns) |

`relevant_ids` is a list of ravelry ids, or `{"<id>": grade}` for graded nDCG:

| Grade | Meaning |
|---|---|
| 2 | Right object with the stated attributes |
| 1 | Right object missing an attribute, or a close substitute |
| 0 | Judged and not relevant: wrong object, or an attribute the query rules out |

Keep the zeros. `judged@10` is the share of the top 10 that has any grade. Unjudged rows
score as not relevant, so when a change pushes `judged@10` below about 0.9, run
`label --pool --new-only`, grade the new rows, and only then compare. Grade from the pool,
not from one variant's ranking, and leave labels alone once a baseline is frozen.

Search metrics: `ndcg@10`, `recall@10`, `mrr`, `judged@10`, `candidate_recall@20` and `@60`
(the pre-rerank pool, production only), `zero_result_rate`, `term_precision@k`,
`title_mrr`, `designer_share@10`, `filter_precision@10`.

Ask metrics: `extraction_accuracy`, `citation_validity`, `faithfulness` (judged cases),
`judged`, `auto_grounded` (no number or corpus pattern name in the answer that isn't in
the context), and `retrieval_*` for cases with a `retrieval` expectation.

Visual photos go in `evals/images/`, which is gitignored.

## Tests

The harness has unit tests that need no database: `pytest tests/test_evals.py`.
