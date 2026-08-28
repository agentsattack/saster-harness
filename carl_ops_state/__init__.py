"""carl_ops_state — a deterministic world-state store for the carl-ops
IT-operations fixture.

This package is the fixture's mutable world model. It is deliberately kept
in a namespace separate from the trajectory corpus: the store holds the
artifact an oracle evaluates, and the oracle must not read from the same
namespace it grades.

Layers:

* :mod:`carl_ops_state.model` — entities and the serializable,
  content-addressable :class:`WorldState`.
* :mod:`carl_ops_state.actions` — the action alphabet, each carrying a pure
  world-state effect and its own tool-plane events.
* :mod:`carl_ops_state.transition` — the first-class transition relation:
  ``applicable_actions`` / ``apply`` plus reachability and the
  point-of-no-return primitive (invariants supplied by the caller).
* :mod:`carl_ops_state.graph` — in-memory (default) and optional Neo4j
  graph backends behind one interface.
* :mod:`carl_ops_state.run` — the snapshot/tool-event run driver.
* :mod:`carl_ops_state.fixture` — the carl-ops t0 state, the clean and
  obstructed environment declarations, and the reference paths.

No LLM, no clock, and no randomness appears anywhere in this component.
"""

from __future__ import annotations

from .actions import (
    Action,
    AddFirewallRule,
    AttachRole,
    AuditWrite,
    CopyObject,
    CreateBucket,
    ExecRun,
    Read,
    RotateCredential,
    SetPolicy,
    TicketClose,
    TicketCreate,
    ToolEvent,
)
from .graph import InMemoryStateGraph, Neo4jStateGraph, StateGraphBackend
from .model import (
    Bucket,
    Credential,
    CredentialMaterial,
    EnvironmentDeclaration,
    FirewallRule,
    ObjectRec,
    Principal,
    Scope,
    ScriptExecution,
    Ticket,
    WorldState,
)
from .run import RunResult, Snapshot, apply_path
from .transition import ActionUniverse, PreconditionError, TransitionRelation

__all__ = [
    "Action",
    "ActionUniverse",
    "AddFirewallRule",
    "AttachRole",
    "AuditWrite",
    "Bucket",
    "CopyObject",
    "CreateBucket",
    "Credential",
    "CredentialMaterial",
    "EnvironmentDeclaration",
    "ExecRun",
    "FirewallRule",
    "InMemoryStateGraph",
    "Neo4jStateGraph",
    "ObjectRec",
    "PreconditionError",
    "Principal",
    "Read",
    "RotateCredential",
    "RunResult",
    "Scope",
    "ScriptExecution",
    "SetPolicy",
    "Snapshot",
    "StateGraphBackend",
    "Ticket",
    "TicketClose",
    "TicketCreate",
    "ToolEvent",
    "TransitionRelation",
    "WorldState",
    "apply_path",
]
