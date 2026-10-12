"""Time the cross-encoder rerank stage on the search eval queries.

For each query in evals/datasets/search.jsonl it pulls the stage-1 candidate
pool once, then times rerank variants on that identical pool. Score-preserving
variants are checked against the baseline ordering; pool-size variants are
reported with the overlap of their top 10 against the baseline top 10.

Latency only: this does not read relevance labels or compute nDCG, so it
cannot be used to tune against the labeled set. Run `python -m evals.run
--suite search` for quality.

Usage (inside the backend container):
    python scripts/bench_rerank.py          # batching, truncation, pool size
    python scripts/bench_rerank.py engine   # thread count, int8 quantization
    python scripts/bench_rerank.py onnx     # ONNX Runtime backend vs torch
"""

import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import torch  # noqa: E402

from app.db.session import get_sessionmaker  # noqa: E402
from app.search.hybrid_search import hybrid_search  # noqa: E402
from app.search.pipeline import RERANK_POOL  # noqa: E402
from app.services import reranking_service as rs  # noqa: E402

DATASET = Path(__file__).resolve().parents[1] / "evals" / "datasets" / "search.jsonl"
REPEATS = 5


def load_queries() -> list[tuple[str, dict]]:
    out = []
    for line in DATASET.read_text().splitlines():
        if line.strip():
            case = json.loads(line)
            out.append((case["input"]["query"], case["input"].get("filters") or {}))
    return out


def pctl(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))]


def timed(fn) -> float:
    start = time.perf_counter()
    fn()
    return (time.perf_counter() - start) * 1000


def main(mode: str) -> None:
    model = rs.get_reranker()
    model.predict([("warm up", "warm up")])
    print(f"torch threads={torch.get_num_threads()}  pool={RERANK_POOL}  max_seq_length={model.max_seq_length}")

    session = get_sessionmaker()()
    pools = []
    for query, filters in load_queries():
        candidates, _ = hybrid_search(session, query, limit=RERANK_POOL, **filters)
        if candidates:
            pools.append((query, candidates))
    print(f"{len(pools)} queries with candidates\n")

    def run(name, predict, pool_size=RERANK_POOL, baseline_orders=None):
        times, orders = [], []
        for query, candidates in pools:
            pairs = [(query, rs._pattern_to_text(c)) for c in candidates[:pool_size]]
            samples = [timed(lambda: predict(pairs)) for _ in range(REPEATS)]
            times.append(statistics.median(samples))
            scores = predict(pairs)
            order = [c["id"] for c, _ in sorted(zip(candidates, scores), key=lambda x: -float(x[1]))]
            orders.append(order)
        same = top10 = ""
        if baseline_orders is not None:
            same = sum(a == b for a, b in zip(orders, baseline_orders)) / len(orders)
            top10 = statistics.mean(len(set(a[:10]) & set(b[:10])) / 10 for a, b in zip(orders, baseline_orders))
            same, top10 = f"{same:.2f}", f"{top10:.2f}"
        print(f"{name:34s} p50={pctl(times, .5):6.1f}ms p95={pctl(times, .95):6.1f}ms  same_order={same:>5}  top10_overlap={top10:>5}")
        return orders

    base = run("baseline predict() batch=32", lambda p: model.predict(p))
    if mode == "basic":
        run("batch_size=64", lambda p: model.predict(p, batch_size=64), baseline_orders=base)
        run("batch_size=16", lambda p: model.predict(p, batch_size=16), baseline_orders=base)
        for length in (128, 96):
            model.max_seq_length = length
            run(f"max_seq_length={length}", lambda p: model.predict(p), baseline_orders=base)
        model.max_seq_length = 512
        for size in (40, 30):
            run(f"pool={size}", lambda p: model.predict(p), pool_size=size, baseline_orders=base)
        return

    if mode == "onnx":
        from sentence_transformers import CrossEncoder

        onnx_model = CrossEncoder(rs.MODEL_NAME, backend="onnx")
        onnx_model.predict([("warm up", "warm up")])
        run("onnx fp32", lambda p: onnx_model.predict(p), baseline_orders=base)
        scores_gap = []
        for query, candidates in pools[:10]:
            pairs = [(query, rs._pattern_to_text(c)) for c in candidates]
            a, b = model.predict(pairs), onnx_model.predict(pairs)
            scores_gap.append(float(abs(a - b).max()))
        print(f"max |logit diff| torch vs onnx over 10 queries: {max(scores_gap):.5f}")
        return

    default_threads = torch.get_num_threads()
    for threads in (4, 8):
        torch.set_num_threads(threads)
        run(f"threads={threads}", lambda p: model.predict(p), baseline_orders=base)
    torch.set_num_threads(default_threads)

    quantized = torch.quantization.quantize_dynamic(model.model, {torch.nn.Linear}, dtype=torch.qint8)
    original = model.model
    model.model = quantized
    run("int8 dynamic quantization", lambda p: model.predict(p), baseline_orders=base)
    for threads in (4, 8):
        torch.set_num_threads(threads)
        run(f"int8 + threads={threads}", lambda p: model.predict(p), baseline_orders=base)
    model.model = original


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "basic")
