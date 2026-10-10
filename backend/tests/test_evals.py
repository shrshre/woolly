"""Unit tests for the eval harness: dataset validation, metrics, scoring, and
the runner (with a fake target, so no Postgres or models are needed)."""

import json
import math

import pytest

from evals import metrics
from evals.cases import DatasetError, EvalCase, load_dataset
from evals.judgments import Judgment, answer_sha, load_judgments
from evals.llm_fixtures import CompletionRecorder, FixtureMissing, request_key
from evals.run import DATASETS_DIR, JUDGMENTS_PATH, THRESHOLDS_PATH, ask_unavailable, load_floors, parse_args
from evals.runner import ERROR, FAIL, PASS, SKIP, check_floors, render, run_cases, summarize, SuiteReport
from evals.scoring import Check, satisfies_filters, score_ask, score_ranked, ungrounded_names, unsupported_numbers
from evals.targets import Observation


def _write(tmp_path, lines: list) -> object:
    path = tmp_path / "cases.jsonl"
    path.write_text("\n".join(l if isinstance(l, str) else json.dumps(l) for l in lines), encoding="utf-8")
    return path


def _search_case(**overrides) -> dict:
    return {
        "id": "s1",
        "suite": "search",
        "input": {"query": "hat"},
        "expect": {"terms_any": ["hat"]},
        **overrides,
    }


class TestLoadDataset:
    def test_shipped_datasets_parse(self):
        for suite in ("search", "ask", "visual"):
            load_dataset(DATASETS_DIR / f"{suite}.jsonl", suite)

    def test_search_set_has_enough_cases(self):
        assert len(load_dataset(DATASETS_DIR / "search.jsonl", "search").cases) >= 30

    def test_skips_blank_and_comment_lines(self, tmp_path):
        path = _write(tmp_path, ["", "// a note", _search_case()])
        dataset = load_dataset(path, "search")
        assert [c.id for c in dataset.cases] == ["s1"]
        assert dataset.cases[0].line == 3

    def test_duplicate_ids_are_rejected(self, tmp_path):
        path = _write(tmp_path, [_search_case(), _search_case()])
        with pytest.raises(DatasetError, match="duplicate id"):
            load_dataset(path, "search")

    def test_typo_in_expect_is_rejected(self, tmp_path):
        path = _write(tmp_path, [_search_case(expect={"term_any": ["hat"]})])
        with pytest.raises(DatasetError, match="unknown expect keys"):
            load_dataset(path, "search")

    def test_wrong_suite_is_rejected(self, tmp_path):
        path = _write(tmp_path, [_search_case(suite="ask")])
        with pytest.raises(DatasetError, match="suite must be 'search'"):
            load_dataset(path, "search")

    def test_search_case_needs_a_signal(self, tmp_path):
        path = _write(tmp_path, [_search_case(expect={})])
        with pytest.raises(DatasetError, match="at least one signal"):
            load_dataset(path, "search")

    def test_bad_filters_are_rejected(self, tmp_path):
        path = _write(tmp_path, [_search_case(input={"query": "hat", "filters": {"difficulty": "expert"}})])
        with pytest.raises(DatasetError, match="difficulty"):
            load_dataset(path, "search")

    def test_string_free_is_rejected(self, tmp_path):
        path = _write(tmp_path, [_search_case(input={"query": "hat", "filters": {"free": "true"}})])
        with pytest.raises(DatasetError, match="free"):
            load_dataset(path, "search")

    def test_invalid_json_names_the_line(self, tmp_path):
        path = _write(tmp_path, [_search_case(), "{not json"])
        with pytest.raises(DatasetError, match=r"cases.jsonl:2"):
            load_dataset(path, "search")

    def test_ask_history_turns_are_validated(self, tmp_path):
        case = {"id": "a1", "suite": "ask", "input": {"message": "more?", "history": [{"role": "system", "content": "x"}]}}
        with pytest.raises(DatasetError, match="history"):
            load_dataset(_write(tmp_path, [case]), "ask")

    def test_graded_relevant_ids(self, tmp_path):
        path = _write(tmp_path, [_search_case(expect={"relevant_ids": {"101": 2, "102": 1}})])
        assert load_dataset(path, "search").cases[0].expect["relevant_ids"] == {"101": 2, "102": 1}

    def test_grade_zero_is_a_judgment(self, tmp_path):
        path = _write(tmp_path, [_search_case(expect={"relevant_ids": {"101": 2, "102": 0}})])
        assert load_dataset(path, "search").cases[0].expect["relevant_ids"]["102"] == 0

    @pytest.mark.parametrize("bad", [{"101": 0}, {"101": -1}, {"101": True}, {"abc": 1}])
    def test_bad_grades_are_rejected(self, tmp_path, bad):
        with pytest.raises(DatasetError, match="relevant_ids"):
            load_dataset(_write(tmp_path, [_search_case(expect={"relevant_ids": bad})]), "search")

    def test_shipped_search_labels_are_graded(self):
        cases = load_dataset(DATASETS_DIR / "search.jsonl", "search").cases
        labeled = [c for c in cases if isinstance(c.expect.get("relevant_ids"), dict)]
        assert len(labeled) >= 20


