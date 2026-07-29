"""Configurable instrumentation — planes, profiles, gating, escalation."""

from __future__ import annotations

import pytest

from saster_harness.config import MonitoringConfig
from saster_harness.detector import SasterDetector
from saster_harness.event import TurnData
from saster_harness.instrumentation import (
    DEFAULT_PROFILE,
    CallbackProcessPlaneAdapter,
    InstrumentationState,
    ObservationPlane,
    detector_required_planes,
    resolve_profile,
)
from saster_harness.proxy import HarnessAddon

# --- fake detectors ---------------------------------------------------------


class _ToolDetector(SasterDetector):
    saster_id = "TEST-TOOL"
    pattern_name = "Test Tool"
    tier = 4
    # requires_planes defaults to (TOOL,)

    def evaluate(self, turn: TurnData):
        if "fire" in (turn.user_message or ""):
            return self._build_event(turn, {"signal": "t", "detail": "d"})
        return None


class _ModelDetector(SasterDetector):
    saster_id = "TEST-MODEL"
    pattern_name = "Test Model"
    tier = 3
    requires_planes = (ObservationPlane.MODEL,)

    def evaluate(self, turn: TurnData):
        return self._build_event(turn, {"signal": "m", "detail": "d"})


# --- profiles ---------------------------------------------------------------


def test_default_profile_is_tool_only():
    prof = resolve_profile(DEFAULT_PROFILE)
    assert prof.name == "standard"
    assert prof.planes == frozenset({ObservationPlane.TOOL})


def test_builtin_profiles():
    assert resolve_profile("model").planes == {
        ObservationPlane.TOOL,
        ObservationPlane.MODEL,
    }
    assert resolve_profile("full").planes == {
        ObservationPlane.TOOL,
        ObservationPlane.MODEL,
        ObservationPlane.PROCESS,
    }


def test_custom_profile_shadows_and_resolves():
    prof = resolve_profile("mine", {"mine": ["tool", "process"]})
    assert prof.planes == {ObservationPlane.TOOL, ObservationPlane.PROCESS}


def test_unknown_profile_raises():
    with pytest.raises(KeyError):
        resolve_profile("nope")


def test_default_detector_requires_tool_plane():
    assert detector_required_planes(_ToolDetector()) == frozenset(
        {ObservationPlane.TOOL}
    )
    assert detector_required_planes(_ModelDetector()) == frozenset(
        {ObservationPlane.MODEL}
    )


# --- availability: unavailable != clean ------------------------------------


def test_model_detector_unavailable_under_standard():
    state = InstrumentationState(resolve_profile("standard"))
    assert state.is_available(_ToolDetector()) is True
    assert state.is_available(_ModelDetector()) is False
    avail = state.availability_map([_ToolDetector(), _ModelDetector()])
    assert avail == {"TEST-TOOL": "available", "TEST-MODEL": "unavailable"}


def test_model_detector_available_under_model_profile():
    state = InstrumentationState(resolve_profile("model"))
    assert state.is_available(_ModelDetector()) is True


def test_partition_splits_available_unavailable():
    state = InstrumentationState(resolve_profile("standard"))
    avail, unavail = state.partition([_ToolDetector(), _ModelDetector()])
    assert [d.saster_id for d in avail] == ["TEST-TOOL"]
    assert [d.saster_id for d in unavail] == ["TEST-MODEL"]


# --- transitions ------------------------------------------------------------


def test_switch_records_transition_with_overhead():
    state = InstrumentationState(resolve_profile("standard"))
    t = state.switch("full", "manual", session_id="s1", turn_idx=3)
    assert t is not None
    assert (t.from_profile, t.to_profile) == ("standard", "full")
    assert t.overhead_seconds >= 0.0
    assert state.active_profile == "full"
    assert len(state.transitions()) == 1


def test_noop_switch_returns_none():
    state = InstrumentationState(resolve_profile("standard"))
    assert state.switch("standard", "manual") is None
    assert state.transitions() == []


def test_switch_on_activate_receives_added_planes():
    state = InstrumentationState(resolve_profile("standard"))
    seen = {}
    state.switch("model", "x", on_activate=lambda added: seen.update({"a": added}))
    assert seen["a"] == frozenset({ObservationPlane.MODEL})


