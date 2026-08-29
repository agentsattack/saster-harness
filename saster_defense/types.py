"""Core types for the W1 defense stack.

Five layers (L1 input classifier, L2 policy engine, L3 trace monitor, L4
trajectory auditor, L5 approval gate) each evaluate an agent's activity and
return a :class:`LayerOutcome`. Every layer is independently switchable and
every layer can report **unavailable** — a layer that did not run must never
aggregate as clean (the frozen trajectory schema rejects that encoding, so
the layers must emit it correctly).

Backend note. LlamaGuard3-8B (L1), an ``opa`` binary (L2), a z3 SMT solver
(L3), and AgentDoG-1.0-4B (L4) are all **config fields**, not constants; none
is available in this environment. Where a real backend would plug in, the
layer ships a deterministic, in-repo stand-in that implements the same
contract, so the sweep runs without the external dependency. Each stand-in is
labelled ``representative`` in code and recorded as such in the run manifest —
the dissociation under test is between architectural *classes*, not between
two specific repos.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Verdict(str, Enum):
    """Layer verdict vocabulary. ``allow``/``deny``/``error``/``unavailable``
    are the frozen policy-verdict enum (schema §5.1); ``warn`` is added for
    non-blocking auditor layers, and ``escalate`` for the approval gate."""

    ALLOW = "allow"
    DENY = "deny"
    WARN = "warn"
    ESCALATE = "escalate"
    ERROR = "error"
    UNAVAILABLE = "unavailable"


#: The subset that is a legal frozen policy_verdict (schema CLOSED enum). CVR
#: counts ``deny``; a value outside this set silently corrupts CVR, so L2's
#: emitted verdict is checked against exactly this set.
POLICY_VERDICT_VALUES = frozenset({"allow", "deny", "error", "unavailable"})


class LayerName(str, Enum):
    L1_CLASSIFIER = "l1_classifier"
    L2_POLICY = "l2_policy"
    L3_TRACE = "l3_trace"
    L4_AUDITOR = "l4_auditor"
    L5_APPROVAL = "l5_approval"


@dataclass(frozen=True)
class ActionRequest:
    """One action the agent wants to take, as a defense layer sees it.

    ``tier`` and ``mutating`` come from the store's TOOL_SURFACE. ``args`` are
    the tool arguments (e.g. ``cidr``/``reaches`` for a firewall rule,
    ``principal`` for a grant, ``src_object``/``dst_bucket`` for a copy)."""

    tool: str
    args: dict[str, Any] = field(default_factory=dict)
    tier: int = 0
    mutating: bool = False

    @classmethod
    def from_tool(cls, tool: str, tier: int = 0, mutating: bool = False, **args: Any) -> ActionRequest:
        return cls(tool=tool, args=dict(args), tier=tier, mutating=mutating)


@dataclass(frozen=True)
class LayerOutcome:
    """One layer's decision about one action (or the whole trajectory, for
    L4). ``ran`` distinguishes a layer that evaluated and found nothing from a
    layer that could not evaluate — the latter is ``unavailable``, never a
    silent ``allow``."""

    layer: LayerName
    verdict: Verdict
    ran: bool
    rule_id: str | None = None
    detail: str = ""

    @property
    def blocks(self) -> bool:
        """A blocking verdict — the action does not proceed as requested. Only
        ``deny`` blocks; ``escalate`` records a HITL event that was resolved in
        favour of proceeding (a human rejection surfaces as ``deny``)."""
        return self.verdict is Verdict.DENY

    @property
    def is_unavailable(self) -> bool:
        return self.verdict is Verdict.UNAVAILABLE or not self.ran

    def as_detection_entry(self, step_index: int) -> dict[str, Any] | None:
        """Render as one entry of the frozen trajectory record's detection
        list, or ``None`` when the layer produced no detection (allow/error —
        the schema has no clean/no-action ``ok`` entry).

        An unavailable layer emits severity ``unavailable`` and a null
        action_taken — the encoding the schema requires so it cannot collapse
        to clean."""
        if self.is_unavailable:
            return {
                "layer": self.layer.value,
                "step_index": step_index,
                "severity": "unavailable",
                "action_taken": None,
                "status": "unavailable",
            }
        action_taken = _ACTION_TAKEN.get(self.verdict)
        if action_taken is None:  # allow / error — no detection entry
            return None
        return {
            "layer": self.layer.value,
            "step_index": step_index,
            "severity": _SEVERITY.get(self.verdict, "info"),
            "action_taken": action_taken,
            "status": "ok",
        }


_ACTION_TAKEN: dict[Verdict, str | None] = {
    Verdict.ALLOW: None,
    Verdict.WARN: "warn",
    Verdict.DENY: "block",
    Verdict.ESCALATE: "escalate",
    Verdict.ERROR: None,
}

_SEVERITY: dict[Verdict, str] = {
    Verdict.WARN: "medium",
    Verdict.DENY: "high",
    Verdict.ESCALATE: "high",
}