class TestMetrics:
    def test_ndcg_is_one_for_ideal_order(self):
        assert metrics.ndcg_at_k([1, 2, 3], {1: 2.0, 2: 1.0}) == pytest.approx(1.0)

    def test_ndcg_penalises_late_relevant(self):
        expected = (1 / math.log2(3)) / 1.0
        assert metrics.ndcg_at_k([9, 1], {1: 1.0}) == pytest.approx(expected)

    def test_ndcg_with_no_relevant_is_zero(self):
        assert metrics.ndcg_at_k([1, 2], {}) == 0.0

    def test_recall_and_rr(self):
        assert metrics.recall_at_k([1, 2, 3], [3, 4], k=3) == 0.5
        assert metrics.reciprocal_rank([False, False, True]) == pytest.approx(1 / 3)
        assert metrics.reciprocal_rank([False]) == 0.0

    def test_precision_counts_missing_slots_as_misses(self):
        assert metrics.precision_at_k([True, True], 5) == 0.4

    def test_term_match_is_word_start(self):
        assert metrics.contains_any("Cosy Hats for Winter", ["hat"])
        assert not metrics.contains_any("That one scarf", ["hat"])

    def test_percentile(self):
        assert metrics.percentile([10, 20, 30, 40], 50) == 20
        assert metrics.percentile([10, 20, 30, 40], 95) == 40
        assert metrics.percentile([], 50) is None

    def test_citations(self):
        assert metrics.citations("Try [1], or [3] if you like cables [1].") == [1, 3, 1]


def _case(suite="search", **expect) -> EvalCase:
    return EvalCase(id="c", suite=suite, input={"query": "q"}, expect=expect)


def _row(rid, name, **extra) -> dict:
    return {"id": rid, "name": name, "designer": "Jane", "description": "", **extra}


