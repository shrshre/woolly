"""Turn one case plus what the pipeline returned into checks and metrics.

A case passes when every check passes. Metrics are numbers averaged across
the suite; a case only contributes to the metrics its expectations define.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from app.search.filters import DIFFICULTY_RANGES
from evals import metrics
from evals.cases import EvalCase

RANK_CUTOFF = 10
DEFAULT_TERMS_K = 5
DEFAULT_MIN_TERM_PRECISION = 0.6
DEFAULT_TITLE_MAX_RANK = 3
DEFAULT_DESIGNER_MIN_SHARE = 0.5


@dataclass
class Check:
    name: str
    passed: bool
    detail: str = ""


CANDIDATE_CUTOFFS = (20, 60)


def strip_spaces(value: str) -> str:
    """Lowercase with whitespace removed, as the designer search leg compares."""
    return "".join(value.lower().split())


def _judgments(relevant: list[int] | dict[str, float]) -> dict[int, float]:
    """Every judged id with its grade. Grade 0 means judged and not relevant."""
    if isinstance(relevant, list):
        return {rid: 1.0 for rid in relevant}
    return {int(rid): float(grade) for rid, grade in relevant.items()}


def _result_text(result: dict[str, Any]) -> str:
    parts = [result.get("name"), result.get("description"), result.get("category")]
    parts.extend(result.get("tags") or [])
    return " ".join(str(p) for p in parts if p)


def _difficulty(result: dict[str, Any]) -> float | None:
    try:
        value = float(result.get("difficulty"))
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def satisfies_filters(result: dict[str, Any], filters: dict[str, Any]) -> bool:
    """Mirror of build_filter_clause, applied to one returned row."""
    for key in ("craft", "category"):
        if key in filters and (result.get(key) or "").lower() != filters[key].lower():
            return False
    if "free" in filters and result.get("free") is not filters["free"]:
        return False
    if "difficulty" in filters:
        low, high = DIFFICULTY_RANGES[filters["difficulty"]]
        value = _difficulty(result)
        if value is None or not low <= value < high:
            return False
    return True


def score_ranked(
    case: EvalCase,
    results: list[dict[str, Any]],
    *,
    candidate_ids: list[int] | None = None,
) -> tuple[list[Check], dict[str, float]]:
    """Checks for search and visual cases. ``results`` are enriched result rows.

    ``candidate_ids`` is the stage-1 pool before reranking, when the target
    exposes it, so recall the reranker never had a chance at shows up apart
    from recall it lost.
    """
    expect = case.expect
    top = results[:RANK_CUTOFF]
    ids = [r.get("id") for r in results]
    checks: list[Check] = []
    scores: dict[str, float] = {"zero_result_rate": 0.0 if results else 1.0}

    min_results = expect.get("min_results", 1)
    checks.append(
        Check("min_results", len(results) >= min_results, f"{len(results)} returned, need {min_results}")
    )

    if "relevant_ids" in expect:
        judged = _judgments(expect["relevant_ids"])
        grades = {rid: grade for rid, grade in judged.items() if grade > 0}
        ndcg = metrics.ndcg_at_k(ids, grades, RANK_CUTOFF)
        recall = metrics.recall_at_k(ids, grades, RANK_CUTOFF)
        scores["ndcg@10"] = ndcg
        scores["recall@10"] = recall
        scores["mrr"] = metrics.reciprocal_rank([rid in grades for rid in ids])
        # Share of the top 10 that has any judgment. Unjudged rows score as
        # not relevant, so a falling value means the labels need a new pool.
        scores["judged@10"] = (
            sum(1 for rid in ids[:RANK_CUTOFF] if rid in judged) / len(top) if top else 1.0
        )
        if candidate_ids is not None:
            for cutoff in CANDIDATE_CUTOFFS:
                scores[f"candidate_recall@{cutoff}"] = metrics.recall_at_k(candidate_ids, grades, cutoff)
        floor = expect.get("min_ndcg@10")
        if floor is not None:
            checks.append(Check("ndcg@10", ndcg >= floor, f"{ndcg:.3f} vs floor {floor}"))
        else:
            checks.append(Check("relevant_in_top10", recall > 0, f"recall@10 {recall:.2f}"))

    if "terms_any" in expect:
        k = expect.get("terms_k", DEFAULT_TERMS_K)
        floor = expect.get("min_term_precision", DEFAULT_MIN_TERM_PRECISION)
        flags = [metrics.contains_any(_result_text(r), expect["terms_any"]) for r in results]
        precision = metrics.precision_at_k(flags, k)
        scores[f"term_precision@{k}"] = precision
        checks.append(Check("terms_any", precision >= floor, f"{precision:.2f} of top {k}, need {floor}"))

    if "title" in expect:
        max_rank = expect.get("title_max_rank", DEFAULT_TITLE_MAX_RANK)
        flags = [metrics.contains_any(r.get("name") or "", [expect["title"]]) for r in results]
        rank = metrics.first_rank(flags)
        scores["title_mrr"] = metrics.reciprocal_rank(flags)
        checks.append(
            Check("title", rank is not None and rank <= max_rank, f"rank {rank or '-'}, need <= {max_rank}")
        )

    if "designer" in expect:
        floor = expect.get("designer_min_share", DEFAULT_DESIGNER_MIN_SHARE)
        wanted = strip_spaces(expect["designer"])
        flags = [wanted in strip_spaces(r.get("designer") or "") for r in top]
        share = metrics.precision_at_k(flags, RANK_CUTOFF)
        scores["designer_share@10"] = share
        checks.append(Check("designer", share >= floor, f"{share:.2f} of top 10, need {floor}"))

    forbid_k = expect.get("forbid_k", RANK_CUTOFF)
    if "forbid_ids" in expect:
        hits = [rid for rid in ids[:forbid_k] if rid in set(expect["forbid_ids"])]
        checks.append(Check("forbid_ids", not hits, f"found {hits} in top {forbid_k}" if hits else ""))
    if "forbid_terms" in expect:
        hits = [
            r.get("name") for r in results[:forbid_k]
            if metrics.contains_any(r.get("name") or "", expect["forbid_terms"])
        ]
        checks.append(Check("forbid_terms", not hits, f"found {hits} in top {forbid_k}" if hits else ""))

    if case.filters:
        flags = [satisfies_filters(r, case.filters) for r in top]
        share = sum(flags) / len(flags) if flags else 1.0
        scores["filter_precision@10"] = share
        checks.append(Check("filters_hold", all(flags), f"{sum(flags)}/{len(flags)} match {case.filters}"))

    return checks, scores


def _norm(value: Any) -> Any:
    return value.lower() if isinstance(value, str) else value


_CITATION = re.compile(r"\[\d+(?:\s*,\s*\d+)*\]")
_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def _numbers(text: str) -> set[float]:
    return {float(n) for n in _NUMBER.findall(text)}


def unsupported_numbers(answer: str, sources: str) -> list[str]:
    """Numbers in the answer (citations aside) that appear nowhere in the
    sources. Yardage, prices, sizes, and ratings are the facts a model invents
    most fluently, and every real one is in the context block as digits."""
    allowed = _numbers(sources)
    found = _NUMBER.findall(_CITATION.sub("", answer))
    return sorted({n for n in found if float(n) not in allowed}, key=float)


def ungrounded_names(answer: str, sources: str, known_names: Iterable[str]) -> list[str]:
    """Corpus pattern or designer names the answer uses that the sources don't
    contain: a real pattern, just not one that was retrieved. Case-sensitive,
    because these are proper nouns and prose like "a baby blanket" isn't a claim."""
    lowered = sources.lower()
    hits = []
    for name in known_names:
        if name in answer and name.lower() not in lowered and re.search(rf"(?<!\w){re.escape(name)}(?!\w)", answer):
            hits.append(name)
    return sorted(set(hits))


