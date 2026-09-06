"""Class 1 — silent default (catalogue C1, C2).

Every wrapper, against every row of the degenerate-input matrix: the output
is ``unavailable`` or ``error``, never the clean class, never a default, and
never a verdict fabricated from garbage. ``unavailable`` and ``error`` are
distinct from each other and from ``allow``. A policy-engine wrapper failure
records ``policy_verdict: unavailable`` and CVR counts it in neither the
numerator nor the denominator.

The rows and adapters come from the registry (``saster_instrument``); this
file asserts, it does not enumerate. A row a wrapper cannot be fed is skipped
WITH its declared reason, so the skip is visible in the report.
"""
from __future__ import annotations

import pytest

from saster_defense import ActionRequest, ClassifierGuard, DefenseConfig, DefenseStack
from saster_defense.types import LayerOutcome, Verdict
from saster_harness.canary import CanaryResult
from saster_instrument import DEGENERATE_ROWS, WRAPPERS
from saster_instrument.degenerate import (
    OVER_WINDOW_RECORDS,
    TYPED_ERROR,
    RowNotApplicable,
)
from saster_instrument.metrics import cvr, cvr_rate, policy_verdict_of

_MATRIX = [
    (name, row)
    for name, spec in sorted(WRAPPERS.items())
    if spec.degenerate is not None
    for row in DEGENERATE_ROWS
]


def _assert_not_clean(name: str, row: str, result) -> None:
    spec = WRAPPERS[name]
    if isinstance(result, LayerOutcome):
        assert result.verdict in (Verdict.UNAVAILABLE, Verdict.ERROR), (
            f"{name}/{row}: verdict {result.verdict.value!r} from a degenerate input; "
            f"must be unavailable or error, never {spec.clean_values} or a fabricated "
            f"decision ({result.detail[:120]!r})"
        )
        if result.verdict is Verdict.UNAVAILABLE:
            assert result.ran is False, f"{name}/{row}: unavailable but ran=True"
        assert result.verdict.value not in spec.clean_values
    elif isinstance(result, CanaryResult):
        assert result.ok == 0, f"{name}/{row}: degenerate turn counted as ok"
        assert result.errors + result.filtered_or_empty == 1, result.as_dict()
    elif isinstance(result, tuple) and result and isinstance(result[0], Verdict):
        # a text-classifier client: (verdict, rule_id, detail, raw)
        assert result[0] in (Verdict.UNAVAILABLE, Verdict.ERROR), (
            f"{name}/{row}: verdict {result[0].value!r} from a degenerate reply ({result[2][:120]!r})"
        )
        assert result[0].value not in spec.clean_values
    else:
        # bare clients: a typed error, never a value the layer would trust
        assert result == TYPED_ERROR, (
            f"{name}/{row}: expected a typed backend error, got {result!r}"
        )


@pytest.mark.parametrize(("name", "row"), _MATRIX, ids=[f"{n}/{r}" for n, r in _MATRIX])
def test_degenerate_input_never_clean(monkeypatch, name, row):
    run, patches = WRAPPERS[name].degenerate(row)
    if isinstance(run, RowNotApplicable):
        pytest.skip(f"{name}/{row}: not applicable — {run.reason}")
    for target, attr, replacement in patches:
        monkeypatch.setattr(target, attr, replacement)
    _assert_not_clean(name, row, run())


# -- vocabulary: the three non-clean states stay distinct ----------------------


def test_unavailable_error_and_allow_are_distinct():
    assert len({Verdict.UNAVAILABLE, Verdict.ERROR, Verdict.ALLOW}) == 3
    assert policy_verdict_of(LayerOutcome(_l2(), Verdict.UNAVAILABLE, ran=False)) == "unavailable"
    assert policy_verdict_of(LayerOutcome(_l2(), Verdict.ERROR, ran=True)) == "error"
    assert policy_verdict_of(LayerOutcome(_l2(), Verdict.ALLOW, ran=True)) == "allow"
    assert policy_verdict_of(None) == "unavailable"


def _l2():
    from saster_defense.types import LayerName

    return LayerName.L2_POLICY


