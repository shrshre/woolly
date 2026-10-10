"""Per-request stage timings and degradation flags.

``TraceMiddleware`` opens a :class:`Trace` for every HTTP request. Code on the
hot path wraps its stages in ``stage("embed")``, ``stage("rerank")``... and
calls ``fallback("rerank")`` when it degrades instead of failing. Both are
no-ops outside a request, so seeding and the offline evals pay nothing.

Stage times are exclusive: time spent in a stage nested inside another (the
query embedding inside retrieval) is subtracted from the parent, so the
stages of one request never add up to more than its latency.

The route that logs a ``search_events`` row copies the trace onto it and
writes one structured log line per request.
"""

import json
import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

request_logger = logging.getLogger("woolly.requests")


@dataclass
class Trace:
    stages: dict[str, float] = field(default_factory=dict)
    fallbacks: list[str] = field(default_factory=list)
    # Time spent in child stages, one slot per open stage.
    _open: list[float] = field(default_factory=list)

    def stage_ms(self) -> dict[str, int]:
        return {name: round(ms) for name, ms in self.stages.items()}


_current: ContextVar[Trace | None] = ContextVar("woolly_trace", default=None)


def current() -> Trace | None:
    return _current.get()


@contextmanager
def track() -> Iterator[Trace]:
    trace = Trace()
    token = _current.set(trace)
    try:
        yield trace
    finally:
        _current.reset(token)


@contextmanager
def stage(name: str) -> Iterator[None]:
    trace = _current.get()
    if trace is None:
        yield
        return
    started = time.perf_counter()
    trace._open.append(0.0)
    try:
        yield
    finally:
        children = trace._open.pop()
        elapsed = (time.perf_counter() - started) * 1000
        trace.stages[name] = trace.stages.get(name, 0.0) + elapsed - children
        if trace._open:
            trace._open[-1] += elapsed


def fallback(name: str) -> None:
    """Record that the request degraded (served, but worse than designed)."""
    trace = _current.get()
    if trace is not None and name not in trace.fallbacks:
        trace.fallbacks.append(name)


def degraded() -> bool:
    trace = _current.get()
    return bool(trace and trace.fallbacks)


def log_request(**fields: Any) -> None:
    request_logger.info(json.dumps(fields, sort_keys=True, default=str))


class TraceMiddleware:
    """Pure ASGI, not BaseHTTPMiddleware, so the route runs in the same context."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        with track():
            await self.app(scope, receive, send)
