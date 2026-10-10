"""Run the eval suites and print a scoreboard.

Usage (inside the backend container):
    docker-compose exec -e GIT_SHA=$(git rev-parse --short HEAD) backend python -m evals.run
    docker-compose exec backend python -m evals.run --suite search --variant vector
    docker-compose exec backend python -m evals.run --suite ask --tag follow-up -v
    docker-compose exec backend python -m evals.run --suite ask --llm record

The ask suite replays recorded completions by default, so it needs no API key.
After --llm record, judge the new answers (python -m evals.review --unjudged);
the ``judged`` floor fails until every answer has a verdict.

Exit codes: 0 all floors held, 1 a floor was breached, 2 the run could not start
(bad dataset or judgments, no fixture file to replay, or no API key for
--llm record/live on an explicitly requested suite).
"""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError

from evals.cases import SUITES, DatasetError, load_dataset
from evals.judgments import load_judgments
from evals.llm_fixtures import LLM_MODES, CompletionRecorder
from evals.runner import SuiteReport, check_floors, render, run_cases, summarize
from evals.targets import EVALS_DIR, SEARCH_VARIANTS, AskTarget, SearchTarget, VisualTarget

DATASETS_DIR = EVALS_DIR / "datasets"
RESULTS_DIR = EVALS_DIR / "results"
THRESHOLDS_PATH = EVALS_DIR / "thresholds.json"
FIXTURES_PATH = EVALS_DIR / "fixtures" / "llm.jsonl"
JUDGMENTS_PATH = DATASETS_DIR / "ask_judgments.jsonl"

EXIT_OK, EXIT_BREACH, EXIT_UNUSABLE = 0, 1, 2

logger = logging.getLogger("evals")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Woolly's offline evals.")
    parser.add_argument("--suite", choices=[*SUITES, "all"], default="all")
    parser.add_argument(
        "--variant",
        choices=SEARCH_VARIANTS,
        default="production",
        help="Search stage to stop at (search suite only). Floors apply to production only.",
    )
    parser.add_argument("--dataset", type=Path, help="Override the JSONL file (single suite only)")
    parser.add_argument("--tag", action="append", default=[], help="Only cases with this tag (repeatable)")
    parser.add_argument("--case", action="append", default=[], help="Only this case id (repeatable)")
    parser.add_argument("--thresholds", type=Path, default=THRESHOLDS_PATH)
    parser.add_argument(
        "--llm",
        choices=LLM_MODES,
        default="replay",
        help="Ask suite: replay recorded completions (no key needed), record new ones, or call the model live",
    )
    parser.add_argument(
        "--enforce-floors",
        action="store_true",
        help="Hold a non-production variant to the production floors, to check a regression is caught",
    )
    parser.add_argument("--no-save", action="store_true", help="Do not write a results JSON file")
    parser.add_argument("-v", "--verbose", action="store_true", help="List passing cases and app logs")
    args = parser.parse_args(argv)
    if args.dataset and args.suite == "all":
        parser.error("--dataset needs a single --suite")
    if args.variant != "production" and args.suite not in ("search", "all"):
        parser.error("--variant only applies to the search suite")
    return args


def load_floors(path: Path) -> dict[str, dict[str, float]]:
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {suite: {k: v for k, v in floors.items() if v is not None} for suite, floors in raw.items() if suite in SUITES}


def select(cases, tags: list[str], ids: list[str]):
    if tags:
        cases = [c for c in cases if set(tags) & set(c.tags)]
    if ids:
        cases = [c for c in cases if c.id in ids]
    return cases


def make_target(suite: str, db, variant: str, recorder=None, judgments=None):
    if suite == "search":
        return SearchTarget(db, variant)
    if suite == "visual":
        return VisualTarget(db)
    return AskTarget(db, recorder, judgments)


def ask_unavailable(mode: str, key_configured: bool, fixtures: Path) -> str | None:
    """Why the ask suite can't run in this mode, or None if it can."""
    if mode == "replay" and not fixtures.exists():
        return f"no recorded completions at {fixtures.name}; run once with --llm record"
    if mode != "replay" and not key_configured:
        return f"OPENAI_API_KEY is not set; --llm {mode} calls the live model"
    return None


