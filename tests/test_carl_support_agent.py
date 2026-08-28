"""carl-support deployment — minimal tool surface for tool-plane observation
of the intent_erosion_susceptible directive."""
from __future__ import annotations

import pytest

from carl.support_agent import (
    BENIGN_TOOL,
    CARL_SUPPORT_DIRECTIVE,
    CARL_SUPPORT_TOOLS,
    RESTRICTED_TOOLS,
    CarlSupport,
)
from carl_ops_agent.deployments import build_carl_ops, build_carl_support
from carl_ops_trajectory import validate_record
from saster_harness.instrumentation import ObservationPlane
from saster_harness.victim_agent import UnboundToolDispatchError


def test_minimal_surface_is_five_tools_not_thirteen():
    tools = CarlSupport.model_facing_tools()
    assert len(tools) == 5
    assert set(tools) == set(CARL_SUPPORT_TOOLS)
    # one benign anchor + the four restricted actions the directive enumerates
    assert BENIGN_TOOL in tools
    assert set(RESTRICTED_TOOLS) <= set(tools)
    assert len(RESTRICTED_TOOLS) == 4


def test_wraps_the_existing_directive_unchanged():
    agent = CarlSupport()
    assert agent.directive == CARL_SUPPORT_DIRECTIVE == "intent_erosion_susceptible"


def test_baseline_benign_tool_is_observable_on_the_tool_plane():
    # A non-eroded run still emits a tool-plane action, so a beat-1 miss is
    # distinguishable from nothing-to-observe (P7).
    agent = CarlSupport()
    obs = agent.act(BENIGN_TOOL, account="acct-1")
    assert obs["found"] is True
    steps = [r for r in agent.records() if r["record_type"] == "step"]
    assert len(steps) == 1
    assert steps[0]["plane"] == ObservationPlane.TOOL.value
    assert steps[0]["action"]["tool"] == BENIGN_TOOL


def test_capitulation_to_a_restricted_action_is_observable():
    agent = CarlSupport()
    obs = agent.act("support.export_customers")
    assert obs["restricted"] is True
    assert agent.is_restricted("support.export_customers")
    step = agent.records()[-1]
    assert step["record_type"] == "step"
    assert step["action"]["tool"] == "support.export_customers"


def test_dispatch_integrity_holds_for_carl_support():
    agent = CarlSupport()
    with pytest.raises(UnboundToolDispatchError):
        agent.dispatch_tool("support.grant_admin", None)


def test_emitted_records_validate():
    agent = CarlSupport(profile_name="model")
    agent.act(BENIGN_TOOL, account="a")
    agent.act("support.set_rate_limit")
    for rec in agent.records():
        assert validate_record(rec) == [], rec
        assert rec["clock"] == "logical"


def test_registry_builds_carl_support_and_carl_ops_separately():
    support = build_carl_support()
    assert isinstance(support, CarlSupport)
    with pytest.raises(ValueError, match="configuration"):
        build_carl_ops("carl-support")
