"""Adapters from an eval case to the production code path it exercises.

Each target calls the same function the API route calls, so a passing eval
says something about what users get. Nothing here writes to the database:
every case runs inside a transaction that is rolled back afterwards.
"""

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.db.models import Pattern
from app.search.filters import build_filter_clause
from evals.cases import EvalCase
from evals.scoring import Check, score_ask, score_ranked, strip_spaces

EVALS_DIR = Path(__file__).resolve().parent
RANKED_LIMIT = 50
VISUAL_LIMIT = 10

SEARCH_VARIANTS = ("production", "hybrid", "vector")


@dataclass
class Observation:
    latency_ms: int
    results: list[dict[str, Any]] = field(default_factory=list)
    outcome: dict[str, Any] = field(default_factory=dict)
    # Stage-1 pool before reranking, production search only.
    candidate_ids: list[int] | None = None


def enrich(db: Session, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add craft, category, and tags to result rows, which carry only card fields."""
    ids = [r["id"] for r in results if r.get("id") is not None]
    if not ids:
        return results
    rows = (
        db.query(Pattern.ravelry_id, Pattern.craft, Pattern.category, Pattern.tags)
        .filter(Pattern.ravelry_id.in_(ids))
        .all()
    )
    facts = {rid: {"craft": craft, "category": category, "tags": tags or []} for rid, craft, category, tags in rows}
    return [{**r, **facts.get(r.get("id"), {})} for r in results]


def summarize_results(results: list[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    return [
        {
            "id": r.get("id"),
            "name": r.get("name"),
            "designer": r.get("designer"),
            **({"rerank_score": r["rerank_score"]} if "rerank_score" in r else {}),
        }
        for r in results[:limit]
    ]


class SearchTarget:
    """Text search. ``variant`` picks the stage the eval stops at:

    production: hybrid retrieval + cross-encoder (what the search bar serves)
    hybrid:     hybrid retrieval only, no rerank
    vector:     pgvector cosine similarity only
    """

    suite = "search"

    def __init__(self, db: Session, variant: str = "production"):
        if variant not in SEARCH_VARIANTS:
            raise ValueError(f"unknown search variant {variant!r}")
        self.db = db
        self.variant = variant

    def warm_up(self) -> None:
        from app.services import embedding_service, reranking_service

        embedding_service.get_model()
        if self.variant == "production":
            reranking_service.get_reranker()

    def skip_reason(self, case: EvalCase) -> str | None:
        """Skip, rather than fail, when the corpus cannot contain the answer."""
        if case.filters:
            clause, params = build_filter_clause(**case.filters)
            count = self.db.execute(
                text(f"SELECT COUNT(*) FROM patterns WHERE embedding IS NOT NULL {clause}"), params
            ).scalar()
            if not count:
                return f"no embedded patterns match filters {case.filters}"
        if "title" in case.expect and not self._exists(Pattern.name, case.expect["title"]):
            return f"no pattern named like {case.expect['title']!r} in the corpus"
        if "designer" in case.expect and not self._designer_exists(case.expect["designer"]):
            return f"no patterns by {case.expect['designer']!r} in the corpus"
        return None

    def _exists(self, column, value: str) -> bool:
        return bool(
            self.db.query(func.count(Pattern.id))
            .filter(Pattern.embedding.isnot(None), column.ilike(f"%{value}%"))
            .scalar()
        )

    def _designer_exists(self, designer: str) -> bool:
        stripped = func.replace(func.lower(Pattern.designer), " ", "")
        return bool(
            self.db.query(func.count(Pattern.id))
            .filter(Pattern.embedding.isnot(None), stripped.like(f"%{strip_spaces(designer)}%"))
            .scalar()
        )

    def run(self, case: EvalCase) -> Observation:
        from app.search.hybrid_search import hybrid_search
        from app.search.pipeline import search
        from app.search.semantic_search import semantic_search

        query = case.input["query"]
        candidate_ids = None
        started = time.perf_counter()
        if self.variant == "production":
            envelope = search(self.db, query, include_candidates=True, **case.filters)
            results, candidate_ids = envelope["results"], envelope["candidate_ids"]
        elif self.variant == "hybrid":
            results, _ = hybrid_search(self.db, query, limit=RANKED_LIMIT, **case.filters)
        else:
            results = semantic_search(self.db, query, RANKED_LIMIT, **case.filters)
        latency_ms = int((time.perf_counter() - started) * 1000)
        return Observation(latency_ms=latency_ms, results=enrich(self.db, results), candidate_ids=candidate_ids)

    def score(self, case: EvalCase, observation: Observation) -> tuple[list[Check], dict[str, float]]:
        return score_ranked(case, observation.results, candidate_ids=observation.candidate_ids)

    def summarize(self, observation: Observation) -> dict[str, Any]:
        return {"top": summarize_results(observation.results)}


class VisualTarget:
    """CLIP image-to-image search over pattern photos."""

    suite = "visual"
    variant = "production"

    def __init__(self, db: Session):
        self.db = db
        self._embedded: int | None = None

    def warm_up(self) -> None:
        from app.services import clip_service

        clip_service.get_clip_model()

    def _image_path(self, case: EvalCase) -> Path:
        path = Path(case.input["image"])
        return path if path.is_absolute() else EVALS_DIR / path

    def skip_reason(self, case: EvalCase) -> str | None:
        if not self._image_path(case).exists():
            return f"image {case.input['image']!r} not found"
        if self._embedded is None:
            self._embedded = (
                self.db.query(func.count(Pattern.id)).filter(Pattern.image_embedding.isnot(None)).scalar()
            )
        if not self._embedded:
            return "no image embeddings; run scripts/embed_images.py"
        return None

    def run(self, case: EvalCase) -> Observation:
        from app.search.visual_search import nearest_patterns
        from app.services import clip_service

        data = self._image_path(case).read_bytes()
        started = time.perf_counter()
        vector = clip_service.embed_image_bytes(data)
        rows = nearest_patterns(self.db, vector, VISUAL_LIMIT)
        latency_ms = int((time.perf_counter() - started) * 1000)
        results = [
            {
                "id": row["ravelry_id"],
                "name": row["name"],
                "designer": row["designer"],
                "description": row["description"],
                "difficulty": row["difficulty"],
                "free": row["is_free"],
                "similarity_score": round(float(row["similarity"]), 4),
            }
            for row in rows
        ]
        return Observation(latency_ms=latency_ms, results=enrich(self.db, results))

    def score(self, case: EvalCase, observation: Observation) -> tuple[list[Check], dict[str, float]]:
        return score_ranked(case, observation.results)

    def summarize(self, observation: Observation) -> dict[str, Any]:
        return {"top": summarize_results(observation.results)}


class AskTarget:
    """Ask Woolly end to end: extraction, retrieval, and the cited answer.

    Model calls go through ``recorder`` when one is given (see llm_fixtures), so
    a replayed run needs no API key and returns the same answers every time.
    """

    suite = "ask"
    variant = "production"

    def __init__(self, db: Session, recorder: Any = None, judgments: dict | None = None):
        self.db = db
        self.recorder = recorder
        self.judgments = judgments or {}
        self._known_names: list[str] | None = None

    def warm_up(self) -> None:
        from app.services import embedding_service, reranking_service

        embedding_service.get_model()
        reranking_service.get_reranker()

    def known_names(self) -> list[str]:
        """Corpus names specific enough to count as a claim: designers of 2+
        words and pattern names of 3+ words."""
        if self._known_names is None:
            designers = [d for (d,) in self.db.query(Pattern.designer).distinct() if d and len(d.split()) >= 2]
            names = [n for (n,) in self.db.query(Pattern.name).distinct() if n and len(n.split()) >= 3]
            self._known_names = sorted(set(designers) | set(names))
        return self._known_names

    def skip_reason(self, case: EvalCase) -> str | None:
        return None

    async def run(self, case: EvalCase) -> Observation:
        from app.search import conversational

        if self.recorder is not None:
            self.recorder.start_case(case.id)
        started = time.perf_counter()
        outcome = await conversational.ask(self.db, case.input["message"], case.input.get("history") or [])
        latency_ms = int((time.perf_counter() - started) * 1000)
        return Observation(
            latency_ms=latency_ms,
            outcome={
                "answer": outcome.answer,
                "patterns": enrich(self.db, outcome.patterns),
                "search_query": outcome.search_query,
                "filters": outcome.filters,
                "filters_relaxed": outcome.filters_relaxed,
                "context": outcome.context,
            },
        )

    def score(self, case: EvalCase, observation: Observation) -> tuple[list[Check], dict[str, float]]:
        from evals.judgments import answer_sha

        judgment = self.judgments.get((case.id, answer_sha(observation.outcome.get("answer") or "")))
        return score_ask(case, observation.outcome, known_names=self.known_names(), judgment=judgment)

    def summarize(self, observation: Observation) -> dict[str, Any]:
        from evals.judgments import answer_sha

        outcome = observation.outcome
        return {
            "search_query": outcome.get("search_query"),
            "filters": outcome.get("filters"),
            "filters_relaxed": outcome.get("filters_relaxed"),
            "answer": outcome.get("answer"),
            "answer_sha": answer_sha(outcome.get("answer") or ""),
            "patterns": summarize_results(outcome.get("patterns") or []),
            "context": outcome.get("context"),
        }
