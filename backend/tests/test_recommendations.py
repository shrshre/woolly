"""Unit tests for the pure parts of the recommendation engine:
taste-vector combination and the designer-diversity pass."""

from types import SimpleNamespace

import numpy as np
import pytest

from app.search.recommendations import (
    MAX_PER_DESIGNER,
    QUERY_WEIGHT,
    SAVED_WEIGHT,
    combine_signal_vectors,
    diversify,
)


def _unit(vec: list[float]) -> np.ndarray:
    arr = np.asarray(vec, dtype=np.float32)
    return arr / np.linalg.norm(arr)


class TestCombineSignalVectors:
    def test_no_signals_returns_none(self):
        assert combine_signal_vectors([], []) is None

    def test_zero_vectors_return_none(self):
        assert combine_signal_vectors([[0.0, 0.0]], [[0.0, 0.0]]) is None

    def test_single_saved_vector_is_normalized_passthrough(self):
        taste = combine_signal_vectors([[3.0, 4.0]], [])
        assert taste is not None
        np.testing.assert_allclose(taste, [0.6, 0.8], atol=1e-6)

    def test_result_is_unit_length(self):
        taste = combine_signal_vectors([[1.0, 2.0], [2.0, 1.0]], [[0.5, 0.5]])
        assert taste is not None
        assert np.linalg.norm(taste) == pytest.approx(1.0, abs=1e-6)

    def test_saved_patterns_outweigh_queries(self):
        # A save pointing along x and a query pointing along y: the taste
        # vector should lean toward x by SAVED_WEIGHT / QUERY_WEIGHT.
        taste = combine_signal_vectors([[1.0, 0.0]], [[0.0, 1.0]])
        assert taste is not None
        assert taste[0] / taste[1] == pytest.approx(SAVED_WEIGHT / QUERY_WEIGHT, rel=1e-5)

    def test_queries_alone_produce_a_taste_vector(self):
        taste = combine_signal_vectors([], [[0.0, 5.0]])
        assert taste is not None
        np.testing.assert_allclose(taste, _unit([0.0, 5.0]), atol=1e-6)


def _pattern(pid: int, designer: str | None) -> SimpleNamespace:
    return SimpleNamespace(id=pid, designer=designer)


class TestDiversify:
    def test_caps_patterns_per_designer(self):
        candidates = [_pattern(i, "Prolific Designer") for i in range(1, 5)]
        candidates.append(_pattern(5, "Someone Else"))
        picked = diversify(candidates, limit=3)
        prolific = [p for p in picked if p.designer == "Prolific Designer"]
        assert len(prolific) == MAX_PER_DESIGNER
        assert picked[-1].id == 5

    def test_designer_cap_is_case_insensitive(self):
        candidates = [
            _pattern(1, "jane doe"),
            _pattern(2, "Jane Doe"),
            _pattern(3, "JANE DOE"),
            _pattern(4, "Other"),
        ]
        picked = diversify(candidates, limit=3)
        assert [p.id for p in picked] == [1, 2, 4]

    def test_backfills_when_cap_starves_the_page(self):
        # Only one designer available: the cap can't be honored without
        # returning fewer results, so extras are backfilled in order.
        candidates = [_pattern(i, "Only Designer") for i in range(1, 6)]
        picked = diversify(candidates, limit=4)
        assert [p.id for p in picked] == [1, 2, 3, 4]

    def test_unknown_designers_are_never_capped(self):
        candidates = [_pattern(i, None) for i in range(1, 6)]
        picked = diversify(candidates, limit=4)
        assert [p.id for p in picked] == [1, 2, 3, 4]

    def test_preserves_best_first_order(self):
        candidates = [_pattern(1, "A"), _pattern(2, "B"), _pattern(3, "C")]
        picked = diversify(candidates, limit=3)
        assert [p.id for p in picked] == [1, 2, 3]
