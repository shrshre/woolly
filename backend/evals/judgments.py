"""Hand judgments of Ask answers: is the prose supported by its context block?

One line per judged answer in ``datasets/ask_judgments.jsonl``:

    {"case": "ask-filter-001", "answer_sha": "3f9c0a1b2d4e",
     "verdict": "unfaithful", "note": "calls unrated difficulty 0/10 very easy"}

A judgment is pinned to the exact answer text by ``answer_sha``, so re-recording
an answer leaves it unjudged instead of silently inheriting the old verdict.

Verdicts:
    faithful    every claim is in the context, and weak matches are called weak
    unfaithful  any claim the context doesn't support, an invented pattern or
                number, a weak match oversold, or a relaxed filter presented as held
    refused     declined an out-of-scope request (instructions, invented items)
                correctly; counts as faithful
"""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from evals.cases import DatasetError

VERDICTS = ("faithful", "unfaithful", "refused")
SHA_CHARS = 12


def answer_sha(answer: str) -> str:
    return hashlib.sha256(answer.strip().encode("utf-8")).hexdigest()[:SHA_CHARS]


@dataclass(frozen=True)
class Judgment:
    case: str
    answer_sha: str
    verdict: str
    note: str = ""

    @property
    def faithful(self) -> bool:
        return self.verdict != "unfaithful"


def load_judgments(path: Path) -> dict[tuple[str, str], Judgment]:
    if not path.exists():
        return {}
    judgments: dict[tuple[str, str], Judgment] = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip() or line.strip().startswith("//"):
            continue
        where = f"{path.name}:{number}"
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise DatasetError(f"{where}: invalid JSON ({exc.msg})") from exc
        unknown = set(raw) - {"case", "answer_sha", "verdict", "note"}
        if unknown:
            raise DatasetError(f"{where}: unknown keys {sorted(unknown)}")
        if raw.get("verdict") not in VERDICTS:
            raise DatasetError(f"{where}: verdict must be one of {VERDICTS}")
        if not (isinstance(raw.get("case"), str) and isinstance(raw.get("answer_sha"), str)):
            raise DatasetError(f"{where}: case and answer_sha are required")
        key = (raw["case"], raw["answer_sha"])
        if key in judgments:
            raise DatasetError(f"{where}: duplicate judgment for {key}")
        judgments[key] = Judgment(raw["case"], raw["answer_sha"], raw["verdict"], raw.get("note", ""))
    return judgments
