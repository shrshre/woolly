"""Health, request logging, and admin analytics shaping. Needs FastAPI, so it
runs in the backend container: docker-compose exec backend pytest tests/"""

from datetime import date, datetime

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from app import main, observability  # noqa: E402
from app.api import admin, patterns  # noqa: E402
from app.auth.dependencies import get_current_user_optional  # noqa: E402
from app.db.session import get_db  # noqa: E402


class FakeRedis:
    def __init__(self, up=True):
        self.up = up

    async def ping(self):
        if not self.up:
            raise ConnectionError("redis down")
        return True


@pytest.fixture
def client():
    return TestClient(main.app)  # no `with`: skip the lifespan (models, DB init)


@pytest.mark.parametrize(
    ("postgres_up", "redis_up", "status", "body"),
    [
        (True, True, 200, {"status": "ok", "postgres": "ok", "redis": "ok"}),
        (False, True, 503, {"status": "degraded", "postgres": "down", "redis": "ok"}),
        (True, False, 503, {"status": "degraded", "postgres": "ok", "redis": "down"}),
    ],
)
def test_health_checks_both_stores(client, monkeypatch, postgres_up, redis_up, status, body):
    def ping_postgres():
        if not postgres_up:
            raise OSError("connection refused")

    monkeypatch.setattr(main, "_ping_postgres", ping_postgres)
    monkeypatch.setattr(main, "get_redis", lambda: FakeRedis(redis_up))
    response = client.get("/health")
    assert (response.status_code, response.json()) == (status, body)


def test_health_times_out_a_hung_store(client, monkeypatch):
    import time

    monkeypatch.setattr(main, "HEALTH_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(main, "_ping_postgres", lambda: time.sleep(0.5))
    monkeypatch.setattr(main, "get_redis", lambda: FakeRedis())
    response = client.get("/health")
    assert response.status_code == 503 and response.json()["postgres"] == "down"


class FakeSession:
    def __init__(self):
        self.events = []
        self.rollbacks = 0

    def add(self, event):
        event.id = len(self.events) + 1
        self.events.append(event)

    def commit(self):
        pass

    def rollback(self):
        self.rollbacks += 1


ROW = {"id": 7, "name": "Harbor Hat", "similarity_score": 0.9, "rerank_score": None}


@pytest.fixture
def search_api(monkeypatch):
    session = FakeSession()
    cached = []
    main.app.dependency_overrides[get_db] = lambda: session
    main.app.dependency_overrides[get_current_user_optional] = lambda: None

    async def no_cache(_key):
        return None

    async def remember(key, value, ttl):
        cached.append(key)

    monkeypatch.setattr(patterns, "get_cached", no_cache)
    monkeypatch.setattr(patterns, "set_cached", remember)
    yield session, cached, TestClient(main.app)
    main.app.dependency_overrides.clear()


def _pipeline(degrade=False, fail=False):
    def run(db, query, **filters):
        if fail:
            raise RuntimeError("database is gone")
        with observability.stage("rerank"):
            pass
        if degrade:
            observability.fallback("rerank")
        return {"results": [ROW], "top_result_id": 1, "search_type": "hybrid", "latency_ms": 5}

    return run


def test_search_logs_stages_and_caches_a_healthy_result(search_api, monkeypatch):
    session, cached, client = search_api
    monkeypatch.setattr(patterns, "run_search_pipeline", _pipeline())
    assert client.get("/patterns/semantic-search", params={"q": "hat"}).status_code == 200
    event = session.events[0]
    assert {"cache", "rerank"} <= set(event.stage_ms)
    assert event.fallbacks == [] and event.error is None
    assert cached == ["semantic:hat"]


def test_degraded_search_is_served_but_not_cached(search_api, monkeypatch):
    session, cached, client = search_api
    monkeypatch.setattr(patterns, "run_search_pipeline", _pipeline(degrade=True))
    response = client.get("/patterns/semantic-search", params={"q": "hat"})
    assert response.status_code == 200 and response.json()["patterns"][0]["name"] == "Harbor Hat"
    assert session.events[0].fallbacks == ["rerank"]
    assert cached == []


def test_failed_search_is_logged_as_an_error(search_api, monkeypatch):
    session, cached, client = search_api
    monkeypatch.setattr(patterns, "run_search_pipeline", _pipeline(fail=True))
    assert client.get("/patterns/semantic-search", params={"q": "hat"}).status_code == 503
    event = session.events[0]
    assert (event.error, event.result_count, session.rollbacks) == ("retrieval", 0, 1)
    assert event.latency_ms >= 1
    assert cached == []


def test_analytics_stays_closed_without_a_token(client, monkeypatch):
    from app.config import Settings

    main.app.dependency_overrides[admin.get_settings] = lambda: Settings(admin_api_token="")
    try:
        assert client.get("/admin/analytics", headers={"X-Admin-Token": ""}).status_code == 403
    finally:
        main.app.dependency_overrides.clear()


def test_window_start_counts_today_as_day_one():
    assert admin.window_start(1, date(2026, 10, 10)) == datetime(2026, 10, 10)
    assert admin.window_start(7, date(2026, 10, 10)) == datetime(2026, 10, 4)


def _surface(name, **overrides):
    row = {
        "surface": name, "requests": 10, "errors": 2, "degraded": 1, "cache_hit_rate": 0.25,
        "zero_result_rate": 0.1, "save_rate": None, "click_rate": 0.05, "semantic_fallback_rate": 0.3,
        "p50": 300.4, "p95": 410.6, "uncached_p50": 320, "uncached_p95": 420,
    }
    return {**row, **overrides}


def test_shape_report_per_surface():
    report = admin.shape_report(
        [_surface("search"), _surface("ask", errors=0)],
        [
            {"surface": "search", "stage": "rerank", "n": 8, "p50": 240, "p95": 288},
            {"surface": "search", "stage": "retrieve", "n": 8, "p50": 70, "p95": 90},
            {"surface": "ask", "stage": "extract", "n": 3, "p50": 1200, "p95": 2100},
        ],
        [{"surface": "search", "name": "rerank", "n": 1}],
        [{"surface": "search", "name": "retrieval", "n": 2}],
    )
    search = report["search"]
    assert search["error_rate"] == 0.2 and search["save_rate"] is None
    assert search["latency_ms"] == {"p50": 300, "p95": 411}
    assert search["slowest_stage"] == "rerank"
    assert search["fallbacks"] == {"rerank": 1} and search["errors_by_kind"] == {"retrieval": 2}
    assert "semantic_fallback_rate" in search and "semantic_fallback_rate" not in report["ask"]
    assert report["ask"]["slowest_stage"] == "extract" and report["ask"]["fallbacks"] == {}


def test_shape_report_with_no_traffic():
    assert admin.shape_report([], [], [], []) == {}
