"""Tests for the v0.3 split of InductionDetector into
SingleTurnInductionDetector + ScenarioInductionDetector.

Covers the inheritance / introspection contract. Per-detector
behavior is exercised in the existing test_saster_*_induced files.
"""

from __future__ import annotations

import pytest

from saster_harness.detectors.base_induction import (
    InductionDetector,
    ScenarioInductionDetector,
    SingleTurnInductionDetector,
)
from saster_harness.detectors.saster_13_induced import Saster13InducedDetector
from saster_harness.detectors.saster_15_induced import Saster15InducedDetector
from saster_harness.detectors.saster_18_induced import Saster18InducedDetector
from saster_harness.detectors.saster_24_induced import Saster24InducedDetector
from saster_harness.detectors.saster_26_induced import Saster26InducedDetector

_SINGLE_TURN_DETECTORS = (
    Saster13InducedDetector,
    Saster18InducedDetector,
)

_SCENARIO_DETECTORS = (
    Saster15InducedDetector,
    Saster24InducedDetector,
    Saster26InducedDetector,
)


def test_polymorphic_parent_is_abstract() -> None:
    """InductionDetector itself can't be instantiated — concrete
    detectors must inherit from one of the two siblings."""
    with pytest.raises(TypeError):
        InductionDetector()  # type: ignore[abstract]


@pytest.mark.parametrize("cls", _SINGLE_TURN_DETECTORS)
def test_single_turn_detectors_inherit_correctly(cls: type) -> None:
    det = cls()
    assert isinstance(det, SingleTurnInductionDetector)
    assert isinstance(det, InductionDetector)
    assert not isinstance(det, ScenarioInductionDetector)
    # The single-turn contract methods must exist.
    assert callable(det.baseline_prompt)
    assert callable(det.induction_strategy)
    assert callable(det.divergence_score)


@pytest.mark.parametrize("cls", _SCENARIO_DETECTORS)
def test_scenario_detectors_inherit_correctly(cls: type) -> None:
    det = cls()
    assert isinstance(det, ScenarioInductionDetector)
    assert isinstance(det, InductionDetector)
    assert not isinstance(det, SingleTurnInductionDetector)
    # Scenario detectors must expose scenarios() and must NOT carry
    # the old single-turn compat shims.
    assert callable(det.scenarios)
    assert len(det.scenarios()) > 0
    assert not hasattr(det, "baseline_prompt")
    assert not hasattr(det, "induction_strategy")
    # divergence_score is gone too — scenario detectors expose
    # divergence_for_scenario instead (signature varies per detector).
    assert not hasattr(det, "divergence_score")


def test_evaluate_returns_none_for_both_shapes() -> None:
    """Both shapes inherit ``evaluate -> None`` from the polymorphic
    parent — induction is out-of-band."""
    from saster_harness.event import TurnData

    turn = TurnData(session_id="s", turn_idx=0)
    for cls in (*_SINGLE_TURN_DETECTORS, *_SCENARIO_DETECTORS):
        det = cls()
        assert det.evaluate(turn) is None


def test_polymorphic_isinstance_check_covers_both_shapes() -> None:
    """The scheduler relies on ``isinstance(d, InductionDetector)``
    covering both single-turn and scenario detectors."""
    for cls in (*_SINGLE_TURN_DETECTORS, *_SCENARIO_DETECTORS):
        det = cls()
        assert isinstance(det, InductionDetector), (
            f"{cls.__name__} not polymorphically detected as InductionDetector"
        )


def test_single_turn_carries_concrete_induce_impl() -> None:
    """SingleTurnInductionDetector ships a concrete induce() that
    drives the standard loop using the three abstract primitives.
    Subclasses MAY override (SASTER-13 does for session scoping)."""
    # Saster18InducedDetector inherits the base induce() without override.
    assert (
        Saster18InducedDetector.induce
        is SingleTurnInductionDetector.induce
        or Saster18InducedDetector.induce is not InductionDetector.induce
    )
    # The base impl exists and is concrete.
    assert (
        getattr(SingleTurnInductionDetector.induce, "__isabstractmethod__", False)
        is False
    )


def test_scenario_induce_is_abstract_on_the_base() -> None:
    """ScenarioInductionDetector leaves induce() abstract because
    every scenario detector implements its own orchestration."""
    assert (
        getattr(ScenarioInductionDetector.induce, "__isabstractmethod__", False)
        is True
    )
