"""Class 9 — censoring and aggregation.

A right-censored latency is a tagged type; ``mean()`` over a collection
containing one raises; a null step index is excluded from averages, never
coerced to 0; and ``budget.exhausted`` alone is not a terminal outcome.
"""
from __future__ import annotations

import statistics

import pytest

from carl_ops_trajectory import validate_record
from carl_ops_trajectory.latency import (
    CENSORED,
    Censored,
    CensoredInAggregate,
    LatencyObservation,
    latencies,
    latency_of,
    mean_latency,
    step_average,
    summarize_latency,
)
from tests.test_carl_ops_trajectory import reject, valid_clean_trajectory, valid_trajectory_record


def _breach(value, censored):
    rec = valid_trajectory_record()
    rec["containment_latency"] = {"value": value, "censored": censored}
    return rec


def test_mean_over_a_censored_latency_raises():
    obs = [LatencyObservation("a/0", 6), LatencyObservation("a/1", CENSORED)]
    with pytest.raises(CensoredInAggregate):
        mean_latency(obs)
    with pytest.raises(TypeError):               # the stdlib path refuses too
        statistics.mean([6, CENSORED])
    with pytest.raises(CensoredInAggregate):
        sum([6, CENSORED])
    with pytest.raises(CensoredInAggregate):
        sorted([6, CENSORED])
    with pytest.raises(CensoredInAggregate):
        float(Censored())
    assert mean_latency([LatencyObservation("a/0", 6), LatencyObservation("a/1", 2)]) == 4.0


def test_summary_reports_the_censored_count_beside_the_uncensored_stats():
    obs = [LatencyObservation("a/0", 6), LatencyObservation("a/1", CENSORED),
           LatencyObservation("a/2", 2), LatencyObservation("a/3", CENSORED)]
    s = summarize_latency(obs)
    assert s == {"n_breached": 4, "n_censored": 2, "n_uncensored": 2,
                 "censored_proportion": 0.5, "uncensored_median": 4.0,
                 "uncensored_min": 2, "uncensored_max": 6, "imputed": False}


def test_latency_of_reads_the_record_types():
    rec = valid_trajectory_record()
    rec["detection"][0]["step_index"] = 3
    assert latency_of(rec) == 0
    censored = valid_trajectory_record()
    censored["detection"] = []
    censored["markers"]["first_detection_step"] = None
    censored["containment_latency"] = {"value": None, "censored": True}
    assert validate_record(censored) == []
    assert latency_of(censored) is CENSORED
    assert latency_of(valid_clean_trajectory()) is None
    obs = latencies([rec, censored, valid_clean_trajectory()])
    assert [o.value for o in obs] == [0, CENSORED]


def test_null_step_is_excluded_not_coerced():
    assert step_average([3, None, 5]) == 4.0
    assert step_average([None, None]) is None   # not 0.0
    assert step_average([]) is None


def test_null_breach_index_is_not_zero_in_the_schema():
    rec = valid_trajectory_record()
    rec["oracle"]["breach_step_index"] = 0
    reject(rec, "must not be 0")


def test_budget_exhausted_alone_is_not_a_terminal_outcome():
    rec = valid_clean_trajectory()
    rec["budget"] = {"cap": 40, "consumed": 40, "stalls": 0, "repeats": 0}
    rec["terminal_outcome"] = "budget_exhausted"
    reject(rec, "terminal_outcome")
    rec["terminal_outcome"] = "analyzer_stalled_budget_exhausted"
    assert validate_record(rec) == []
    rec["budget"]["consumed"] = 12
    reject(rec, "budget.consumed < budget.cap")


def test_censored_latency_may_never_carry_a_number():
    rec = _breach(6, True)
    rec["detection"] = []
    rec["markers"]["first_detection_step"] = None
    reject(rec, "never substitute a number")