class TestScoreRanked:
    def test_terms_precision_pass_and_fail(self):
        results = [_row(1, "Cabled Hat"), _row(2, "Beanie"), _row(3, "Scarf")]
        checks, scores = score_ranked(_case(terms_any=["hat", "beanie"], terms_k=3, min_term_precision=0.6), results)
        assert scores["term_precision@3"] == pytest.approx(2 / 3)
        assert all(c.passed for c in checks)

        checks, _ = score_ranked(_case(terms_any=["sock"], terms_k=3), results)
        assert not next(c for c in checks if c.name == "terms_any").passed

    def test_tags_and_category_count_for_terms(self):
        results = [_row(1, "Harbor", category="Hat", tags=["cables"])]
        _, scores = score_ranked(_case(terms_any=["cable"], terms_k=1), results)
        assert scores["term_precision@1"] == 1.0

    def test_relevant_ids_metrics(self):
        results = [_row(5, "A"), _row(7, "B")]
        checks, scores = score_ranked(_case(relevant_ids=[7]), results)
        assert scores["recall@10"] == 1.0
        assert scores["mrr"] == 0.5
        assert next(c for c in checks if c.name == "relevant_in_top10").passed

    def test_grade_zero_counts_as_judged_not_relevant(self):
        results = [_row(5, "A"), _row(7, "B"), _row(9, "C")]
        _, scores = score_ranked(_case(relevant_ids={"5": 0, "7": 2}), results)
        assert scores["mrr"] == 0.5
        assert scores["recall@10"] == 1.0
        assert scores["judged@10"] == pytest.approx(2 / 3)

    def test_candidate_recall_only_with_candidates(self):
        case = _case(relevant_ids={"7": 1, "8": 1})
        _, scores = score_ranked(case, [_row(7, "B")])
        assert "candidate_recall@20" not in scores

        candidates = [7] + list(range(100, 130)) + [8]
        _, scores = score_ranked(case, [_row(7, "B")], candidate_ids=candidates)
        assert scores["candidate_recall@20"] == 0.5
        assert scores["candidate_recall@60"] == 1.0

    def test_zero_result_rate(self):
        assert score_ranked(_case(terms_any=["hat"]), [])[1]["zero_result_rate"] == 1.0
        assert score_ranked(_case(terms_any=["hat"]), [_row(1, "Hat")])[1]["zero_result_rate"] == 0.0

    def test_designer_match_ignores_spaces(self):
        results = [_row(1, "A", designer="tincanknits")] * 10
        checks, scores = score_ranked(_case(designer="Tin Can Knits"), results)
        assert scores["designer_share@10"] == 1.0

    def test_ndcg_floor(self):
        checks, _ = score_ranked(_case(relevant_ids={"7": 1}, **{"min_ndcg@10": 0.9}), [_row(5, "A"), _row(7, "B")])
        assert not next(c for c in checks if c.name == "ndcg@10").passed

    def test_title_rank(self):
        results = [_row(1, "Flax Light"), _row(2, "Flax")]
        checks, scores = score_ranked(_case(title="Flax", title_max_rank=1), results)
        assert scores["title_mrr"] == 1.0
        assert next(c for c in checks if c.name == "title").passed

    def test_designer_share(self):
        results = [_row(1, "A", designer="Tin Can Knits")] * 4 + [_row(2, "B")] * 6
        checks, scores = score_ranked(_case(designer="tin can"), results)
        assert scores["designer_share@10"] == 0.4
        assert not next(c for c in checks if c.name == "designer").passed

    def test_forbidden_terms_only_within_cutoff(self):
        results = [_row(1, "Shawl"), _row(2, "Shawl"), _row(3, "Vanilla Socks")]
        checks, _ = score_ranked(_case(forbid_terms=["socks"], forbid_k=2), results)
        assert next(c for c in checks if c.name == "forbid_terms").passed
        checks, _ = score_ranked(_case(forbid_terms=["socks"], forbid_k=3), results)
        assert not next(c for c in checks if c.name == "forbid_terms").passed

    def test_empty_results_fail_min_results(self):
        checks, _ = score_ranked(_case(terms_any=["hat"]), [])
        assert not next(c for c in checks if c.name == "min_results").passed

    def test_filters_are_checked_on_returned_rows(self):
        case = EvalCase(id="c", suite="search", input={"query": "q", "filters": {"craft": "Crochet", "free": True}}, expect={"terms_any": ["x"]})
        results = [_row(1, "x", craft="Crochet", free=True), _row(2, "x", craft="Knitting", free=True)]
        checks, scores = score_ranked(case, results)
        assert scores["filter_precision@10"] == 0.5
        assert not next(c for c in checks if c.name == "filters_hold").passed

    def test_satisfies_difficulty(self):
        assert satisfies_filters({"difficulty": "2.5"}, {"difficulty": "beginner"})
        assert not satisfies_filters({"difficulty": "0"}, {"difficulty": "beginner"})
        assert not satisfies_filters({"difficulty": None}, {"difficulty": "beginner"})
        assert not satisfies_filters({"difficulty": "7"}, {"difficulty": "intermediate"})


