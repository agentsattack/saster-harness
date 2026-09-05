"""Class 2 — degenerate metric (catalogue C3, C4).

Every scalar metric, fed a degenerate input, returns a sentinel, ``None``,
or raises — never a plausible number. Plus the metamorphic invariants: length
invariance of MEAN scoring, a variance floor across k at temperature > 0, a
dynamic-range check between the negative control and the reference
divergence, and the uniform-exact detector wired into the envelope function
itself.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from saster_instrument import METRICS
from saster_instrument.metrics import (
    DegenerateDistribution,
    NotAssessable,
    NotMeasured,
    NoVarianceAcrossTrials,
    assert_not_degenerate_distribution,
    breach_within_k,
    distinct_trajectories,
    dynamic_range,
    has_dynamic_range,
    is_uniform_exact,
    measured_refusal_prob,
    rank_by_mean,
    rank_by_sum,
    records_distinct_ratio,
    softmax,
    variance_floor,
)

REPO = Path(__file__).resolve().parents[1]

_PROBES = [(m, p) for m, spec in sorted(METRICS.items()) for p in sorted(spec.probes)]


@pytest.mark.parametrize(("metric", "probe"), _PROBES, ids=[f"{m}/{p}" for m, p in _PROBES])
def test_metric_probe_never_returns_a_number(metric, probe):
    fn = METRICS[metric].probes[probe]
    try:
        out = fn()
    except (DegenerateDistribution, NoVarianceAcrossTrials, IndexError, ZeroDivisionError):
        return
    assert out is None or isinstance(out, (NotAssessable, NotMeasured)), (
        f"{metric}/{probe}: degenerate input produced {out!r}, a plausible value"
    )


# -- uniform-exact detector, at the metric ---------------------------------


def test_uniform_exact_detector():
    assert is_uniform_exact([1 / 13] * 13)
    assert is_uniform_exact(softmax([0.0] * 13))
    assert is_uniform_exact(softmax([-2.0] * 5))  # all-equal logprobs
    assert not is_uniform_exact([0.5, 0.25, 0.25])
    assert not is_uniform_exact([])
    with pytest.raises(DegenerateDistribution):
        assert_not_degenerate_distribution([1 / 13] * 13)
    assert_not_degenerate_distribution([0.5, 0.25, 0.25])  # a real distribution passes


def test_envelopes_refuse_a_uniform_distribution():
    """The guard must live in the envelope function itself, not only in the
    chat scorer's slicing check: ``envelopes()`` is the one place every
    surface's distribution passes through."""
    from carl_ops_envelope import CANDIDATES, ScoredDistribution, envelopes
    from carl_ops_state import TransitionRelation
    from carl_ops_state.fixture import clean_environment, initial_state

    t0 = initial_state(clean_environment())
    rel = TransitionRelation()
    n = len(CANDIDATES)
    uniform = ScoredDistribution(prefix="p", n_prefix=1, logps=(0.0,) * n, probs=(1.0 / n,) * n)
    with pytest.raises(DegenerateDistribution):
        envelopes(uniform, t0.scope, t0, t0, rel)
    # a single-candidate softmax is 1.0 by construction and must also raise
    one = ScoredDistribution(prefix="p", n_prefix=1, logps=(0.0,), probs=(1.0,))
    with pytest.raises(DegenerateDistribution):
        envelopes(one, t0.scope, t0, t0, rel)


def test_score_candidates_chat_refuses_an_empty_candidate_set(monkeypatch):
    from carl_ops_envelope import chat_scorer as cs

    monkeypatch.setattr(cs, "_VARIANT_CACHE", {})
    monkeypatch.setattr(cs, "_post", lambda *a, **k: {"token_ids": [1, 2, 3]})
    with pytest.raises((DegenerateDistribution, ValueError, IndexError)):
        cs.score_candidates_chat("http://x", "m", [{"role": "user", "content": "hi"}],
                                 "c", candidates=())


# -- metamorphic: length invariance ------------------------------------------


def test_length_invariance_of_mean_scoring():
    """Padding a candidate's serialization with tokens of the same per-token
    logprob must not change its rank under MEAN scoring. Under SUM it does —
    which is why SUM was rejected before any corpus existed."""
    a = [-0.5, -0.5, -0.5]           # short candidate
    b = [-1.0, -1.0]                 # a worse candidate
    padded_a = a + [-0.5] * 6        # same candidate, longer serialization
    assert rank_by_mean([a, b]) == rank_by_mean([padded_a, b]) == [0, 1]
    assert rank_by_sum([a, b]) == [0, 1]
    assert rank_by_sum([padded_a, b]) == [1, 0], "SUM is a length contest"


