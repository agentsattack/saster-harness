"""The composable defense stack.

Each layer is independently switchable (the ablation needs L2-only, L3-only,
L4-only, L3+L4, all, none). Per-action layers (L1, L2, L3, L5) evaluate each
action in order; L4 is a post-hoc trajectory auditor. When any per-action
layer blocks, the attacker reroutes and the budget ledger charges it — a
blocking layer is never free.

Every layer can report unavailable, and an unavailable layer is rendered as a
distinct detection entry (severity ``unavailable``, null action), never as a
clean pass — the encoding the frozen schema requires.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from .budget import BudgetLedger
from .l1_classifier import ClassifierGuard
from .l2_policy import DeclaredScope, PolicyEngine
from .l3_trace import TraceMonitor, TracePolicy, compile_policy
from .l4_auditor import TrajectoryAuditor
from .l5_approval import ApprovalGate, auto_approve
from .manifest import build_manifest
from .types import ActionRequest, LayerName, LayerOutcome, Verdict


@dataclass
class DefenseConfig:
    """Which layers are active. Every combination the ablation needs."""

    l1: bool = False
    l2: bool = False
    l3: bool = False
    l4: bool = False
    l5: bool = False

    @classmethod
    def none(cls) -> DefenseConfig:
        return cls()

    @classmethod
    def all_on(cls) -> DefenseConfig:
        return cls(l1=True, l2=True, l3=True, l4=True, l5=True)


@dataclass
class ActionResult:
    """The stack's decision for one submitted action."""

    request: ActionRequest
    outcomes: list[LayerOutcome]
    blocked: bool
    detection_entries: list[dict]


@dataclass
class DefenseStack:
    config: DefenseConfig
    fixture_id: str
    scope: DeclaredScope = field(default_factory=DeclaredScope)
    budget: BudgetLedger = field(default_factory=lambda: BudgetLedger(cap=1000))
    # component overrides (else built from config + scope)
    classifier: ClassifierGuard | None = None
    policy: PolicyEngine | None = None
    trace: TraceMonitor | None = None
    auditor: TrajectoryAuditor | None = None
    approval: ApprovalGate | None = None
    _step: int = 0

    def __post_init__(self) -> None:
        if self.config.l1 and self.classifier is None:
            self.classifier = ClassifierGuard()
        if self.config.l2 and self.policy is None:
            self.policy = PolicyEngine(scope=self.scope)
        if self.config.l3 and self.trace is None:
            policy: TracePolicy = compile_policy(self.fixture_id)
            self.trace = TraceMonitor(policy=policy)
        if self.config.l4 and self.auditor is None:
            self.auditor = TrajectoryAuditor()
        if self.config.l5 and self.approval is None:
            self.approval = ApprovalGate(approver=auto_approve)

    # -- per-action path ---------------------------------------------------

    def submit(self, request: ActionRequest) -> ActionResult:
        """Run the per-action layers against one action. Charges budget,
        charges a reroute if blocked, and (if not blocked) commits the action
        to the trace monitor."""
        self.budget.charge_action()
        step = self._step
        self._step += 1

        outcomes: list[LayerOutcome] = []
        if self.config.l1 and self.classifier is not None:
            outcomes.append(self.classifier.classify(request))
        if self.config.l2 and self.policy is not None:
            outcomes.append(self.policy.evaluate(request))
        if self.config.l3 and self.trace is not None:
            outcomes.append(self.trace.check(request))
        if self.config.l5 and self.approval is not None:
            outcomes.append(self.approval.gate(request))

        blocked = any(o.blocks for o in outcomes)
        if blocked:
            # The attacker reroutes and pays for it — a blocking layer is not
            # free. The action does not execute, so it is not committed.
            self.budget.charge_block_and_reroute()
        elif self.config.l3 and self.trace is not None:
            self.trace.commit(request)

        entries = [
            e for o in outcomes if (e := o.as_detection_entry(step)) is not None
        ]
        return ActionResult(request, outcomes, blocked, entries)

    # -- trajectory path (L4) ----------------------------------------------

    def audit_trajectory(self, event_records: Sequence[dict]) -> LayerOutcome:
        """Run the post-hoc auditor (L4). Off when L4 is disabled — reported
        as an explicitly unavailable layer, never a silent clean pass."""
        if not self.config.l4 or self.auditor is None:
            return LayerOutcome(
                LayerName.L4_AUDITOR, Verdict.UNAVAILABLE, ran=False,
                detail="L4 disabled in this config",
            )
        return self.auditor.audit(event_records)

    # -- manifest ----------------------------------------------------------

    def manifest(self) -> dict:
        return build_manifest(self)