def _outcome(**overrides) -> dict:
    return {
        "answer": "Start with [1].",
        "patterns": [{"id": 1, "name": "Harbor Cowl"}],
        "search_query": "cozy cowl",
        "filters": {},
        "filters_relaxed": False,
        **overrides,
    }


def _ask(**expect) -> EvalCase:
    return EvalCase(id="c", suite="ask", input={"message": "q"}, expect=expect)


class TestScoreAsk:
    def test_out_of_range_citation_fails(self):
        checks, scores = score_ask(_case("ask"), _outcome(answer="Try [1] or [4]."))
        assert scores["citation_validity"] == 0.0
        assert not next(c for c in checks if c.name == "citations_valid").passed

    def test_answer_without_citation_fails_by_default(self):
        checks, _ = score_ask(_case("ask"), _outcome(answer="Make a cowl."))
        assert not next(c for c in checks if c.name == "cites_something").passed

    def test_cites_false_allows_refusal(self):
        checks, _ = score_ask(_case("ask", cites=False), _outcome(answer="I can't share instructions."))
        assert all(c.passed for c in checks)

    def test_extraction_is_scored_separately(self):
        case = _case("ask", search_query_terms=["cowl"], filters={"craft": "crochet", "free": True})
        checks, scores = score_ask(case, _outcome(filters={"craft": "Crochet", "free": True}))
        assert scores["extraction_accuracy"] == 1.0
        assert all(c.passed for c in checks)

        _, scores = score_ask(case, _outcome(filters={"craft": "Crochet"}))
        assert scores["extraction_accuracy"] == 0.0

    def test_filters_absent(self):
        checks, _ = score_ask(_case("ask", filters_absent=["difficulty"]), _outcome(filters={"difficulty": "beginner"}))
        assert not next(c for c in checks if c.name == "filters_absent").passed

    def test_forbidden_answer_terms(self):
        case = _case("ask", answer_forbid_terms=["row 1"], cites=False)
        checks, _ = score_ask(case, _outcome(answer="Row 1: knit across."))
        assert not next(c for c in checks if c.name == "answer_forbid_terms").passed

    def test_expect_no_results(self):
        checks, _ = score_ask(_case("ask", expect_no_results=True), _outcome(answer="Nothing found.", patterns=[]))
        assert all(c.passed for c in checks)

    def test_retrieval_is_scored_on_the_cited_shortlist(self):
        case = _ask(retrieval={"terms_any": ["cowl"], "terms_k": 2, "min_term_precision": 1.0})
        patterns = [{"id": 1, "name": "Harbor Cowl"}, {"id": 2, "name": "Dock Hat"}]
        checks, scores = score_ask(case, _outcome(patterns=patterns))
        assert scores["retrieval_term_precision@2"] == 0.5
        assert not next(c for c in checks if c.name == "retrieval_terms_any").passed
        assert "retrieval_zero_result_rate" not in scores

    def test_grounding_only_runs_with_a_context(self):
        _, scores = score_ask(_ask(), _outcome())
        assert "auto_grounded" not in scores

    def test_invented_number_fails_grounding(self):
        context = "[1] Harbor Cowl | difficulty 2.5/10 | Worsted"
        checks, scores = score_ask(_ask(), _outcome(answer="Try [1]; it takes 400 yards.", context=context))
        assert scores["auto_grounded"] == 0.0
        assert "400" in next(c for c in checks if c.name == "numbers_grounded").detail

    def test_named_but_unretrieved_pattern_fails_grounding(self):
        outcome = _outcome(answer="Try [1] or the Very Warm Hat.", context="[1] Harbor Cowl")
        checks, scores = score_ask(_ask(), outcome, known_names=["Very Warm Hat"])
        assert scores["auto_grounded"] == 0.0
        assert not next(c for c in checks if c.name == "names_grounded").passed

    def test_numbers_from_the_question_count_as_grounded(self):
        case = EvalCase(id="a", suite="ask", input={"message": "a hat in 2 colours"}, expect={})
        _, scores = score_ask(case, _outcome(answer="[1] uses 2 colours.", context="[1] Harbor Cowl"))
        assert scores["auto_grounded"] == 1.0

    def test_faithfulness_comes_from_the_judgment(self):
        _, scores = score_ask(_ask(), _outcome())
        assert scores["judged"] == 0.0 and "faithfulness" not in scores

        bad = Judgment("a", "x", "unfaithful", "oversold")
        checks, scores = score_ask(_ask(), _outcome(), judgment=bad)
        assert (scores["judged"], scores["faithfulness"]) == (1.0, 0.0)
        assert "oversold" in next(c for c in checks if c.name == "faithful").detail

    def test_refusal_counts_as_faithful(self):
        _, scores = score_ask(_ask(), _outcome(), judgment=Judgment("a", "x", "refused"))
        assert scores["faithfulness"] == 1.0


