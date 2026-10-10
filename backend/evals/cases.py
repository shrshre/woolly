"""Eval case schema and the JSONL loader.

One case per line:

    {"id": "search-intent-001", "suite": "search",
     "input": {"query": "cozy winter sweater"},
     "expect": {"terms_any": ["sweater", "pullover"]},
     "tags": ["intent"], "notes": "optional free text"}

The loader rejects unknown keys instead of ignoring them, so a typo in an
expectation fails loudly rather than silently passing every run.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.search.filters import DIFFICULTY_RANGES

SUITES = ("search", "ask", "visual")

FILTER_KEYS = {"craft", "difficulty", "free", "category"}

# Expectations shared by every suite that returns a ranked pattern list.
_RANKED_EXPECT = {
    "relevant_ids",
    "min_ndcg@10",
    "terms_any",
    "terms_k",
    "min_term_precision",
    "title",
    "title_max_rank",
    "designer",
    "designer_min_share",
    "forbid_ids",
    "forbid_terms",
    "forbid_k",
    "min_results",
}

EXPECT_KEYS: dict[str, set[str]] = {
    "search": _RANKED_EXPECT,
    "visual": _RANKED_EXPECT,
    "ask": {
        "search_query_terms",
        "filters",
        "filters_absent",
        "filters_relaxed",
        "expect_no_results",
        "cites",
        "answer_forbid_terms",
        # Ranked expectations on the cited patterns, scored like a search case.
        "retrieval",
    },
}

INPUT_KEYS: dict[str, tuple[set[str], set[str]]] = {
    # suite: (required, optional)
    "search": ({"query"}, {"filters"}),
    "visual": ({"image"}, set()),
    "ask": ({"message"}, {"history"}),
}

CASE_KEYS = {"id", "suite", "input", "expect", "tags", "notes"}


class DatasetError(ValueError):
    """A dataset file is malformed. The message names the file and line."""


@dataclass(frozen=True)
class EvalCase:
    id: str
    suite: str
    input: dict[str, Any]
    expect: dict[str, Any]
    tags: tuple[str, ...] = ()
    notes: str = ""
    line: int = 0

    @property
    def filters(self) -> dict[str, Any]:
        return dict(self.input.get("filters") or {})


@dataclass
class Dataset:
    path: Path
    suite: str
    cases: list[EvalCase] = field(default_factory=list)


def _validate_filters(filters: Any, where: str) -> None:
    if not isinstance(filters, dict):
        raise DatasetError(f"{where}: filters must be an object")
    unknown = set(filters) - FILTER_KEYS
    if unknown:
        raise DatasetError(f"{where}: unknown filter keys {sorted(unknown)}")
    if "difficulty" in filters and filters["difficulty"] not in DIFFICULTY_RANGES:
        raise DatasetError(f"{where}: difficulty must be one of {sorted(DIFFICULTY_RANGES)}")
    if "free" in filters and not isinstance(filters["free"], bool):
        raise DatasetError(f"{where}: free must be true or false")
    for key in ("craft", "category"):
        if key in filters and not (isinstance(filters[key], str) and filters[key].strip()):
            raise DatasetError(f"{where}: {key} must be a non-empty string")


def _validate_relevant_ids(value: Any, where: str) -> None:
    if isinstance(value, list):
        if not value or not all(isinstance(v, int) for v in value):
            raise DatasetError(f"{where}: relevant_ids must be a non-empty list of ravelry ids")
        return
    if isinstance(value, dict):
        for key, grade in value.items():
            if not str(key).isdigit() or isinstance(grade, bool) or not isinstance(grade, (int, float)) or grade < 0:
                raise DatasetError(f"{where}: relevant_ids maps ravelry id -> grade (0 = judged not relevant)")
        if not any(grade > 0 for grade in value.values()):
            raise DatasetError(f"{where}: relevant_ids needs at least one id with grade > 0")
        return
    raise DatasetError(f"{where}: relevant_ids must be a list or an id->grade object")


def _validate_terms(expect: dict[str, Any], where: str) -> None:
    for key in ("terms_any", "forbid_terms", "search_query_terms", "answer_forbid_terms"):
        if key in expect and not (
            isinstance(expect[key], list)
            and expect[key]
            and all(isinstance(t, str) and t.strip() for t in expect[key])
        ):
            raise DatasetError(f"{where}: {key} must be a non-empty list of strings")


def _validate_history(history: Any, where: str) -> None:
    if not isinstance(history, list):
        raise DatasetError(f"{where}: history must be a list of turns")
    for turn in history:
        if not (
            isinstance(turn, dict)
            and turn.get("role") in ("user", "assistant")
            and isinstance(turn.get("content"), str)
            and turn["content"].strip()
        ):
            raise DatasetError(f"{where}: each history turn needs role user/assistant and content")


def parse_case(raw: Any, *, suite: str, where: str, line: int = 0) -> EvalCase:
    if not isinstance(raw, dict):
        raise DatasetError(f"{where}: each line must be a JSON object")
    unknown = set(raw) - CASE_KEYS
    if unknown:
        raise DatasetError(f"{where}: unknown keys {sorted(unknown)}")

    case_id = raw.get("id")
    if not isinstance(case_id, str) or not case_id.strip():
        raise DatasetError(f"{where}: id is required")
    where = f"{where} ({case_id})"

    if raw.get("suite") != suite:
        raise DatasetError(f"{where}: suite must be {suite!r} in this file")

    case_input = raw.get("input")
    if not isinstance(case_input, dict):
        raise DatasetError(f"{where}: input must be an object")
    required, optional = INPUT_KEYS[suite]
    missing = required - set(case_input)
    if missing:
        raise DatasetError(f"{where}: input is missing {sorted(missing)}")
    unknown = set(case_input) - required - optional
    if unknown:
        raise DatasetError(f"{where}: unknown input keys {sorted(unknown)}")
    for key in required:
        if not (isinstance(case_input[key], str) and case_input[key].strip()):
            raise DatasetError(f"{where}: input.{key} must be a non-empty string")
    if "filters" in case_input:
        _validate_filters(case_input["filters"], where)
    if "history" in case_input:
        _validate_history(case_input["history"], where)

    expect = raw.get("expect", {})
    if not isinstance(expect, dict):
        raise DatasetError(f"{where}: expect must be an object")
    unknown = set(expect) - EXPECT_KEYS[suite]
    if unknown:
        raise DatasetError(f"{where}: unknown expect keys {sorted(unknown)}")
    if suite != "ask" and not expect:
        raise DatasetError(f"{where}: expect needs at least one signal")
    if "retrieval" in expect:
        nested = expect["retrieval"]
        if not isinstance(nested, dict) or not nested:
            raise DatasetError(f"{where}: retrieval must be a non-empty object of ranked expectations")
        unknown = set(nested) - _RANKED_EXPECT
        if unknown:
            raise DatasetError(f"{where}: unknown retrieval keys {sorted(unknown)}")
        _validate_terms(nested, where)
    if "relevant_ids" in expect:
        _validate_relevant_ids(expect["relevant_ids"], where)
    _validate_terms(expect, where)
    if "filters" in expect:
        _validate_filters(expect["filters"], where)
    if "filters_absent" in expect and not (
        isinstance(expect["filters_absent"], list) and set(expect["filters_absent"]) <= FILTER_KEYS
    ):
        raise DatasetError(f"{where}: filters_absent must list filter keys")

    tags = raw.get("tags", [])
    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
        raise DatasetError(f"{where}: tags must be a list of strings")
    notes = raw.get("notes", "")
    if not isinstance(notes, str):
        raise DatasetError(f"{where}: notes must be a string")

    return EvalCase(
        id=case_id.strip(),
        suite=suite,
        input=case_input,
        expect=expect,
        tags=tuple(tags),
        notes=notes,
        line=line,
    )


def load_dataset(path: Path, suite: str) -> Dataset:
    """Parse a JSONL file. Blank lines and lines starting with ``//`` are skipped."""
    if suite not in SUITES:
        raise DatasetError(f"unknown suite {suite!r}")
    if not path.exists():
        raise DatasetError(f"{path}: dataset not found")

    dataset = Dataset(path=path, suite=suite)
    seen: set[str] = set()
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("//"):
            continue
        where = f"{path.name}:{number}"
        try:
            raw = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise DatasetError(f"{where}: invalid JSON ({exc.msg})") from exc
        case = parse_case(raw, suite=suite, where=where, line=number)
        if case.id in seen:
            raise DatasetError(f"{where}: duplicate id {case.id!r}")
        seen.add(case.id)
        dataset.cases.append(case)
    return dataset
