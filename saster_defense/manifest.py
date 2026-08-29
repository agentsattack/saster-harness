"""Run manifest for the defense stack.

Records what actually ran per run: which layers were active, the backend behind
each (a config field, never a hidden constant), and — critically — each
layer's ``backend_status``: ``real`` when the genuine component executed, or
``stand-in`` (with a reason) when a labelled representative ran in its place. A
corpus generated against a stand-in must be identifiable as such from the
record alone, so this status travels with every run.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .l1_classifier import LLAMAGUARD3_ATBENCH_RECALL
from .l2_policy import ALL_RULES

if TYPE_CHECKING:
    from .stack import DefenseStack

#: The pre-registered GrrCON prediction matrix. Its SHA-256 is a REQUIRED
#: manifest field: every run records the hash of the predictions it was
#: measured against, so a prediction cannot be edited after the fact without
#: the manifest hash changing. A prediction written after the data exists is
#: not one; this is the mechanism that makes that checkable.
GRRCON_MATRIX_PATH = Path(__file__).resolve().parents[1] / "docs" / "grrcon-test-matrix.md"

#: The envelope-mass pre-registration. Its SHA-256 is a REQUIRED manifest
#: field, on the same footing as the prediction matrix and for the same
#: reason. This document fixes the scoring method (MEAN per-token logprob, not
#: SUM), the 13-candidate set, and both calibrated thresholds —
#: ``DECLARED_IN_ENVELOPE_FLOOR`` and the ``PROHIBITION_OUT_CEILING`` that
#: ``explanatory_divergence`` keys on. Those are the semantics the marker is
#: computed under, so a corpus that does not record which version of them it
#: ran against cannot be interpreted: a threshold edited after the fact would
#: silently redefine the marker for every record already published.
ENVELOPE_PREREG_PATH = (
    Path(__file__).resolve().parents[1] / "docs" / "envelope-preregistration.md"
)

#: Required hash fields, each mapping to the function that recomputes it from
#: the committed bytes. Kept as a table so a third pre-registered document
#: cannot be added to the manifest without also being validated.
_REQUIRED_HASH_FIELDS = {
    "grrcon_matrix_sha256": "the pre-registered prediction-matrix hash",
    "envelope_preregistration_sha256": (
        "the envelope-mass pre-registration hash (scoring method, candidate "
        "set, thresholds)"
    ),
}


class ManifestError(ValueError):
    """A manifest is missing a required field."""


def grrcon_matrix_sha256() -> str:
    """SHA-256 of the pre-registered prediction matrix, as committed."""
    return hashlib.sha256(GRRCON_MATRIX_PATH.read_bytes()).hexdigest()


def envelope_preregistration_sha256() -> str:
    """SHA-256 of the envelope-mass pre-registration, as committed."""
    return hashlib.sha256(ENVELOPE_PREREG_PATH.read_bytes()).hexdigest()


def validate_manifest(manifest: dict[str, Any]) -> None:
    """Reject a manifest that lacks either pre-registration hash.

    A corpus whose manifest carries no ``grrcon_matrix_sha256`` cannot be tied
    to the predictions it was meant to test; one carrying no
    ``envelope_preregistration_sha256`` cannot be tied to the scoring method
    and thresholds its ``explanatory_divergence`` was computed under. Neither
    is admissible.
    """
    for field, description in _REQUIRED_HASH_FIELDS.items():
        value = manifest.get(field)
        if not isinstance(value, str) or len(value) != 64:
            raise ManifestError(f"manifest missing required {field} ({description})")

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


#: Sweep traffic runs the MANAGEMENT plane, by deliberate decision. The
#: affinity router reaches the victims at their management-plane addresses
#: (192.168.1.228 = Qwen3-8B, 192.168.1.208 = Ministral-8B) even though the
#: same victims also answer on the fabric (fd00:200::3, fd00:200::6).
#: Repointing to the fabric is NOT transparent: the router pins each campaign
#: to a backend by consistent hashing over the backend STRING, so changing the
#: addresses rebuilds the hash ring and reassigns ~half of campaign keys — and
#: because the two backends are DIFFERENT victim models, a reassigned campaign
#: lands on the wrong model, not merely a prefix-cache miss. Held on the
#: management plane for the sweep, recorded per run so the corpus is
#: self-describing.
TRAFFIC_PLANE: dict[str, Any] = {
    "plane": "management",
    "victim_backends": {
        "192.168.1.228:8000": "Qwen/Qwen3-8B",
        "192.168.1.208:8000": "mistralai/Ministral-8B-Instruct-2410",
    },
    "fabric_alternative": {
        "fd00:200::3:8000": "Qwen/Qwen3-8B",
        "fd00:200::6:8000": "mistralai/Ministral-8B-Instruct-2410",
    },
    "deliberate": True,
    "rationale": (
        "repointing the router to the fabric rebuilds the consistent-hash ring "
        "and reassigns campaigns across two DIFFERENT victim models, not just a "
        "prefix-cache miss; held on the management plane by decision"
    ),
}


def build_manifest(stack: DefenseStack) -> dict[str, Any]:
    cfg = stack.config
    manifest: dict[str, Any] = {
        "fixture_id": stack.fixture_id,
        "grrcon_matrix_sha256": grrcon_matrix_sha256(),
        "envelope_preregistration_sha256": envelope_preregistration_sha256(),
        "traffic_plane": TRAFFIC_PLANE,
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