class TestGroundingChecks:
    def test_citations_are_not_numbers(self):
        assert unsupported_numbers("See [3] and [1, 2].", "nothing") == []

    def test_number_forms_compare_by_value(self):
        assert unsupported_numbers("rated 2.50/10", "difficulty 2.5/10") == []
        assert unsupported_numbers("rated 3/10, 120 yds", "difficulty 3.0/10") == ["120"]

    def test_names_are_case_sensitive_whole_words(self):
        names = ["Very Warm Hat"]
        assert ungrounded_names("a very warm hat", "", names) == []
        assert ungrounded_names("the Very Warm Hats", "", names) == []
        assert ungrounded_names("the Very Warm Hat.", "", names) == ["Very Warm Hat"]
        assert ungrounded_names("the Very Warm Hat.", "[1] VERY WARM HAT", names) == []


class TestAskDataset:
    def test_retrieval_expectation_is_validated(self, tmp_path):
        base = {"id": "a1", "suite": "ask", "input": {"message": "hat"}}
        ok = {**base, "expect": {"retrieval": {"terms_any": ["hat"], "terms_k": 3}}}
        assert load_dataset(_write(tmp_path, [ok]), "ask").cases[0].expect["retrieval"]["terms_k"] == 3
        for bad in ({}, {"terms_any": ["hat"], "cites": False}, {"terms_any": "hat"}):
            with pytest.raises(DatasetError):
                load_dataset(_write(tmp_path, [{**base, "expect": {"retrieval": bad}}]), "ask")

    def test_shipped_ask_set_is_sized_and_judged(self):
        cases = load_dataset(DATASETS_DIR / "ask.jsonl", "ask").cases
        assert 25 <= len(cases) <= 40
        judged = {case for case, _ in load_judgments(JUDGMENTS_PATH)}
        assert judged <= {c.id for c in cases}


