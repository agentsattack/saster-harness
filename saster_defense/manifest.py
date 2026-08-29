"""Run manifest for the defense stack.

Records what actually ran: which layers were active, the model/backend behind
each layer as a config field (never a hidden constant), and whether a layer is
a ``representative`` stand-in for an unavailable real backend. The
class-vs-repo dissociation under test depends on this being explicit — a
representative stand-in must be labelled here, not silently substituted.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .l1_classifier import LLAMAGUARD3_ATBENCH_RECALL
from .l2_policy import ALL_RULES

if TYPE_CHECKING:
    from .stack import DefenseStack

#: VIGIL (the intended L3 trace-verification backend) was searched for and is
#: unobtainable in this environment; L3 runs the representative stand-in of the
#: same architectural class. The dissociation under test is between classes.
VIGIL_STATUS = "unobtainable — representative stand-in of the same class in use"


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
        manifest["l1"] = {
            "role": "input_classifier",
            "model": stack.classifier.model,
            "endpoint": stack.classifier.endpoint,
            "atbench_recall": LLAMAGUARD3_ATBENCH_RECALL,
            "representative": stack.classifier.representative,
            "note": "low agent-path recall is the anchored operating point, not a bug",
        }
    if cfg.l2 and stack.policy is not None:
        manifest["l2"] = {
            "role": "policy_engine",
            "backend": "opa/rego",
            "executor": "representative-python (no opa binary present)",
            "stateless_per_action": True,
            "rules_active": sorted(stack.policy.rules),
            "rules_available": list(ALL_RULES),
            "representative": stack.policy.representative,
        }
    if cfg.l3 and stack.trace is not None:
        manifest["l3"] = {
            "role": "trace_monitor",
            "backend_class": "SMT-over-finite-trace",
            "intended_backend": "VIGIL",
            "vigil_status": VIGIL_STATUS,
            "executor": "representative bounded checker (z3 not present)",
            "representative": stack.trace.representative,
            "policy_cache": "per-fixture, config-invariant",
            "observability_boundary": "opaque exec.run (in-script effects unobserved) — P4",
        }
    if cfg.l4 and stack.auditor is not None:
        manifest["l4"] = {
            "role": "trajectory_auditor",
            "observer_model": stack.auditor.observer_model,
            "context_window": stack.auditor.context_window,
            "level": "warn",
            "representative": stack.auditor.representative,
            "note": "observer_model is a config field; vary if budget allows",
        }
    if cfg.l5 and stack.approval is not None:
        manifest["l5"] = {
            "role": "approval_gate",
            "escalate_tier": stack.approval.escalate_tier,
            "approver": "scriptable (auto-approve default; human on stage)",
        }
    return manifest