def test_to_dict_snapshot():
    state = InstrumentationState(resolve_profile("standard"))
    state.switch("model", "manual")
    snap = state.to_dict([_ToolDetector(), _ModelDetector()])
    assert snap["active_profile"] == "model"
    assert snap["active_planes"] == ["model", "tool"]
    assert snap["detector_availability"]["TEST-MODEL"] == "available"
    assert len(snap["transitions"]) == 1


# --- addon gating -----------------------------------------------------------


def _turn(msg="fire"):
    return TurnData(session_id="sess", turn_idx=0, user_message=msg)


def test_addon_gates_unavailable_detector_and_records_it():
    events = []
    state = InstrumentationState(resolve_profile("standard"))
    addon = HarnessAddon(
        adapter=object(),
        detectors=[_ToolDetector(), _ModelDetector()],
        baseline=object(),
        sink=events.append,
        agent_name="a",
        instrumentation=state,
    )
    addon._run_detectors(_turn("fire"))
    # Tool detector ran and fired; model detector was gated (unavailable),
    # NOT run-and-clean.
    assert [e.saster_id for e in events] == ["TEST-TOOL"]
    assert addon.unavailable_detectors("sess") == {"TEST-MODEL"}
    # Firing carries the active profile it was observed under.
    assert events[0].evidence["active_profile"] == "standard"


def test_addon_runs_model_detector_after_switch():
    events = []
    state = InstrumentationState(resolve_profile("standard"))
    addon = HarnessAddon(
        adapter=object(),
        detectors=[_ModelDetector()],
        baseline=object(),
        sink=events.append,
        agent_name="a",
        instrumentation=state,
    )
    addon._run_detectors(_turn())
    assert events == []
    assert addon.unavailable_detectors("sess") == {"TEST-MODEL"}
    state.switch("model", "manual")
    addon._run_detectors(_turn())
    assert [e.saster_id for e in events] == ["TEST-MODEL"]


def test_addon_without_instrumentation_runs_all():
    # Backward-compatible default: no gating.
    events = []
    addon = HarnessAddon(
        adapter=object(),
        detectors=[_ToolDetector(), _ModelDetector()],
        baseline=object(),
        sink=events.append,
        agent_name="a",
    )
    addon._run_detectors(_turn("fire"))
    assert set(e.saster_id for e in events) == {"TEST-TOOL", "TEST-MODEL"}


# --- process-plane reference adapter ---------------------------------------


def test_callback_process_adapter():
    got = []
    a = CallbackProcessPlaneAdapter(sink=got.append)
    a.emit({"before_start": 1})  # ignored — not started
    assert got == []
    a.start()
    a.emit({"hook": "tool_call"})
    a.stop()
    a.emit({"after_stop": 1})  # ignored
    assert got == [{"hook": "tool_call"}]
    assert a.received == [{"hook": "tool_call"}]


# --- config validation ------------------------------------------------------


def _cfg(**kw):
    base = dict(agent_name="a", agent_endpoint="http://x", authorized_tools=[])
    base.update(kw)
    return MonitoringConfig(**base)


def test_config_default_profile_is_standard():
    assert _cfg().instrumentation_profile == "standard"


def test_config_rejects_unknown_profile():
    with pytest.raises(ValueError):
        _cfg(instrumentation_profile="nope")


def test_config_rejects_invalid_custom_plane():
    with pytest.raises(ValueError):
        _cfg(custom_profiles={"x": ["tool", "bogus"]})


def test_config_accepts_valid_custom_profile():
    c = _cfg(instrumentation_profile="x", custom_profiles={"x": ["tool", "model"]})
    assert c.instrumentation_profile == "x"


def test_config_escalation_requires_target():
    with pytest.raises(ValueError):
        _cfg(escalation_enabled=True)


def test_config_escalation_target_must_resolve():
    with pytest.raises(ValueError):
        _cfg(escalation_enabled=True, escalation_profile="nope")
    # valid target is accepted
    c = _cfg(escalation_enabled=True, escalation_profile="full")
    assert c.escalation_profile == "full"
