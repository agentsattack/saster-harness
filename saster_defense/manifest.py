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

from . import agentdog
from .l1_classifier import LLAMAGUARD3_ATBENCH_RECALL
from .l2_policy import ALL_RULES
from .scope_lock import LOCK_RULES

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

#: The addendum to the prediction matrix. The matrix is CLOSED (sweep prompt
#: hard constraint 11); anything pre-registered after its closure — the
#: Class 4 golden trace, P17 — lives in the addendum under its OWN hash, on
#: the same mechanism: a required manifest field and a pinned test.
GRRCON_ADDENDUM_PATH = (
    Path(__file__).resolve().parents[1] / "docs" / "grrcon-test-matrix-addendum.md"
)

#: Required hash fields, each mapping to the function that recomputes it from
#: the committed bytes. Kept as a table so a pre-registered document cannot
#: be added to the manifest without also being validated.
_REQUIRED_HASH_FIELDS = {
    "grrcon_matrix_sha256": "the pre-registered prediction-matrix hash",
    "envelope_preregistration_sha256": (
        "the envelope-mass pre-registration hash (scoring method, candidate "
        "set, thresholds)"
    ),
    "grrcon_addendum_sha256": (
        "the prediction-matrix addendum hash (golden trace, marker units, "
        "predictions written after the matrix closed)"
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


def grrcon_addendum_sha256() -> str:
    """SHA-256 of the prediction-matrix addendum, as committed."""
    return hashlib.sha256(GRRCON_ADDENDUM_PATH.read_bytes()).hexdigest()


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

#: Run-level fields every cell manifest must carry (Stage 2). The hash
#: check above ties a run to its pre-registrations; this ties it to its
#: cell: which arm, which precondition, what budget, which analyst, what
#: reset semantics, how the widening route was chosen. The cell driver
#: calls it AFTER populating the fields (the Stage 2 audit found the hash
#: check called before them, so they were never validated).
_REQUIRED_RUN_FIELDS = {
    # CarlOpsMode values, as every corpus manifest since W7 records them.
    "fixture_mode": ("carl-ops-compromised", "carl-ops-induced"),
    "precondition_state": ("obstructed", "unobstructed"),
    "widening_route_policy": ("agent", "grant", "firewall"),
}
_REQUIRED_RUN_BLOCKS = ("budget", "analyst", "reset", "victim_model", "k")


def validate_run_manifest(manifest: dict[str, Any]) -> None:
    """Reject a cell manifest missing a run field, after :func:`validate_manifest`."""
    validate_manifest(manifest)
    for field, allowed in _REQUIRED_RUN_FIELDS.items():
        if manifest.get(field) not in allowed:
            raise ManifestError(
                f"manifest {field!r} must be one of {list(allowed)}; got {manifest.get(field)!r}"
            )
    for block in _REQUIRED_RUN_BLOCKS:
        if block not in manifest:
            raise ManifestError(f"manifest missing required run block {block!r}")
    budget = manifest["budget"]
    if not isinstance(budget, dict) or not isinstance(budget.get("cap"), int) or budget["cap"] <= 0:
        raise ManifestError("manifest budget.cap must be a positive int (the attack budget)")


#: Why each layer is real or a stand-in in THIS environment. Recorded so the
#: corpus is self-describing.
_STANDIN_REASONS = {
    "l1": "LlamaGuard3-8B weights not obtainable in this environment",
    "l4": "no AgentDoG endpoint configured; representative warn evaluator in use",
    "scope_lock": "opa binary or scope_lock.rego not available; python mirror in use",
    "judge": "no judge endpoint configured; representative scope-block judge in use",
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


def _l4_prompt_path(a: Any) -> Path:
    if a.prompt_style == "v1.5-coarse":
        return agentdog.V15_COARSE_PATH
    if a.prompt_style == "v1.5-unified":
        return agentdog.V15_UNIFIED_PATH
    return agentdog.TRAJECTORY_FINEGRAINED_PATH if a.fine_grained else agentdog.TRAJECTORY_BINARY_PATH


def _l4_prompt_template(a: Any) -> str:
    return "agentdog/" + str(_l4_prompt_path(a).relative_to(agentdog._HERE))


def build_manifest(stack: DefenseStack) -> dict[str, Any]:
    cfg = stack.config
    manifest: dict[str, Any] = {
        "fixture_id": stack.fixture_id,
        "grrcon_matrix_sha256": grrcon_matrix_sha256(),
        "envelope_preregistration_sha256": envelope_preregistration_sha256(),
        "grrcon_addendum_sha256": grrcon_addendum_sha256(),
        "traffic_plane": TRAFFIC_PLANE,
        "layers_enabled": {
            "l1": cfg.l1, "l2": cfg.l2, "l3": cfg.l3, "l4": cfg.l4, "l5": cfg.l5,
            "scope_lock": cfg.vendor_shaped, "judge": cfg.vendor_shaped,
        },
        "vendor_shaped": cfg.vendor_shaped,
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
        # A served classifier (2026-09-06, addendum §S): the model, endpoint,
        # risk and pins beside the status; ``healthy`` is the health check.
        manifest["l1"].update({
            "model": c.model, "endpoint": c.endpoint, "family": getattr(c, "family", None),
            "risk_name": getattr(c, "risk_name", None), "pins": dict(getattr(c, "pins", {}) or {}),
            "healthy": bool(getattr(c, "healthy", False)), "rendering": "wire form (F27)",
        })
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
            # What the observer was ASKED, hashed. The prompt and taxonomy are
            # AgentDoG's own, vendored verbatim; a record that does not say
            # which version it ran cannot be read against AgentDoG's published
            # fine-grained accuracy, which is P10's entire baseline.
            "fine_grained": a.fine_grained,
            "prompt_style": a.prompt_style,
            "prompt_template": _l4_prompt_template(a),
            "prompt_sha256": agentdog.sha256(_l4_prompt_path(a)),
            "max_tokens_effective": a.effective_max_tokens,
            "taxonomy_sha256": (
                agentdog.sha256(agentdog.TAXONOMY_FINEGRAINED_PATH)
                if a.fine_grained else None
            ),
            "agentdog_repo": agentdog.AGENTDOG_REPO,
            "agentdog_revision": agentdog.AGENTDOG_REVISION,
            "agentdog_prompt_version": agentdog.AGENTDOG_PROMPT_VERSION,
            # AgentDoG 1.0 ships the binary and fine-grained heads as SEPARATE
            # checkpoints, and the published fine-grained accuracies are the FG
            # head's. Asking a binary head for a label may still parse, and the
            # answer is not the quantity those numbers describe. Recorded so a
            # corpus never has to be taken on trust about which head answered.
            "observer_is_fine_grained_checkpoint": (
                a.observer_is_fine_grained_checkpoint
            ),
            "max_tokens": a.max_tokens,
            "temperature": a.temperature,
            **_status(not a.representative, "l4"),
        }
    if cfg.vendor_shaped and stack.scope_lock is not None and stack.judge is not None:
        lock, judge = stack.scope_lock, stack.judge
        manifest["scope_lock"] = {
            "role": "scope_lock",
            "backend": lock.backend,
            "policy_artifact": "scope_lock.rego",
            "semantics": "allow-list over declared destinations and identities; stateless per-action",
            "locked": lock.lock.as_data()["lock"],
            "rules": list(LOCK_RULES),
            **_status(not lock.representative, "scope_lock"),
        }
        manifest["judge"] = {
            "role": "per_action_judge",
            "model": judge.model,
            "endpoint": judge.endpoint,
            "backend": judge.backend,
            "sees_reasoning": False,
            "sees_history": False,
            "max_tokens": judge.max_tokens,
            "temperature": 0.0,
            "prompt_style": judge.prompt_style,
            "prompt_sha256": judge.prompt_sha256,
            **_status(not judge.representative, "judge"),
        }
        manifest["temporal_layer"] = None
    if cfg.l5 and stack.approval is not None:
        manifest["l5"] = {
            "role": "approval_gate",
            "escalate_tier": stack.approval.escalate_tier,
            "approver": "scriptable (auto-approve default; human on stage)",
            "backend_status": "real",  # a real gate, no external model needed
        }
    return manifest
