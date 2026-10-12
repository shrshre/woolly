"""Reranker warm-up: loads the model and runs one real prediction."""

from app import main
from app.services import reranking_service


class FakeModel:
    def __init__(self):
        self.calls = []

    def predict(self, pairs):
        self.calls.append(pairs)
        return [0.0 for _ in pairs]


def test_warm_up_runs_one_prediction(monkeypatch):
    model = FakeModel()
    monkeypatch.setattr(reranking_service, "get_reranker", lambda: model)

    reranking_service.warm_up()

    assert len(model.calls) == 1


def test_background_warm_up_swallows_failures(monkeypatch):
    def boom():
        raise RuntimeError("no memory")

    monkeypatch.setattr(reranking_service, "warm_up", boom)

    main._warm_reranker()  # must not raise: the first search loads lazily