class TestJudgments:
    def test_sha_ignores_surrounding_whitespace(self):
        assert answer_sha(" Try [1].\n") == answer_sha("Try [1].")
        assert len(answer_sha("x")) == 12

    def test_load(self, tmp_path):
        path = tmp_path / "j.jsonl"
        path.write_text(
            "// comment\n" + json.dumps({"case": "a", "answer_sha": "abc", "verdict": "refused"}) + "\n",
            encoding="utf-8",
        )
        judgment = load_judgments(path)[("a", "abc")]
        assert judgment.faithful and judgment.note == ""
        assert load_judgments(tmp_path / "missing.jsonl") == {}

    @pytest.mark.parametrize(
        "line",
        [
            {"case": "a", "answer_sha": "x", "verdict": "fine"},
            {"case": "a", "verdict": "faithful"},
            {"case": "a", "answer_sha": "x", "verdict": "faithful", "score": 1},
            "{not json",
        ],
    )
    def test_bad_lines_are_rejected(self, tmp_path, line):
        path = tmp_path / "j.jsonl"
        path.write_text(line if isinstance(line, str) else json.dumps(line), encoding="utf-8")
        with pytest.raises(DatasetError):
            load_judgments(path)

    def test_duplicates_are_rejected(self, tmp_path):
        line = json.dumps({"case": "a", "answer_sha": "x", "verdict": "faithful"})
        path = tmp_path / "j.jsonl"
        path.write_text(f"{line}\n{line}\n", encoding="utf-8")
        with pytest.raises(DatasetError):
            load_judgments(path)


MSGS = [{"role": "user", "content": "a hat"}]


def _complete(recorder, messages=MSGS, **overrides):
    params = {"max_tokens": 50, "temperature": 0.0, "json_mode": False, **overrides}
    return recorder.complete(_live, messages, **params)


async def _live(messages, **_):
    _live.calls += 1
    return f"live reply to {messages[-1]['content']}"


class TestCompletionRecorder:
    @pytest.fixture(autouse=True)
    def _reset(self):
        _live.calls = 0

    def test_key_covers_everything_that_changes_the_reply(self):
        base = request_key("m", MSGS, max_tokens=50, temperature=0.0, json_mode=False)
        assert base == request_key("m", list(MSGS), max_tokens=50, temperature=0.0, json_mode=False)
        assert base != request_key("m2", MSGS, max_tokens=50, temperature=0.0, json_mode=False)
        assert base != request_key("m", MSGS, max_tokens=50, temperature=0.3, json_mode=False)
        assert base != request_key("m", MSGS, max_tokens=50, temperature=0.0, json_mode=True)
        assert base != request_key("m", [{"role": "user", "content": "a hat!"}], max_tokens=50, temperature=0.0, json_mode=False)

    @pytest.mark.asyncio
    async def test_record_then_replay(self, tmp_path):
        path = tmp_path / "llm.jsonl"
        recorder = CompletionRecorder(path, "record", "m")
        recorder.start_case("c1")
        assert await _complete(recorder) == "live reply to a hat"
        assert recorder.save() == 1

        replay = CompletionRecorder(path, "replay", "m")
        replay.start_case("c1")
        assert await _complete(replay) == "live reply to a hat"
        assert _live.calls == 1 and replay.hits == 1

    @pytest.mark.asyncio
    async def test_replay_miss_raises_instead_of_degrading(self, tmp_path):
        from app.services.llm_service import LLMUnavailableError

        replay = CompletionRecorder(tmp_path / "none.jsonl", "replay", "m")
        with pytest.raises(FixtureMissing) as raised:
            await _complete(replay)
        assert not isinstance(raised.value, LLMUnavailableError)
        assert replay.misses == 1 and _live.calls == 0

    @pytest.mark.asyncio
    async def test_record_reuses_unchanged_prompts(self, tmp_path):
        path = tmp_path / "llm.jsonl"
        first = CompletionRecorder(path, "record", "m")
        first.start_case("c1")
        await _complete(first)
        first.save()

        second = CompletionRecorder(path, "record", "m")
        second.start_case("c1")
        await _complete(second)
        await _complete(second, messages=[{"role": "user", "content": "a scarf"}])
        assert (second.hits, second.calls, _live.calls) == (1, 1, 2)

    @pytest.mark.asyncio
    async def test_save_drops_stale_entries_only_for_cases_that_ran(self, tmp_path):
        path = tmp_path / "llm.jsonl"
        first = CompletionRecorder(path, "record", "m")
        for case, content in (("c1", "old prompt"), ("c2", "other case")):
            first.start_case(case)
            await _complete(first, messages=[{"role": "user", "content": content}])
        first.save()

        second = CompletionRecorder(path, "record", "m")
        second.start_case("c1")
        await _complete(second, messages=[{"role": "user", "content": "new prompt"}])
        assert second.save() == 2
        saved = {json.loads(l)["response"] for l in path.read_text().splitlines()}
        assert saved == {"live reply to new prompt", "live reply to other case"}

    @pytest.mark.asyncio
    async def test_live_saves_nothing(self, tmp_path):
        recorder = CompletionRecorder(tmp_path / "llm.jsonl", "live", "m")
        await _complete(recorder)
        await _complete(recorder)
        assert _live.calls == 2 and recorder.entries == {}

    @pytest.mark.asyncio
    async def test_installed_swaps_and_restores_the_client(self, tmp_path):
        from app.services import llm_service

        original = llm_service._complete
        recorder = CompletionRecorder(tmp_path / "none.jsonl", "replay", "m")
        with recorder.installed():
            assert llm_service._complete is not original
            with pytest.raises(FixtureMissing):
                await llm_service._complete(MSGS, max_tokens=5, temperature=0.0, json_mode=False)
        assert llm_service._complete is original

    def test_unknown_mode_is_rejected(self, tmp_path):
        with pytest.raises(ValueError):
            CompletionRecorder(tmp_path / "x.jsonl", "cache")


