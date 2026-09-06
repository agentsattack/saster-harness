"""Pre-pilot adjustments, 2026-09-05: the judge is never the victim; Ministral
under tool_choice required (addendum §L); every observer head recorded
with head and role (AMENDMENT 16)."""
from __future__ import annotations

import pytest

from carl_ops_agent.agent import CarlOpsMode
from carl_ops_agent.model_driven import ModelDrivenAgent
from carl_ops_trajectory import first_finding_step, validate_record
from saster_defense import TrajectoryAuditor, Verdict
from saster_defense.types import LayerName, LayerOutcome
from saster_harness.families import FAMILIES, judge_family_for, tool_choice_for
from saster_instrument import WRAPPERS
from tests.test_carl_ops_trajectory import reject, valid_trajectory_record


def test_judge_is_the_other_family():
    assert judge_family_for("Qwen/Qwen3-8B").model == "mistralai/Ministral-8B-Instruct-2410"
    assert judge_family_for("mistralai/Ministral-8B-Instruct-2410").model == "Qwen/Qwen3-8B"
    for fam in FAMILIES.values():
        assert judge_family_for(fam.model).model != fam.model
    with pytest.raises(KeyError):
        judge_family_for("nobody/unregistered")


def test_ministral_runs_under_tool_choice_required_and_qwen_does_not():
    assert tool_choice_for("mistralai/Ministral-8B-Instruct-2410") == "required"
    assert tool_choice_for("Qwen/Qwen3-8B") is None
    bodies = []
    agent = ModelDrivenAgent("http://x", "mistralai/Ministral-8B-Instruct-2410", "c", obstructed=False,
                             temperature=0.7, seed=1, mode=CarlOpsMode.INDUCED,
                             transport=lambda body: bodies.append(body) or {"choices": []})
    agent.select_action(0)
    assert bodies[0]["tool_choice"] == "required"
    assert agent.sampling_manifest_block()["tool_choice"] == "required"
    qwen = ModelDrivenAgent("http://x", "Qwen/Qwen3-8B", "c", obstructed=False, temperature=0.7,
                            seed=1, mode=CarlOpsMode.INDUCED,
                            transport=lambda body: bodies.append(body) or {"choices": []})
    qwen.select_action(0)
    assert "tool_choice" not in bodies[1]


def test_recorded_heads_are_never_counted_and_do_not_break_completeness():
    rec = valid_trajectory_record()
    rec["detection"] = [
        {"layer": "l4_auditor", "step_index": 1, "severity": "medium", "action_taken": "warn",
         "finding": True, "status": "ok", "head": "AI45Research/AgentDoG1.5-Qwen3.5-4B", "role": "recorded"},
        {"layer": "l4_auditor", "step_index": 2, "severity": "unavailable", "action_taken": None,
         "status": "unavailable", "head": "AI45Research/AgentDoG1.5-FG-Qwen3.5-4b", "role": "recorded"},
        {"layer": "l2_policy", "step_index": 3, "severity": "high", "action_taken": "block",
         "finding": True, "status": "ok"},
    ]
    assert first_finding_step(rec["detection"]) == 3
    rec["detection_complete"] = True          # a recorded head down is not an incomplete stack
    assert validate_record(rec) == []
    bad = valid_trajectory_record()
    bad["detection"][0]["role"] = "comparator"
    reject(bad, "role")
    bad = valid_trajectory_record()
    bad["detection"][0]["role"] = "recorded"   # no head
    reject(bad, "head")


def test_auditor_outcomes_carry_head_and_role():
    aud = TrajectoryAuditor(observer_model="AI45Research/AgentDoG-FG-Qwen3-4B", role="recorded")
    out = aud.audit([{"step": 0, "tool": "secrets.list_expiring", "args": {}}])
    assert out.head == "AI45Research/AgentDoG-FG-Qwen3-4B" and out.role == "recorded"
    warn = LayerOutcome(LayerName.L4_AUDITOR, Verdict.WARN, ran=True, head="h", role="recorded")
    e = warn.as_detection_entry(4)
    assert e["head"] == "h" and e["role"] == "recorded"
    primary = LayerOutcome(LayerName.L4_AUDITOR, Verdict.WARN, ran=True, head="h")
    assert "role" not in primary.as_detection_entry(4)


def test_15_parsers_are_in_the_degenerate_matrix():
    assert {"l4_auditor_15_coarse", "l4_auditor_15_unified"} <= set(WRAPPERS)
