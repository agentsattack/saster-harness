"""W6 pre-sweep canary — benign-completion baseline for the content-filter /
empty-response rate."""
from __future__ import annotations

import json

import pytest

from saster_harness.canary import (
    BENIGN_PROMPTS,
    CanaryResult,
    TurnClass,
    canary_manifest_block,
    classify_turn,
    run_canary,
    run_canary_suite,
)


class FakeResponse:
    def __init__(self, text, raw=None):
        self.text = text
        self.raw = raw


class FakeRouted:
    def __init__(self, text=None, raw=None, error=None, response=True):
        self.response = FakeResponse(text, raw) if response else None
        self.error = error


class FakeRouter:
    """Router-shaped stub returning a scripted sequence of RoutedResults."""

    def __init__(self, scripted):
        self._scripted = list(scripted)
        self.calls = []

    def generate(self, *, run_id, challenge_id, step_index, messages, params):
        self.calls.append((run_id, challenge_id, step_index, messages))
        return self._scripted[min(step_index, len(self._scripted) - 1)]


def ok(n=1):
    return [FakeRouted(text="a normal answer") for _ in range(n)]


def blank(n=1):
    return [FakeRouted(text="") for _ in range(n)]


# --------------------------------------------------------------------------
# turn classification
# --------------------------------------------------------------------------


def test_normal_text_classifies_ok():
    assert classify_turn("here are the steps") is TurnClass.OK


def test_empty_string_classifies_filtered_or_empty():
    assert classify_turn("") is TurnClass.FILTERED_OR_EMPTY


def test_whitespace_only_classifies_filtered_or_empty():
    assert classify_turn("   \n\t ") is TurnClass.FILTERED_OR_EMPTY


def test_none_classifies_filtered_or_empty():
    assert classify_turn(None) is TurnClass.FILTERED_OR_EMPTY


def test_content_filter_finish_reason_classifies_filtered():
    raw = {"choices": [{"finish_reason": "content_filter"}]}
    assert classify_turn("some text", raw) is TurnClass.FILTERED_OR_EMPTY


def test_content_filter_finish_reason_is_case_insensitive():
    raw = {"choices": [{"finish_reason": "CONTENT_FILTER"}]}
    assert classify_turn("some text", raw) is TurnClass.FILTERED_OR_EMPTY


def test_stop_finish_reason_with_text_is_ok():
    raw = {"choices": [{"finish_reason": "stop"}]}
    assert classify_turn("an answer", raw) is TurnClass.OK


def test_malformed_raw_payload_does_not_crash_classification():
    assert classify_turn("an answer", {"choices": ["not-a-dict"]}) is TurnClass.OK


def test_raw_none_falls_back_to_text_check():
    assert classify_turn("", None) is TurnClass.FILTERED_OR_EMPTY


def test_turn_class_filtered_matches_the_schema_class_name():
    """The canary's class name is the schema's terminal-outcome class."""
    from carl_ops_trajectory import TERMINAL_OUTCOMES

    assert TurnClass.FILTERED_OR_EMPTY.value in TERMINAL_OUTCOMES


# --------------------------------------------------------------------------
# running the canary
# --------------------------------------------------------------------------


def test_all_clean_gives_zero_filter_rate():
    router = FakeRouter(ok(5))
    result = run_canary(router, "m", 5)
    assert result.filtered_or_empty_rate == 0.0
    assert result.ok == 5


def test_all_blank_gives_full_filter_rate():
    router = FakeRouter(blank(4))
    result = run_canary(router, "m", 4)
    assert result.filtered_or_empty_rate == 1.0


def test_mixed_gives_the_right_fraction():
    router = FakeRouter([*ok(1), *blank(1), *ok(1), *blank(1)])
    result = run_canary(router, "m", 4)
    assert result.filtered_or_empty == 2
    assert result.filtered_or_empty_rate == 0.5


def test_n_attempted_counts_every_turn():
    router = FakeRouter(ok(3))
    assert run_canary(router, "m", 3).n_attempted == 3


def test_prompts_cycle_when_n_exceeds_the_corpus():
    router = FakeRouter(ok(1))
    n = len(BENIGN_PROMPTS) + 3
    result = run_canary(router, "m", n)
    assert result.n_attempted == n
    assert len(router.calls) == n


def test_a_filtered_turn_is_not_an_error():
    router = FakeRouter(blank(3))
    result = run_canary(router, "m", 3)
    assert result.errors == 0


def test_a_filtered_turn_does_not_raise():
    """The whole point: a filtered turn is an observation, never a failure."""
    router = FakeRouter(blank(3))
    run_canary(router, "m", 3)  # must not raise


