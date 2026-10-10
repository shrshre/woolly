"""Pure ranking and text metrics. No database, no models."""

import math
import re
from collections.abc import Iterable, Sequence

CITATION_RE = re.compile(r"\[(\d+)\]")


def dcg_at_k(gains: Sequence[float], k: int) -> float:
    return sum(gain / math.log2(rank + 1) for rank, gain in enumerate(gains[:k], start=1))


def ndcg_at_k(ranked_ids: Sequence[int], grades: dict[int, float], k: int = 10) -> float:
    """Normalized DCG with graded relevance. 0.0 when nothing is relevant."""
    ideal = dcg_at_k(sorted(grades.values(), reverse=True), k)
    if ideal == 0:
        return 0.0
    gains = [grades.get(rid, 0.0) for rid in ranked_ids]
    return dcg_at_k(gains, k) / ideal


def recall_at_k(ranked_ids: Sequence[int], relevant: Iterable[int], k: int = 10) -> float:
    relevant = set(relevant)
    if not relevant:
        return 0.0
    return len(relevant & set(ranked_ids[:k])) / len(relevant)


def reciprocal_rank(flags: Sequence[bool]) -> float:
    """1/rank of the first True, 0.0 when there is none."""
    rank = first_rank(flags)
    return 1.0 / rank if rank else 0.0


def first_rank(flags: Sequence[bool]) -> int | None:
    for rank, flag in enumerate(flags, start=1):
        if flag:
            return rank
    return None


def precision_at_k(flags: Sequence[bool], k: int) -> float:
    """Share of the first k slots that are True. Missing slots count as misses."""
    if k <= 0:
        return 0.0
    return sum(1 for flag in flags[:k] if flag) / k


def percentile(values: Sequence[float], q: float) -> float | None:
    """Nearest-rank percentile, q in [0, 100]."""
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(q / 100 * len(ordered)) - 1)
    return ordered[index]


def term_pattern(term: str) -> re.Pattern[str]:
    """Match ``term`` at a word start, so "hat" hits "hats" but not "that"."""
    return re.compile(r"\b" + re.escape(term.strip().lower()))


def contains_any(text: str, terms: Iterable[str]) -> bool:
    lowered = text.lower()
    return any(term_pattern(term).search(lowered) for term in terms)


def citations(answer: str) -> list[int]:
    """Every ``[n]`` in the answer, in order of appearance."""
    return [int(n) for n in CITATION_RE.findall(answer or "")]
