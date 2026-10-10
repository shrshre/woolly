"""Stage timings and degradation flags (app/observability.py). No FastAPI needed."""

import asyncio
import json
import logging

import pytest

from app import observability
from app.observability import TraceMiddleware, current, degraded, fallback, stage, track


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, ms):
        self.now += ms / 1000


@pytest.fixture
def clock(monkeypatch):
    fake = FakeClock()
    monkeypatch.setattr(observability.time, "perf_counter", fake)
    return fake


def test_stages_are_no_ops_outside_a_request():
    with stage("embed"):
        pass
    fallback("rerank")
    assert current() is None and not degraded()


def test_nested_stage_time_is_subtracted_from_the_parent(clock):
    with track() as trace:
        with stage("retrieve"):
            clock.advance(30)
            with stage("embed"):
                clock.advance(20)
            clock.advance(10)
        with stage("rerank"):
            clock.advance(200)
    assert trace.stage_ms() == {"retrieve": 40, "embed": 20, "rerank": 200}


def test_repeated_stages_accumulate(clock):
    with track() as trace:
        for _ in range(2):
            with stage("retrieve"):
                clock.advance(15)
    assert trace.stage_ms() == {"retrieve": 30}


def test_a_stage_that_raises_is_still_timed(clock):
    with track() as trace:
        with pytest.raises(RuntimeError):
            with stage("rerank"):
                clock.advance(5)
                raise RuntimeError("model gone")
    assert trace.stage_ms() == {"rerank": 5}


def test_fallbacks_are_recorded_once():
    with track() as trace:
        assert not degraded()
        fallback("rerank")
        fallback("rerank")
        fallback("extract")
        assert degraded()
    assert trace.fallbacks == ["rerank", "extract"]
    assert current() is None


@pytest.mark.asyncio
async def test_concurrent_requests_get_separate_traces():
    async def request(name):
        with track() as trace:
            await asyncio.sleep(0)
            fallback(name)
            await asyncio.sleep(0)
            return trace.fallbacks

    assert await asyncio.gather(request("a"), request("b")) == [["a"], ["b"]]


@pytest.mark.asyncio
async def test_middleware_opens_a_trace_for_http_only():
    seen = []

    async def app(scope, receive, send):
        seen.append(current())

    middleware = TraceMiddleware(app)
    await middleware({"type": "http"}, None, None)
    await middleware({"type": "lifespan"}, None, None)
    assert seen[0] is not None and seen[1] is None


def test_log_request_is_one_json_line(caplog):
    with caplog.at_level(logging.INFO, logger="woolly.requests"):
        observability.log_request(search_type="hybrid", stage_ms={"rerank": 240}, error=None)
    assert json.loads(caplog.records[-1].getMessage()) == {
        "error": None,
        "search_type": "hybrid",
        "stage_ms": {"rerank": 240},
    }


def test_rerank_failure_marks_the_request_degraded(monkeypatch):
    from app.search import pipeline

    class _DB:
        def query(self, *_):
            return self

        def filter(self, *_):
            return self

        def scalar(self):
            return 1

    def broken(*_, **__):
        raise RuntimeError("cross-encoder unavailable")

    monkeypatch.setattr(pipeline, "hybrid_search", lambda *a, **k: ([{"id": 1}, {"id": 2}], "hybrid"))
    monkeypatch.setattr(pipeline.reranking_service, "rerank", broken)
    with track() as trace:
        envelope = pipeline.search(_DB(), "hat")
    assert [r["id"] for r in envelope["results"]] == [1, 2]
    assert trace.fallbacks == ["rerank"]
    assert {"retrieve", "rerank"} <= set(trace.stages)