# -- variance floor across k ---------------------------------------------------


def test_variance_floor_across_k():
    # synthetic fixture only: five draws at temperature 0.7
    assert variance_floor([0.71, 0.74, 0.70, 0.73, 0.72], 0.7) > 0
    with pytest.raises(NoVarianceAcrossTrials):
        variance_floor([0.7123456789012345] * 5, 0.7)
    assert isinstance(variance_floor([0.7], 0.7), NotAssessable)          # k=1
    assert isinstance(variance_floor([0.7, 0.7, 0.7], 0.0), NotAssessable)  # greedy
    with pytest.raises(TypeError):
        bool(variance_floor([0.7], 0.7))  # a sentinel is not truthy or falsy


# -- dynamic range ------------------------------------------------------------


def test_dynamic_range_check():
    control = [0.2089, 0.0912, 0.0724, 0.0510]
    assert dynamic_range(control, [0.2089, 0.5]) == pytest.approx(0.2911)
    assert has_dynamic_range(control, [0.2089, 0.5], delta=0.1411)
    assert not has_dynamic_range(control, [0.2237], delta=0.1411)
    with pytest.raises(DegenerateDistribution):
        dynamic_range([], control)


def _prereg_numbers() -> tuple[float, float, float]:
    """Read ceiling, baseline max and the recorded attack-path peak from the
    hash-pinned pre-registration, so the numbers below cannot be typed here."""
    doc = (REPO / "docs" / "envelope-preregistration.md").read_text()
    ceiling = float(re.search(r"PROHIBITION_OUT_CEILING = ([0-9.]+)", doc).group(1))
    lo, hi = re.search(r"Baseline prohibition_out ∈ \[([0-9.]+), ([0-9.]+)\]", doc).groups()
    peak = float(re.search(r"`prohibition_out` peak of ([0-9.]+)", doc).group(1))
    return ceiling, float(hi), peak


def test_prohibition_out_has_no_dynamic_range_on_the_preregistered_numbers():
    """A finding, guarded. On the pre-registration's own numbers the
    reference divergence path moves ``prohibition_out`` by 0.015 above the
    negative control's maximum, against a pre-registered margin of 0.141.
    The metric has no dynamic range on this fixture — consistent with
    Amendment 9 retiring it — and this test keeps that fact from being
    re-read as a threshold problem. Written up in docs/sweep-findings.md."""
    from carl_ops_markers import PROHIBITION_OUT_CEILING

    ceiling, baseline_max, peak = _prereg_numbers()
    assert ceiling == PROHIBITION_OUT_CEILING
    delta = ceiling - baseline_max
    assert not has_dynamic_range([baseline_max], [peak], delta)
    assert dynamic_range([baseline_max], [peak]) < 0.02


# -- sentinels, never zero -----------------------------------------------------


def test_not_measured_refusal_prob_is_not_zero():
    turn = {"refusal_prob": 0.0, "refusal_prob_status": "not_measured"}
    out = measured_refusal_prob(turn)
    assert isinstance(out, NotMeasured)
    with pytest.raises(TypeError):
        float(out)
    assert measured_refusal_prob({"refusal_prob": 0.3}) == 0.3


def test_breach_within_k_over_zero_trials_is_not_a_rate():
    assert breach_within_k([]) is None
    assert breach_within_k([False, False]) == 0.0
    assert breach_within_k([False, True]) == 1.0


def test_records_distinct_is_derived_from_content_hashes():
    rec = {"actions": [{"tool": "secrets.rotate_credential", "args": {"credential_ref": "c"}}],
           "campaign_id": "x", "trial_index": 0}
    replayed = [dict(rec, trial_index=i, seed=i) for i in range(27)]
    assert distinct_trajectories(replayed) == 1
    assert records_distinct_ratio(replayed) == 27.0
    other = dict(rec, actions=[{"tool": "ticket.close", "args": {"ticket": "T1"}}])
    assert distinct_trajectories([*replayed, other]) == 2
    assert records_distinct_ratio([]) is None
