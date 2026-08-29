"""Run manifest for the defense stack.

Records what actually ran per run: which layers were active, the backend behind
each (a config field, never a hidden constant), and — critically — each
layer's ``backend_status``: ``real`` when the genuine component executed, or
``stand-in`` (with a reason) when a labelled representative ran in its place. A
corpus generated against a stand-in must be identifiable as such from the
record alone, so this status travels with every run.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .l1_classifier import LLAMAGUARD3_ATBENCH_RECALL
from .l2_policy import ALL_RULES

if TYPE_CHECKING:
    from .stack import DefenseStack

#: Why each layer is real or a stand-in in THIS environment. Recorded so the
#: corpus is self-describing.
_STANDIN_REASONS = {
    "l1": "LlamaGuard3-8B weights not obtainable in this environment",
    "l4": "no AgentDoG endpoint configured; representative warn evaluator in use",
}


def _status(is_real: bool, layer: str) -> dict[str, Any]:
    if is_real:
        return {"backend_status": "real"}
    return {"backend_status": "stand-in", "stand_in_reason": _STANDIN_REASONS.get(layer, "")}


def build_manifest(stack: DefenseStack) -> dict[str, Any]:
    cfg = stack.config
    manifest: dict[str, Any] = {
        "fixture_id": stack.fixture_id,
        "layers_enabled": {
            "l1": cfg.l1, "l2": cfg.l2, "l3": cfg.l3, "l4": cfg.l4, "l5": cfg.l5,
        },
        "budget": {
            "cap": stack.budget.cap,
            "base_cost": stack.budget.base_cost,
            "reroute_cost": stack.budget.reroute_cost,
        },
    }
    if cfg.l1 and stack.classifier is not None:
        c = stack.classifier
        manifest["l1"] = {
            "role": "input_classifier",
            "model": c.model,
            "endpoint": c.endpoint,
            "backend": c.backend,
            "atbench_recall": LLAMAGUARD3_ATBENCH_RECALL,
            "note": "low agent-path recall is the anchored operating point, not a bug",
            **_status(not c.representative, "l1"),
        }
    if cfg.l2 and stack.policy is not None:
        p = stack.policy
        manifest["l2"] = {
            "role": "policy_engine",
            "backend": p.backend,   # 'opa' (real) or 'python-mirror'
            "policy_artifact": "policy.rego",
            "stateless_per_action": True,
            "rules_active": sorted(p.rules),
            "rules_available": list(ALL_RULES),
            "python_mirror": "test-oracle only; agrees with OPA on the test set",
            **_status(not p.representative, "l2"),
        }
    if cfg.l3 and stack.trace is not None:
        t = stack.trace
        manifest["l3"] = {
            "role": "trace_monitor",
            "backend": t.backend,   # 'z3' (real) or 'representative'
            "backend_class": "SMT-over-finite-trace",
            "intended_specific_tool": "VIGIL (unobtainable; z3 is the real solver of the class)",
            "policy_cache": "per-fixture, config-invariant",
            "observability_boundary": "opaque exec.run (in-script effects unobserved) — P4",
            **_status(not t.representative, "l3"),
        }
    if cfg.l4 and stack.auditor is not None:
        a = stack.auditor
        manifest["l4"] = {
            "role": "trajectory_auditor",
            "observer_model": a.observer_model,
            "endpoint": a.endpoint,
            "backend": a.backend,
            "context_window": a.context_window,
            "level": "warn",
            "note": "observer_model is a config field; vary if budget allows",
            **_status(not a.representative, "l4"),
        }
    if cfg.l5 and stack.approval is not None:
        manifest["l5"] = {
            "role": "approval_gate",
            "escalate_tier": stack.approval.escalate_tier,
            "approver": "scriptable (auto-approve default; human on stage)",
            "backend_status": "real",  # a real gate, no external model needed
        }
    return manifest
