"""Print Ask answers beside the context they were written from, for hand judging.

Reads a saved run (the newest ask run by default) and prints, per case, the
question, what extraction did, the CONTEXT block, the answer, and its
answer_sha. Write verdicts to datasets/ask_judgments.jsonl; see judgments.py
for what each verdict means.

    docker-compose exec backend python -m evals.review --unjudged
    docker-compose exec backend python -m evals.review --case ask-filter-001
"""

import argparse
import json
import sys
from pathlib import Path

from evals.cases import load_dataset
from evals.judgments import load_judgments
from evals.run import DATASETS_DIR, JUDGMENTS_PATH, RESULTS_DIR


def latest_ask_run() -> Path | None:
    runs = sorted(RESULTS_DIR.glob("*-ask-*.json")) + sorted(RESULTS_DIR.glob("*-all-*.json"))
    runs = [p for p in runs if any(r["suite"] == "ask" for r in json.loads(p.read_text())["reports"])]
    return max(runs, key=lambda p: p.name) if runs else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Show Ask answers with their context for judging.")
    parser.add_argument("run", nargs="?", type=Path, help="Results JSON (default: newest ask run)")
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--unjudged", action="store_true", help="Only answers with no judgment yet")
    args = parser.parse_args(argv)

    path = args.run or latest_ask_run()
    if path is None:
        print("no saved ask run; run python -m evals.run --suite ask first", file=sys.stderr)
        return 2
    report = next(r for r in json.loads(path.read_text())["reports"] if r["suite"] == "ask")
    judgments = load_judgments(JUDGMENTS_PATH)
    cases = {c.id: c for c in load_dataset(DATASETS_DIR / "ask.jsonl", "ask").cases}
    print(f"# {path.name}\n")

    for result in report["results"]:
        observed = result.get("observed") or {}
        if args.case and result["case_id"] not in args.case:
            continue
        sha = observed.get("answer_sha")
        judged = judgments.get((result["case_id"], sha))
        if args.unjudged and judged:
            continue
        failed = [f"{c['name']}: {c['detail']}" for c in result.get("checks", []) if not c["passed"]]
        print(f"## {result['case_id']}  [{result['status']}]  answer_sha {sha}")
        case = cases.get(result["case_id"])
        if case:
            for turn in case.input.get("history") or []:
                print(f"   ({turn['role']}) {turn['content']}")
            print(f"   ASK: {case.input['message']}")
        print(f"   judged: {judged.verdict + ' — ' + judged.note if judged else '-'}")
        if failed:
            print(f"   failing: {'; '.join(failed)}")
        print(f"   extraction: {observed.get('search_query')!r} {observed.get('filters')}  relaxed={observed.get('filters_relaxed')}")
        print("   CONTEXT:")
        for line in (observed.get("context") or "(none)").splitlines():
            print(f"      {line}")
        print("   ANSWER:")
        for line in (observed.get("answer") or result.get("detail") or "").splitlines():
            print(f"      {line}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
