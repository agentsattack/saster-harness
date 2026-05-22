"""Tests for the v0.3.2 public detector-registration hooks.

Coverage:
- register_detector adds a module-path entry usable via enabled_detectors.
- register_detector_instance adds a pre-built instance.
- Re-registering an id replaces the previous entry.
- Instance registry wins when both registries carry the same id.
- Validation: empty id, missing modules, wrong instance type.
- registered_detector_ids returns the union of both registries.
"""

from __future__ import annotations

import sys
import types

import pytest

from saster_harness import (
    MonitoringConfig,
    MonitoringHarness,
    SasterDetector,
    register_detector,
    register_detector_instance,
    registered_detector_ids,
)
from saster_harness.event import DetectionEvent, TurnData
from saster_harness.harness import (
    _DETECTOR_INSTANCE_REGISTRY,
    _DETECTOR_REGISTRY,
    _load_default_detectors,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _CustomDetector(SasterDetector):
    saster_id = "CUSTOM-1"
    pattern_name = "Custom Pattern"
    tier = 3

    def __init__(self, mark: str = "default") -> None:
        super().__init__()
        self.mark = mark

    def evaluate(self, turn: TurnData) -> DetectionEvent | None:
        return None


@pytest.fixture(autouse=True)
def _isolate_registry() -> None:
    """Snapshot and restore both registries around each test so
    register_* calls don't leak across the suite."""
    snapshot_path = dict(_DETECTOR_REGISTRY)
    snapshot_instance = dict(_DETECTOR_INSTANCE_REGISTRY)
    yield
    _DETECTOR_REGISTRY.clear()
    _DETECTOR_REGISTRY.update(snapshot_path)
    _DETECTOR_INSTANCE_REGISTRY.clear()
    _DETECTOR_INSTANCE_REGISTRY.update(snapshot_instance)


# ---------------------------------------------------------------------------
# register_detector (module-path form)
# ---------------------------------------------------------------------------


def test_register_detector_makes_id_loadable_via_enabled_detectors() -> None:
    """Build a fake module on the fly, register it, load it through the
    standard path."""
    mod = types.ModuleType("saster_harness_test_custom_a")
    mod.DETECTOR = _CustomDetector(mark="fake-module")
    sys.modules["saster_harness_test_custom_a"] = mod
    try:
        register_detector("CUSTOM-A", "saster_harness_test_custom_a")
        loaded = _load_default_detectors(["CUSTOM-A"])
        assert len(loaded) == 1
        assert loaded[0].saster_id == "CUSTOM-1"
        assert loaded[0].mark == "fake-module"  # type: ignore[attr-defined]
    finally:
        sys.modules.pop("saster_harness_test_custom_a", None)


def test_register_detector_re_registration_replaces_previous() -> None:
    mod_a = types.ModuleType("saster_harness_test_repl_a")
    mod_a.DETECTOR = _CustomDetector(mark="A")
    mod_b = types.ModuleType("saster_harness_test_repl_b")
    mod_b.DETECTOR = _CustomDetector(mark="B")
    sys.modules["saster_harness_test_repl_a"] = mod_a
    sys.modules["saster_harness_test_repl_b"] = mod_b
    try:
        register_detector("REPL-1", "saster_harness_test_repl_a")
        register_detector("REPL-1", "saster_harness_test_repl_b")
        loaded = _load_default_detectors(["REPL-1"])
        assert loaded[0].mark == "B"  # type: ignore[attr-defined]
    finally:
        sys.modules.pop("saster_harness_test_repl_a", None)
        sys.modules.pop("saster_harness_test_repl_b", None)


def test_register_detector_rejects_empty_id() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        register_detector("", "some.module")
    with pytest.raises(ValueError, match="non-empty"):
        register_detector("   ", "some.module")


def test_register_detector_rejects_missing_module_paths() -> None:
    with pytest.raises(ValueError, match="at least one"):
        register_detector("X")


def test_register_detector_rejects_empty_path() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        register_detector("X", "good.module", "")


# ---------------------------------------------------------------------------
# register_detector_instance (instance form)
# ---------------------------------------------------------------------------


def test_register_detector_instance_loads_pre_built_instance() -> None:
    sentinel = _CustomDetector(mark="instance-form")
    register_detector_instance("CUSTOM-INST", sentinel)
    loaded = _load_default_detectors(["CUSTOM-INST"])
    assert len(loaded) == 1
    assert loaded[0] is sentinel


def test_register_detector_instance_wins_over_module_path() -> None:
    """When the same id appears in both registries, the instance wins."""
    sentinel = _CustomDetector(mark="instance-wins")
    mod = types.ModuleType("saster_harness_test_loser")
    mod.DETECTOR = _CustomDetector(mark="module-loses")
    sys.modules["saster_harness_test_loser"] = mod
    try:
        register_detector("CONFLICT-1", "saster_harness_test_loser")
        register_detector_instance("CONFLICT-1", sentinel)
        loaded = _load_default_detectors(["CONFLICT-1"])
        assert loaded[0] is sentinel
    finally:
        sys.modules.pop("saster_harness_test_loser", None)


def test_register_detector_instance_rejects_non_detector() -> None:
    with pytest.raises(TypeError, match="SasterDetector"):
        register_detector_instance("BAD", "not a detector")  # type: ignore[arg-type]


def test_register_detector_instance_rejects_empty_id() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        register_detector_instance("", _CustomDetector())


# ---------------------------------------------------------------------------
# Unknown id rejection
# ---------------------------------------------------------------------------


def test_unknown_id_still_raises_after_registration() -> None:
    """Sanity: registering one id doesn't make every id valid."""
    register_detector_instance("REGISTERED-1", _CustomDetector())
    with pytest.raises(ValueError, match="Unknown detector identifier"):
        _load_default_detectors(["NOT-A-REAL-ID"])


# ---------------------------------------------------------------------------
# registered_detector_ids
# ---------------------------------------------------------------------------


def test_registered_detector_ids_includes_both_registries() -> None:
    register_detector("PATH-ID", "fake.module")
    register_detector_instance("INST-ID", _CustomDetector())
    ids = registered_detector_ids()
    assert "PATH-ID" in ids
    assert "INST-ID" in ids
    # Shipped ids still present
    assert "SASTER-18-induced" in ids
    assert "SASTER-18-multiturn" in ids


# ---------------------------------------------------------------------------
# End-to-end: harness picks up a registered detector
# ---------------------------------------------------------------------------


def test_harness_loads_registered_detector_via_enabled_detectors() -> None:
    """End-to-end: register, build a MonitoringConfig referencing the
    custom id, construct the harness, assert the detector is in the
    detector list."""
    sentinel = _CustomDetector(mark="end-to-end")
    register_detector_instance("E2E-1", sentinel)

    config = MonitoringConfig(
        agent_name="test-agent",
        agent_endpoint="http://localhost:9999/chat",
        authorized_tools=["any"],
        enabled_detectors=["E2E-1"],
        sample_refusal_baseline=False,
    )
    harness = MonitoringHarness(config)
    assert any(d is sentinel for d in harness.detectors)
