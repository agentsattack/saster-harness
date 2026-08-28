"""VictimAgent base — plane exposure, cross-deployment plane resolution, and
dispatch integrity."""
from __future__ import annotations

import pytest

from carl_ops_trajectory import validate_record
from saster_harness.instrumentation import ObservationPlane
from saster_harness.victim_agent import (
    UnboundToolDispatchError,
    VictimAgent,
)


class _StubDeployment(VictimAgent):
    """Minimal concrete deployment: echoes the tool name back."""

    def _execute_tool(self, tool, target=None, **args):
        return f"ran:{tool}"


class _ToolDetector:
    requires_planes = (ObservationPlane.TOOL,)


class _ModelDetector:
    requires_planes = (ObservationPlane.MODEL,)


def _agent(profile="standard", deployment="stub"):
    return _StubDeployment(
        run_id="r", challenge_id="c", deployment=deployment, profile_name=profile
    )


# -- plane resolution is identical across deployments -----------------------


def test_plane_resolution_identical_across_deployments():
    a = _agent(deployment="carl-support-like")
    b = _agent(deployment="carl-ops-like")
    tool_det, model_det = _ToolDetector(), _ModelDetector()
    # Under standard (tool-only), a tool detector is available on both and a
    # model detector is unavailable on both — resolution does not depend on
    # which deployment produced the trajectory.
    assert a.detector_available(tool_det) == b.detector_available(tool_det) is True
    assert a.detector_available(model_det) == b.detector_available(model_det) is False
    assert a.required_planes(model_det) == b.required_planes(model_det)


def test_unavailable_plane_is_not_clean():
    # A model-requiring detector under the tool-only profile is UNAVAILABLE,
    # a state distinct from clean. (Honest note: no shipped detector needs a
    # non-tool plane, so this branch is exercised only by this stub.)
    a = _agent(profile="standard")
    assert a.detector_available(_ModelDetector()) is False
    full = _agent(profile="full")
    assert full.detector_available(_ModelDetector()) is True


def test_active_planes_follow_profile():
    assert _agent("standard").active_planes() == frozenset({ObservationPlane.TOOL})
    assert _agent("full").active_planes() == frozenset(ObservationPlane)


# -- dispatch integrity ------------------------------------------------------


def test_unbound_tool_call_is_refused_and_recorded_as_integrity_event():
    a = _agent()
    with pytest.raises(UnboundToolDispatchError):
        a.dispatch_tool("some.tool", None, arg=1)
    recs = a.records()
    assert len(recs) == 1
    assert recs[0]["record_type"] == "error"
    assert recs[0]["outcome"] == "error"
    assert recs[0]["error"]["type"] == "unbound_tool_dispatch"
    # It is NOT recorded as a step — a spoof never enters the trace as agent
    # behaviour.
    assert all(r["record_type"] != "step" for r in recs)


def test_token_for_a_different_tool_is_refused():
    a = _agent()
    token = a.record_completion("call tool A", authorized_tools=("tool.A",))
    with pytest.raises(UnboundToolDispatchError):
        a.dispatch_tool("tool.B", token)  # not authorized by this completion


def test_bound_tool_call_executes_and_records_a_step():
    a = _agent(profile="full")
    token = a.record_completion("call the tool", authorized_tools=("some.tool",))
    result = a.dispatch_tool("some.tool", token, target="t", x=1)
    assert result == "ran:some.tool"
    kinds = [r["record_type"] for r in a.records()]
    assert kinds == ["model_call", "step"]  # completion, then bound dispatch


def test_all_emitted_records_validate():
    a = _agent(profile="model")
    token = a.record_completion("go", authorized_tools=("some.tool",))
    a.dispatch_tool("some.tool", token)
    with pytest.raises(UnboundToolDispatchError):
        a.dispatch_tool("some.tool", None)
    for rec in a.records():
        assert validate_record(rec) == [], rec


def test_model_plane_record_only_when_model_plane_active():
    # Standard profile is tool-only: a completion is still minted (so tools
    # can bind) but no model_call record is emitted.
    a = _agent(profile="standard")
    token = a.record_completion("go", authorized_tools=("some.tool",))
    a.dispatch_tool("some.tool", token)
    assert [r["record_type"] for r in a.records()] == ["step"]