async def run(args: argparse.Namespace) -> int:
    from app.db.session import get_sessionmaker
    from app.services import llm_service
    from evals.stamp import corpus_stats, file_sha256, git_revision, now_utc, pipeline_config

    suites = list(SUITES) if args.suite == "all" else [args.suite]
    floors = load_floors(args.thresholds)

    datasets = {}
    for suite in suites:
        path = args.dataset or DATASETS_DIR / f"{suite}.jsonl"
        try:
            datasets[suite] = load_dataset(path, suite)
        except DatasetError as exc:
            print(f"dataset error: {exc}", file=sys.stderr)
            return EXIT_UNUSABLE

    selected = {suite: select(dataset.cases, args.tag, args.case) for suite, dataset in datasets.items()}
    for suite in list(suites):
        if selected[suite]:
            continue
        # The shipped visual dataset is an empty template. Filters in an all
        # run may also select cases from only one of the other suites.
        if args.suite == "all" and (args.tag or args.case or (suite == "visual" and not datasets[suite].cases)):
            suites.remove(suite)
            print(f"Skipping {suite}: no selected cases.")
        else:
            print(f"{suite}: no selected cases", file=sys.stderr)
            return EXIT_UNUSABLE
    if not suites:
        print("No cases match the requested selection", file=sys.stderr)
        return EXIT_UNUSABLE

    recorder = judgments = None
    if "ask" in suites:
        reason = ask_unavailable(args.llm, llm_service.is_configured(), FIXTURES_PATH)
        if reason and args.suite == "ask":
            print(reason, file=sys.stderr)
            return EXIT_UNUSABLE
        if reason:
            print(f"Skipping ask: {reason}.")
            suites.remove("ask")
        else:
            from app.config import get_settings

            recorder = CompletionRecorder(FIXTURES_PATH, args.llm, model=get_settings().openai_model)
            try:
                judgments = load_judgments(JUDGMENTS_PATH)
            except DatasetError as exc:
                print(f"dataset error: {exc}", file=sys.stderr)
                return EXIT_UNUSABLE

    try:
        db = get_sessionmaker()()
        corpus = corpus_stats(db)
    except (SQLAlchemyError, ImportError) as exc:
        print(f"database unavailable: {exc.__class__.__name__}: {exc}", file=sys.stderr)
        return EXIT_UNUSABLE
    try:
        db.rollback()
        started = now_utc()
        meta = {
            "started_at": started.isoformat(),
            "git": git_revision(),
            "corpus": corpus,
            "config": pipeline_config(),
            "datasets": {s: {"path": str(d.path), "sha256": file_sha256(d.path)} for s, d in datasets.items()},
            "filters": {"tags": args.tag, "cases": args.case},
        }
        if recorder is not None:
            meta["llm"] = {
                "mode": args.llm,
                "fixtures_sha256": file_sha256(FIXTURES_PATH) if FIXTURES_PATH.exists() else None,
                "judgments_sha256": file_sha256(JUDGMENTS_PATH) if JUDGMENTS_PATH.exists() else None,
            }
        print(
            f"git {meta['git']['sha']}{' (dirty)' if meta['git']['dirty'] else ''}  "
            f"corpus {meta['corpus']['text_embedded']} text / {meta['corpus']['image_embedded']} image  "
            f"rerank pool {meta['config']['rerank_pool']}"
        )

        reports: list[SuiteReport] = []
        for suite in suites:
            cases = selected[suite]
            variant = args.variant if suite == "search" else "production"
            target = make_target(suite, db, variant, recorder, judgments)
            target.warm_up()
            if suite == "ask":
                with recorder.installed():
                    results = await run_cases(target, cases, rollback=db.rollback)
                if args.llm == "record":
                    written = recorder.save()
                    print(
                        f"\nRecorded {recorder.calls} new completions, reused {recorder.hits}; "
                        f"{written} in {FIXTURES_PATH.relative_to(EVALS_DIR.parent)}"
                    )
                elif args.llm == "replay" and recorder.misses:
                    print(f"\n{recorder.misses} completions had no recording; re-record with --llm record")
            else:
                results = await run_cases(target, cases, rollback=db.rollback)
            summary = summarize(results)
            enforce = variant == "production" or args.enforce_floors
            suite_floors = floors.get(suite, {}) if enforce else {}
            report = SuiteReport(suite, variant, results, summary, suite_floors, check_floors(summary, suite_floors))
            reports.append(report)
            print()
            print(render(report, verbose=args.verbose))
    finally:
        db.close()

    if not args.no_save and reports:
        RESULTS_DIR.mkdir(exist_ok=True)
        name = f"{started:%Y%m%dT%H%M%SZ}-{args.suite}-{args.variant}.json"
        out = RESULTS_DIR / name
        out.write_text(
            json.dumps({**meta, "reports": [r.to_dict() for r in reports]}, indent=2, default=str),
            encoding="utf-8",
        )
        print(f"\nSaved {out.relative_to(EVALS_DIR.parent)}")

    if not reports:
        return EXIT_UNUSABLE
    return EXIT_BREACH if any(r.breaches for r in reports) else EXIT_OK


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        return asyncio.run(run(args))
    except Exception:
        logger.exception("Eval run crashed before it could be scored.")
        return EXIT_UNUSABLE


if __name__ == "__main__":
    sys.exit(main())