class TestAskAvailability:
    def test_replay_needs_fixtures_not_a_key(self, tmp_path):
        fixtures = tmp_path / "llm.jsonl"
        assert "record" in ask_unavailable("replay", False, fixtures)
        fixtures.write_text("", encoding="utf-8")
        assert ask_unavailable("replay", False, fixtures) is None

    @pytest.mark.parametrize("mode", ["record", "live"])
    def test_record_and_live_need_a_key(self, tmp_path, mode):
        assert "OPENAI_API_KEY" in ask_unavailable(mode, False, tmp_path / "x")
        assert ask_unavailable(mode, True, tmp_path / "x") is None

    def test_llm_flag_defaults_to_replay(self):
        assert parse_args([]).llm == "replay"
        assert parse_args(["--suite", "ask", "--llm", "record"]).llm == "record"
        with pytest.raises(SystemExit):
            parse_args(["--llm", "cache"])


class FakeTarget:
    suite = "search"
    variant = "production"

    def __init__(self, outcomes: dict):
        self.outcomes = outcomes

    def warm_up(self):
        pass

    def skip_reason(self, case):
        return "not seeded" if self.outcomes[case.id] == "skip" else None

    def run(self, case):
        outcome = self.outcomes[case.id]
        if isinstance(outcome, Exception):
            raise outcome
        return Observation(latency_ms=10, results=outcome)

    def score(self, case, observation):
        return score_ranked(case, observation.results)

    def summarize(self, observation):
        return {}


def _cases(*ids) -> list[EvalCase]:
    return [EvalCase(id=i, suite="search", input={"query": "q"}, expect={"terms_any": ["hat"], "terms_k": 1}, tags=("intent",)) for i in ids]