def score_ask(
    case: EvalCase,
    outcome: dict[str, Any],
    *,
    known_names: Iterable[str] = (),
    judgment: Any = None,
) -> tuple[list[Check], dict[str, float]]:
    """Checks for one Ask answer, one group per stage so a bad answer has a cause.

    ``outcome`` has answer, patterns, search_query, filters, filters_relaxed,
    and context (the exact block the model saw). ``known_names`` are corpus
    pattern and designer names for the grounding check. ``judgment`` is the
    hand verdict for this exact answer text, if one exists.
    """
    expect = case.expect
    answer = outcome.get("answer") or ""
    patterns = outcome.get("patterns") or []
    cited = metrics.citations(answer)
    checks: list[Check] = []
    scores: dict[str, float] = {}

    out_of_range = sorted({n for n in cited if not 1 <= n <= len(patterns)})
    checks.append(
        Check(
            "citations_valid",
            not out_of_range,
            f"cited {out_of_range} with {len(patterns)} patterns" if out_of_range else "",
        )
    )
    scores["citation_validity"] = 0.0 if out_of_range else 1.0
    scores["cited_patterns"] = float(len(set(cited)))

    if expect.get("expect_no_results"):
        checks.append(Check("no_results", not patterns, f"{len(patterns)} patterns returned"))
    elif patterns and expect.get("cites", True):
        checks.append(Check("cites_something", bool(cited), "answer has no [n] citation" if not cited else ""))

    extraction: list[Check] = []
    query = outcome.get("search_query") or ""
    if "search_query_terms" in expect:
        missing = [t for t in expect["search_query_terms"] if not metrics.contains_any(query, [t])]
        extraction.append(Check("search_query_terms", not missing, f"{query!r} lacks {missing}" if missing else ""))
    filters = outcome.get("filters") or {}
    if "filters" in expect:
        wrong = {
            key: filters.get(key)
            for key, value in expect["filters"].items()
            if _norm(filters.get(key)) != _norm(value)
        }
        extraction.append(Check("filters", not wrong, f"got {filters}, want {expect['filters']}" if wrong else ""))
    if "filters_absent" in expect:
        present = [key for key in expect["filters_absent"] if key in filters]
        extraction.append(Check("filters_absent", not present, f"unexpected {present}" if present else ""))
    if extraction:
        scores["extraction_accuracy"] = 1.0 if all(c.passed for c in extraction) else 0.0
        checks.extend(extraction)

    if "filters_relaxed" in expect:
        relaxed = bool(outcome.get("filters_relaxed"))
        checks.append(Check("filters_relaxed", relaxed is expect["filters_relaxed"], f"got {relaxed}"))

    if "answer_forbid_terms" in expect:
        lowered = answer.lower()
        hits = [t for t in expect["answer_forbid_terms"] if t.lower() in lowered]
        checks.append(Check("answer_forbid_terms", not hits, f"answer contains {hits}" if hits else ""))

    if "retrieval" in expect:
        sub = EvalCase(id=case.id, suite="search", input={"query": outcome.get("search_query") or ""}, expect=expect["retrieval"])
        sub_checks, sub_scores = score_ranked(sub, patterns)
        checks.extend(Check(f"retrieval_{c.name}", c.passed, c.detail) for c in sub_checks)
        scores.update({f"retrieval_{k}": v for k, v in sub_scores.items() if k != "zero_result_rate"})

    if patterns and "context" in outcome:
        history = " ".join(turn.get("content", "") for turn in case.input.get("history") or [])
        sources = f"{outcome['context']}\n{case.input['message']}\n{history}"
        numbers = unsupported_numbers(answer, sources)
        names = ungrounded_names(answer, sources, known_names)
        checks.append(Check("numbers_grounded", not numbers, f"not in context: {numbers}" if numbers else ""))
        checks.append(Check("names_grounded", not names, f"not in context: {names}" if names else ""))
        scores["auto_grounded"] = 0.0 if numbers or names else 1.0

    scores["judged"] = 1.0 if judgment is not None else 0.0
    if judgment is not None:
        scores["faithfulness"] = 1.0 if judgment.faithful else 0.0
        checks.append(Check("faithful", judgment.faithful, f"{judgment.verdict}: {judgment.note}" if not judgment.faithful else ""))

    return checks, scores