def test_policy_verdict_of_wrapper_failure_is_unavailable():
    """A wrapper failure is ``unavailable`` on the record, and CVR excludes it
    from both numerator and denominator."""
    from saster_defense.types import LayerName

    failed = LayerOutcome(LayerName.L2_POLICY, Verdict.UNAVAILABLE, ran=False)
    assert policy_verdict_of(failed) == "unavailable"
    # an outcome whose verdict is out of the policy vocabulary is an error,
    # and also excluded
    odd = LayerOutcome(LayerName.L2_POLICY, Verdict.WARN, ran=True)
    assert policy_verdict_of(odd) == "error"
    actions = [
        {"policy_verdict": "deny"},
        {"policy_verdict": "allow"},
        {"policy_verdict": "unavailable"},
        {"policy_verdict": "error"},
    ]
    assert cvr(actions) == (1, 2)
    assert cvr_rate(actions) == 0.5
    assert cvr_rate([{"policy_verdict": "unavailable"}] * 5) is None  # never 0.0


# -- the >16k row, for every detector ----------------------------------------


@pytest.mark.parametrize("fine_grained", [False, True], ids=["binary", "fine_grained"])
def test_over_window_trajectory_is_unavailable_for_every_detector(monkeypatch, fine_grained):
    """A trajectory serialized over 16,384 tokens scores ``unavailable`` for
    every detector, never clean — with or without a real tokenizer."""
    import saster_defense.l4_auditor as l4

    # offline estimate path (no endpoint): the ~4 chars/token estimate
    offline = l4.TrajectoryAuditor(context_window=16384, fine_grained=fine_grained)
    out = offline.audit(OVER_WINDOW_RECORDS)
    assert out.verdict is Verdict.UNAVAILABLE and out.ran is False
    assert "exceeds" in out.detail

    # real-tokenizer path: /tokenize answers with a count over the window and
    # /v1/models with the window; the chat completion must never be consulted
    calls: list[str] = []

    class R:
        def __init__(self, p):
            self.p = p

        def raise_for_status(self):
            return None

        def json(self):
            return self.p

    def post(url, **kw):
        calls.append(url)
        if url.endswith("/tokenize"):
            return R({"count": 20000})
        return R({"choices": [{"message": {"content": "safe"}, "finish_reason": "stop"}]})

    monkeypatch.setattr(l4.httpx, "post", post)
    monkeypatch.setattr(l4.httpx, "get", lambda url, **kw: R({"data": [{"max_model_len": 16384}]}))
    real = l4.TrajectoryAuditor(endpoint="http://x", fine_grained=fine_grained)
    out = real.audit(OVER_WINDOW_RECORDS)
    assert out.verdict is Verdict.UNAVAILABLE and out.ran is False
    assert not any(u.endswith("/v1/chat/completions") for u in calls), (
        "the observer was asked to audit a trajectory that does not fit its window"
    )


# -- L1: the wrapper with no parse surface -----------------------------------


def test_l1_without_stand_in_is_unavailable_never_clean():
    guard = ClassifierGuard(use_representative=False)
    out = guard.classify(ActionRequest.from_tool("secrets.rotate_credential", tier=2))
    assert out.verdict is Verdict.UNAVAILABLE and out.ran is False


def test_l1_endpoint_that_does_not_answer_is_unavailable_not_real():
    """D5, restated for a module that now carries a client: an endpoint that
    does not answer is UNAVAILABLE (never the stand-in's answer under a real
    label), and the manifest says ``real`` only after a health check has
    listed the model."""
    guard = ClassifierGuard(model="ibm-granite/granite-guardian-3.2-5b", endpoint="http://guardian.invalid:8003", timeout=2.0)
    out = guard.classify(ActionRequest.from_tool("secrets.rotate_credential", tier=2))
    assert out.verdict is Verdict.UNAVAILABLE and out.ran is False, (
        f"L1 with an unreachable endpoint answered {out.verdict.value!r}"
    )
    assert guard.health_check() is False and guard.representative
    stack = DefenseStack(config=DefenseConfig(l1=True), fixture_id="t0", classifier=guard)
    assert stack.manifest()["l1"]["backend_status"] != "real"