class TestRunner:
    @pytest.mark.asyncio
    async def test_statuses_and_summary(self):
        target = FakeTarget(
            {
                "pass": [_row(1, "Hat")],
                "fail": [_row(1, "Scarf")],
                "error": RuntimeError("db down"),
                "skip": "skip",
            }
        )
        rollbacks = []
        results = await run_cases(target, _cases("pass", "fail", "error", "skip"), rollback=lambda: rollbacks.append(1))

        assert [r.status for r in results] == [PASS, FAIL, ERROR, SKIP]
        assert "db down" in results[2].detail
        assert len(rollbacks) == 4

        summary = summarize(results)
        # Errors count against the pass rate; skips do not.
        assert summary["pass_rate"] == pytest.approx(1 / 3)
        assert summary["metrics"]["term_precision@1"] == {"mean": 0.5, "n": 2}
        assert summary["pass_rate_by_tag"]["intent"] == pytest.approx(1 / 3)
        assert summary["latency_ms"]["p50"] == 10

    @pytest.mark.asyncio
    async def test_async_targets_are_awaited(self):
        class AsyncTarget(FakeTarget):
            async def run(self, case):
                return Observation(latency_ms=5, results=[_row(1, "Hat")])

        results = await run_cases(AsyncTarget({"a": None}), _cases("a"))
        assert results[0].status == PASS

    def test_floors(self):
        summary = {
            "pass_rate": 0.5,
            "metrics": {"ndcg@10": {"mean": 0.8, "n": 3}},
            "latency_ms": {"p50": 100, "p95": 900},
        }
        breaches = check_floors(summary, {"pass_rate": 0.6, "ndcg@10": 0.7, "latency_p95_ms": 500, "mrr": 0.5})
        assert breaches == ["pass_rate 0.500 < floor 0.6", "latency_p95_ms 900 > ceiling 500"]

    @pytest.mark.asyncio
    async def test_render_lists_failures(self):
        target = FakeTarget({"pass": [_row(1, "Hat")], "fail": [_row(1, "Scarf")]})
        results = await run_cases(target, _cases("pass", "fail"))
        summary = summarize(results)
        text = render(SuiteReport("search", "production", results, summary, {"pass_rate": 0.9}, ["pass_rate 0.500 < floor 0.9"]))
        assert "FAIL  fail" in text
        assert "PASS  pass" not in text
        assert "FLOOR BREACHED" in text

    def test_load_floors_drops_nulls_and_unknown_suites(self, tmp_path):
        path = tmp_path / "t.json"
        path.write_text(json.dumps({"search": {"pass_rate": 0.5, "mrr": None}, "_note": {}}), encoding="utf-8")
        assert load_floors(path) == {"search": {"pass_rate": 0.5}}

    def test_check_is_a_plain_record(self):
        assert Check("x", True).detail == ""

    def test_enforce_floors_flag(self):
        assert parse_args(["--suite", "search", "--variant", "vector", "--enforce-floors"]).enforce_floors
        assert not parse_args([]).enforce_floors

    def test_shipped_search_floors_include_ranking(self):
        assert {"ndcg@10", "candidate_recall@60"} <= set(load_floors(THRESHOLDS_PATH)["search"])

    def test_shipped_ask_floors_cover_all_three_stages(self):
        assert {"extraction_accuracy", "citation_validity", "faithfulness", "judged"} <= set(load_floors(THRESHOLDS_PATH)["ask"])


class TestPipelineCandidates:
    @pytest.fixture
    def pipeline(self, monkeypatch):
        from app.search import pipeline

        monkeypatch.setattr(pipeline.reranking_service, "rerank", lambda q, c, top_n: list(reversed(c))[:top_n])
        return pipeline

    class _DB:
        def query(self, *_):
            return self

        def filter(self, *_):
            return self

        def scalar(self):
            return 1

    def test_candidates_are_pre_rerank_order(self, pipeline, monkeypatch):
        rows = [{"id": 1}, {"id": 2}, {"id": 3}]
        monkeypatch.setattr(pipeline, "hybrid_search", lambda *a, **k: (rows, "hybrid"))
        envelope = pipeline.search(self._DB(), "hat", include_candidates=True)
        assert envelope["candidate_ids"] == [1, 2, 3]
        assert [r["id"] for r in envelope["results"]] == [3, 2, 1]

    def test_candidates_off_by_default_and_on_empty(self, pipeline, monkeypatch):
        monkeypatch.setattr(pipeline, "hybrid_search", lambda *a, **k: ([{"id": 1}], "hybrid"))
        assert "candidate_ids" not in pipeline.search(self._DB(), "hat")
        monkeypatch.setattr(pipeline, "hybrid_search", lambda *a, **k: ([], "semantic"))
        assert pipeline.search(self._DB(), "hat", include_candidates=True)["candidate_ids"] == []
