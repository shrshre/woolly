"""Run cases against a target, aggregate a scoreboard, and check floors."""

import inspect
import traceback
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

from evals import metrics
from evals.cases import EvalCase
from evals.scoring import Check

PASS, FAIL, ERROR, SKIP = "pass", "fail", "error", "skip"


class Target(Protocol):
    suite: str
    variant: str

    def warm_up(self) -> None: ...
    def skip_reason(self, case: EvalCase) -> str | None: ...
    def run(self, case: EvalCase) -> Any: ...
    def score(self, case: EvalCase, observation: Any) -> tuple[list[Check], dict[str, float]]: ...
    def summarize(self, observation: Any) -> dict[str, Any]: ...


@dataclass
class CaseResult:
    case_id: str
    tags: list[str]
    status: str
    checks: list[Check] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)
    latency_ms: int | None = None
    detail: str = ""
    observed: dict[str, Any] = field(default_factory=dict)

    @property
    def failed_checks(self) -> list[Check]:
        return [c for c in self.checks if not c.passed]


@dataclass
class SuiteReport:
    suite: str
    variant: str
    results: list[CaseResult]
    summary: dict[str, Any]
    floors: dict[str, float]
    breaches: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


async def run_cases(target: Target, cases: list[EvalCase], *, rollback=None) -> list[CaseResult]:
    """Run every case. One case raising never stops the rest."""
    results = []
    for case in cases:
        tags = list(case.tags)
        try:
            reason = target.skip_reason(case)
            if reason:
                results.append(CaseResult(case.id, tags, SKIP, detail=reason))
                continue
            observation = target.run(case)
            if inspect.isawaitable(observation):
                observation = await observation
            checks, scores = target.score(case, observation)
            status = PASS if all(c.passed for c in checks) else FAIL
            results.append(
                CaseResult(
                    case.id,
                    tags,
                    status,
                    checks=checks,
                    metrics=scores,
                    latency_ms=observation.latency_ms,
                    observed=target.summarize(observation),
                )
            )
        except Exception as exc:
            detail = f"{type(exc).__name__}: {exc}"
            results.append(
                CaseResult(case.id, tags, ERROR, detail=detail, observed={"traceback": traceback.format_exc()})
            )
        finally:
            if rollback:
                rollback()
    return results


def summarize(results: list[CaseResult]) -> dict[str, Any]:
    counts = defaultdict(int)
    for r in results:
        counts[r.status] += 1
    scored = counts[PASS] + counts[FAIL] + counts[ERROR]

    by_metric: dict[str, list[float]] = defaultdict(list)
    for r in results:
        for name, value in r.metrics.items():
            by_metric[name].append(value)

    latencies = [r.latency_ms for r in results if r.latency_ms is not None]
    by_tag: dict[str, list[CaseResult]] = defaultdict(list)
    for r in results:
        for tag in r.tags:
            by_tag[tag].append(r)

    def tag_pass_rate(group: list[CaseResult]) -> float | None:
        ran = [r for r in group if r.status != SKIP]
        return sum(r.status == PASS for r in ran) / len(ran) if ran else None

    return {
        "cases": len(results),
        "passed": counts[PASS],
        "failed": counts[FAIL],
        "errored": counts[ERROR],
        "skipped": counts[SKIP],
        "pass_rate": counts[PASS] / scored if scored else None,
        "metrics": {
            name: {"mean": sum(values) / len(values), "n": len(values)}
            for name, values in sorted(by_metric.items())
        },
        "latency_ms": {
            "p50": metrics.percentile(latencies, 50),
            "p95": metrics.percentile(latencies, 95),
        },
        "pass_rate_by_tag": {tag: tag_pass_rate(group) for tag, group in sorted(by_tag.items())},
    }


def summary_value(summary: dict[str, Any], name: str) -> float | None:
    if name == "pass_rate":
        return summary["pass_rate"]
    if name in ("latency_p50_ms", "latency_p95_ms"):
        return summary["latency_ms"][name.split("_")[1]]
    metric = summary["metrics"].get(name)
    return metric["mean"] if metric else None


def check_floors(summary: dict[str, Any], floors: dict[str, float]) -> list[str]:
    """Floors are minimums, except latency keys, which are ceilings."""
    breaches = []
    for name, limit in floors.items():
        value = summary_value(summary, name)
        if value is None:
            continue
        if name.startswith("latency_"):
            if value > limit:
                breaches.append(f"{name} {value:.0f} > ceiling {limit}")
        elif value < limit:
            breaches.append(f"{name} {value:.3f} < floor {limit}")
    return breaches


def _fmt(value: float | None, digits: int = 3) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


def render(report: SuiteReport, *, verbose: bool = False) -> str:
    lines = [f"== {report.suite} ({report.variant}) =="]
    width = max([len(r.case_id) for r in report.results] + [4])
    for r in report.results:
        if r.status == PASS and not verbose:
            continue
        reason = r.detail or "; ".join(f"{c.name}: {c.detail}" for c in r.failed_checks)
        lines.append(f"  {r.status.upper():5} {r.case_id:<{width}}  {reason}")

    s = report.summary
    lines.append("")
    lines.append(
        f"  cases {s['cases']}  passed {s['passed']}  failed {s['failed']}  "
        f"errored {s['errored']}  skipped {s['skipped']}  pass_rate {_fmt(s['pass_rate'])}"
    )
    rows = [("pass_rate", s["pass_rate"], None)]
    rows += [(name, m["mean"], m["n"]) for name, m in s["metrics"].items()]
    rows += [
        ("latency_p50_ms", s["latency_ms"]["p50"], None),
        ("latency_p95_ms", s["latency_ms"]["p95"], None),
    ]
    lines.append(f"  {'metric':<22} {'value':>8} {'n':>4} {'floor':>8}")
    for name, value, n in rows:
        floor = report.floors.get(name)
        digits = 0 if name.startswith("latency_") else 3
        lines.append(
            f"  {name:<22} {_fmt(value, digits):>8} {'' if n is None else n:>4} "
            f"{'' if floor is None else floor:>8}"
        )
    if s["pass_rate_by_tag"]:
        tags = "  ".join(f"{tag} {_fmt(rate, 2)}" for tag, rate in s["pass_rate_by_tag"].items())
        lines.append(f"  by tag: {tags}")
    for breach in report.breaches:
        lines.append(f"  FLOOR BREACHED: {breach}")
    return "\n".join(lines)
