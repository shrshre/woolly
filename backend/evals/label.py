"""Helpers for writing relevance labels by hand.

Ranked mode prints one variant's ranked list with ravelry ids:
    docker-compose exec backend python -m evals.label "cozy winter sweater"
    docker-compose exec backend python -m evals.label "hat" --craft Crochet --free
    docker-compose exec backend python -m evals.label --case search-intent-001 --variant vector

Pool mode prints, per case, the union of the top-k from every search variant,
sorted by ravelry id with no rank or score, so judging can't favour the
variant that happened to rank a row first:
    docker-compose exec backend python -m evals.label --pool
    docker-compose exec backend python -m evals.label --pool --case search-intent-003 --new-only

Label from the pool, then freeze the labels before reading a fresh scoreboard.
"""

import argparse
import logging
import sys

from evals.cases import EvalCase, load_dataset
from evals.run import DATASETS_DIR
from evals.targets import SEARCH_VARIANTS, SearchTarget

POOL_DESCRIPTION_CHARS = 160
POOL_TAG_LIMIT = 6


def search_cases() -> dict[str, EvalCase]:
    return {c.id: c for c in load_dataset(DATASETS_DIR / "search.jsonl", "search").cases}


def build_case(args: argparse.Namespace) -> EvalCase:
    if args.case:
        cases = search_cases()
        if args.case[0] not in cases:
            raise SystemExit(f"no search case {args.case[0]!r}")
        return cases[args.case[0]]
    if not args.query:
        raise SystemExit("give a query or --case")
    filters = {
        key: value
        for key, value in (
            ("craft", args.craft),
            ("category", args.category),
            ("difficulty", args.difficulty),
            ("free", True if args.free else False if args.paid else None),
        )
        if value is not None
    }
    return EvalCase(id="adhoc", suite="search", input={"query": args.query, "filters": filters}, expect={})


def print_ranked(db, args: argparse.Namespace) -> None:
    case = build_case(args)
    target = SearchTarget(db, args.variant)
    target.warm_up()
    observation = target.run(case)
    print(f"{case.input['query']!r} {case.filters or ''} ({args.variant}, {observation.latency_ms}ms)")
    for rank, r in enumerate(observation.results[: args.k], start=1):
        score = r.get("rerank_score", r.get("similarity_score"))
        facts = " / ".join(str(v) for v in (r.get("craft"), r.get("category")) if v)
        price = "free" if r.get("free") else "paid"
        print(
            f"{rank:>3}. {r['id']:>8}  {r.get('name')} — {r.get('designer') or '?'}"
            f"  [{facts}; {price}; diff {r.get('difficulty') or '-'}; score {score}]"
        )


def pool_line(r: dict) -> str:
    facts = " / ".join(str(v) for v in (r.get("craft"), r.get("category")) if v)
    tags = ", ".join((r.get("tags") or [])[:POOL_TAG_LIMIT])
    description = " ".join((r.get("description") or "").split())[:POOL_DESCRIPTION_CHARS]
    return f"  {r['id']:>8} | {r.get('name')} | {facts} | {tags} | {description}"


def print_pools(db, args: argparse.Namespace) -> None:
    cases = search_cases()
    selected = [cases[i] for i in args.case] if args.case else [
        c for c in cases.values() if "title" not in c.expect and "designer" not in c.expect
    ]
    targets = [SearchTarget(db, variant) for variant in SEARCH_VARIANTS]
    for target in targets:
        target.warm_up()

    for case in selected:
        judged = {int(k) for k in (case.expect.get("relevant_ids") or {})} if args.new_only else set()
        pool: dict[int, dict] = {}
        for target in targets:
            for r in target.run(case).results[: args.k]:
                pool.setdefault(r["id"], r)
            db.rollback()
        fresh = [pool[rid] for rid in sorted(pool) if rid not in judged]
        print(f"\n## {case.id}: {case.input['query']!r} {case.filters or ''}  ({len(fresh)} to judge)")
        for r in fresh:
            print(pool_line(r))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Show results with ravelry ids for labeling.")
    parser.add_argument("query", nargs="?")
    parser.add_argument("--case", action="append", default=[], help="Use a search.jsonl case (repeatable in --pool)")
    parser.add_argument("--pool", action="store_true", help="Pooled, unranked candidates from every variant")
    parser.add_argument("--new-only", action="store_true", help="With --pool, hide ids the case already judges")
    parser.add_argument("--variant", choices=SEARCH_VARIANTS, default="production")
    parser.add_argument("--craft")
    parser.add_argument("--category")
    parser.add_argument("--difficulty", choices=["beginner", "intermediate", "advanced"])
    parser.add_argument("--free", action="store_true")
    parser.add_argument("--paid", action="store_true")
    parser.add_argument("-k", type=int, default=10)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING)

    from app.db.session import get_sessionmaker

    db = get_sessionmaker()()
    try:
        if args.pool:
            print_pools(db, args)
        else:
            print_ranked(db, args)
    finally:
        db.rollback()
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