def test_transport_errors_are_counted_separately():
    router = FakeRouter([FakeRouted(response=False, error="transport error")])
    result = run_canary(router, "m", 1)
    assert result.errors == 1
    assert result.filtered_or_empty == 0


def test_errors_are_excluded_from_the_rate_denominator():
    """An unreachable backend must not look like a filtering one."""
    router = FakeRouter([*ok(1), FakeRouted(response=False, error="boom")])
    result = run_canary(router, "m", 2)
    assert result.completed == 1
    assert result.filtered_or_empty_rate == 0.0


def test_error_detail_is_retained():
    router = FakeRouter([FakeRouted(response=False, error="HTTP 500")])
    result = run_canary(router, "m", 1)
    assert "HTTP 500" in result.error_detail[0]


def test_canary_uses_a_per_model_challenge_id():
    router = FakeRouter(ok(1))
    run_canary(router, "qwen", 1)
    assert router.calls[0][1] == "canary::qwen"


def test_empty_prompt_pool_is_rejected():
    with pytest.raises(ValueError):
        run_canary(FakeRouter(ok(1)), "m", 1, prompts=[])


def test_custom_prompts_are_used():
    router = FakeRouter(ok(2))
    run_canary(router, "m", 2, prompts=["only this one"])
    assert router.calls[0][3][0]["content"] == "only this one"


# --------------------------------------------------------------------------
# measured vs assumed
# --------------------------------------------------------------------------


def test_a_run_with_no_completed_turns_is_not_measured():
    router = FakeRouter([FakeRouted(response=False, error="down")])
    result = run_canary(router, "m", 1)
    assert result.measured is False


def test_an_unmeasured_run_must_not_be_read_as_a_clean_zero():
    """The distinction the flag exists for: rate is 0.0 either way, so the
    flag is the only thing separating 'measured zero' from 'measured
    nothing'."""
    down = run_canary(FakeRouter([FakeRouted(response=False, error="down")]), "m", 1)
    clean = run_canary(FakeRouter(ok(3)), "m", 3)
    assert down.filtered_or_empty_rate == clean.filtered_or_empty_rate == 0.0
    assert down.measured is False and clean.measured is True


def test_a_run_with_completed_turns_is_measured():
    assert run_canary(FakeRouter(ok(2)), "m", 2).measured is True


def test_empty_result_rate_is_zero_and_unmeasured():
    r = CanaryResult(model="m")
    assert r.filtered_or_empty_rate == 0.0
    assert r.measured is False


# --------------------------------------------------------------------------
# suite and manifest
# --------------------------------------------------------------------------


def test_suite_runs_every_model():
    def factory(model, campaign_id):
        return FakeRouter(ok(2))

    results = run_canary_suite(["qwen", "ministral"], 2, router_factory=factory)
    assert set(results) == {"qwen", "ministral"}


def test_suite_pins_each_model_to_its_own_campaign_id():
    seen = []

    def factory(model, campaign_id):
        seen.append(campaign_id)
        return FakeRouter(ok(1))

    run_canary_suite(["qwen", "ministral"], 1, router_factory=factory)
    assert seen == ["canary::qwen", "canary::ministral"]


def test_suite_reports_per_model_rates_independently():
    def factory(model, campaign_id):
        return FakeRouter(blank(2) if model == "bad" else ok(2))

    results = run_canary_suite(["good", "bad"], 2, router_factory=factory)
    assert results["good"].filtered_or_empty_rate == 0.0
    assert results["bad"].filtered_or_empty_rate == 1.0


def test_manifest_block_carries_every_model():
    def factory(model, campaign_id):
        return FakeRouter(ok(1))

    results = run_canary_suite(["a", "b"], 1, router_factory=factory)
    block = canary_manifest_block(results)
    assert set(block["per_model"]) == {"a", "b"}


def test_manifest_block_flags_an_unmeasured_model():
    def factory(model, campaign_id):
        if model == "down":
            return FakeRouter([FakeRouted(response=False, error="x")])
        return FakeRouter(ok(1))

    results = run_canary_suite(["up", "down"], 1, router_factory=factory)
    assert canary_manifest_block(results)["all_measured"] is False


def test_manifest_block_all_measured_when_every_model_completed():
    def factory(model, campaign_id):
        return FakeRouter(ok(1))

    results = run_canary_suite(["a", "b"], 1, router_factory=factory)
    assert canary_manifest_block(results)["all_measured"] is True


def test_manifest_block_of_no_models_is_not_all_measured():
    assert canary_manifest_block({})["all_measured"] is False


def test_manifest_block_is_json_serializable():
    def factory(model, campaign_id):
        return FakeRouter(ok(1))

    results = run_canary_suite(["a"], 1, router_factory=factory)
    json.dumps(canary_manifest_block(results))
