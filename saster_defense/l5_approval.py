"""L5 — approval gate (human-in-the-loop circuit breaker).

Nothing HITL existed before this: the codebase's intervention queue is a
file-based control queue, not a consent gate. This is a real gate. Tier-2
actions escalate to an approver; the approver's decision determines whether
the action proceeds. For unattended sweeps the approver is scriptable
(auto-approve or auto-deny); on stage it is a human — something escalates, a
human approves, and the campaign proceeds. That is the circuit breaker the
abstract promises.

Verdicts: an approved escalation returns ``escalate`` (a recorded HITL event;
the action proceeds), a rejected escalation returns ``deny`` (blocks), a
sub-tier-2 action returns ``allow`` (not gated).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from .types import ActionRequest, LayerName, LayerOutcome, Verdict

Approver = Callable[[ActionRequest], bool]  # True == approve


def auto_approve(_request: ActionRequest) -> bool:
    """Scriptable auto-approve for unattended sweeps."""
    return True


def auto_deny(_request: ActionRequest) -> bool:
    return False


@dataclass
class QueueApprover:
    """A real gate for the demo: escalations land in a queue; a human (or a
    scripted decision) resolves each. Records what escalated so the stage
    circuit-breaker is auditable."""

    decisions: list[bool] = field(default_factory=list)
    escalated: list[ActionRequest] = field(default_factory=list)
    default: bool = True

    def __call__(self, request: ActionRequest) -> bool:
        self.escalated.append(request)
        if self.decisions:
            return self.decisions.pop(0)
        return self.default


@dataclass
class ApprovalGate:
    approver: Approver = auto_approve
    escalate_tier: int = 2
    available: bool = True

    def gate(self, request: ActionRequest) -> LayerOutcome:
        if not self.available:
            return LayerOutcome(
                LayerName.L5_APPROVAL, Verdict.UNAVAILABLE, ran=False,
                detail="approval gate unavailable",
            )
        if request.tier < self.escalate_tier:
            return LayerOutcome(
                LayerName.L5_APPROVAL, Verdict.ALLOW, ran=True,
                detail=f"tier {request.tier} < {self.escalate_tier}; not gated",
            )
        approved = self.approver(request)
        if approved:
            return LayerOutcome(
                LayerName.L5_APPROVAL, Verdict.ESCALATE, ran=True,
                rule_id="L5_tier2_gate",
                detail="tier-2 escalated to HITL; approved — proceeds",
            )
        return LayerOutcome(
            LayerName.L5_APPROVAL, Verdict.DENY, ran=True,
            rule_id="L5_tier2_gate",
            detail="tier-2 escalated to HITL; rejected — blocked",
        )
