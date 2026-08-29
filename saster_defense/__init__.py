"""W1 defense stack — five independently switchable layers.

L1 input classifier (LlamaGuard3-8B), L2 policy engine (OPA/Rego, stateless),
L3 trace monitor (SMT-over-finite-trace), L4 trajectory auditor (AgentDoG,
warn-level), L5 approval gate (HITL circuit breaker). Every external backend
is a config field with a labelled representative stand-in; every layer reports
unavailable distinctly; blocking charges a reroute against the budget.

Not in scope: the containment oracle, which is an independent evaluator and
must not share an input surface with the policy engine.
"""

from __future__ import annotations

from .budget import BudgetLedger
from .l1_classifier import ClassifierGuard
from .l2_policy import DeclaredScope, PolicyEngine, ladder
from .l3_trace import TraceMonitor, compile_count, compile_policy, reset_compile_cache
from .l4_auditor import TrajectoryAuditor
from .l5_approval import ApprovalGate, QueueApprover, auto_approve, auto_deny
from .stack import ActionResult, DefenseConfig, DefenseStack
from .types import ActionRequest, LayerName, LayerOutcome, Verdict

__all__ = [
    "ActionRequest",
    "LayerName",
    "LayerOutcome",
    "Verdict",
    "BudgetLedger",
    "ClassifierGuard",
    "PolicyEngine",
    "DeclaredScope",
    "ladder",
    "TraceMonitor",
    "compile_policy",
    "compile_count",
    "reset_compile_cache",
    "TrajectoryAuditor",
    "ApprovalGate",
    "QueueApprover",
    "auto_approve",
    "auto_deny",
    "DefenseStack",
    "DefenseConfig",
    "ActionResult",
]
