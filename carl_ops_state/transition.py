"""The transition relation as a first-class object.

``TransitionRelation`` is not implied by any tool implementation. Given a
state it enumerates the applicable (mutating) action set, and ``apply``
maps a state and an action to a successor. On top of those two primitives
it offers reachability over the *state* graph — deduplicated by each
snapshot's content hash, so the search explores distinct world states
rather than enumerating trajectories.

Reachability takes the goal and the admissibility predicates as
parameters. The store ships neither an invariant nor an
objective-completion test; ``point_of_no_return`` is expressible here only
because the caller supplies both (see the objective spec: invariants are
authored separately from this store, on purpose).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .actions import (
    Action,
    AddFirewallRule,
    AttachRole,
    AuditWrite,
    CopyObject,
    CreateBucket,
    RotateCredential,
    SetPolicy,
    TicketClose,
)
from .model import WorldState

Predicate = Callable[[WorldState], bool]


@dataclass(frozen=True)
class ActionUniverse:
    """The finite parameter universe the fixture declares. Bounding the
    parameters keeps the successor relation finite, which is what makes
    reachability a terminating graph search."""

    candidate_buckets: tuple[tuple[str, str, str], ...] = ()  # (name, region, owner)
    candidate_principals: tuple[str, ...] = ()
    candidate_roles: tuple[str, ...] = ()
    candidate_cidrs: tuple[tuple[str, int, str], ...] = ()  # (cidr, port, direction)
    audit_endpoint_id: str = "audit-endpoint"


class PreconditionError(RuntimeError):
    """Raised when an action is applied to a state that does not satisfy its
    precondition — i.e. the path does not apply cleanly."""


class TransitionRelation:
    def __init__(self, universe: ActionUniverse | None = None) -> None:
        self.universe = universe or ActionUniverse()

    # -- core relation -----------------------------------------------------
    def apply(self, state: WorldState, action: Action) -> WorldState:
        if not action.precondition(state):
            raise PreconditionError(action.describe())
        return action.apply(state)

    def applicable_actions(self, state: WorldState) -> list[Action]:
        """The mutating action set applicable at ``state``. Read actions are
        state-invariant and excluded from the successor relation."""
        u = self.universe
        out: list[Action] = []

        for cred in state.credentials:
            if not cred.rotated:
                out.append(RotateCredential(cred.ref))

        for name, region, owner in u.candidate_buckets:
            if state.bucket(name) is None:
                out.append(CreateBucket(name, region, owner))

        for audit_target in (u.audit_endpoint_id, *(b.name for b in state.buckets)):
            act = AuditWrite(audit_target)
            if act.precondition(state):
                out.append(act)

        for bkt in state.buckets:
            granted = {g.principal for g in bkt.grants}
            for principal in u.candidate_principals:
                if principal not in granted:
                    out.append(SetPolicy(bkt.name, principal, ("read",)))

        targets: tuple[str | None, ...] = (None, *(b.name for b in state.buckets))
        attached = {ra.id for ra in state.role_attachments}
        for principal in u.candidate_principals:
            for role in u.candidate_roles:
                for target in targets:
                    ra = AttachRole(principal, role, target)
                    if ra.precondition(state) and f"ra:{principal}:{role}:{target or '-'}" not in attached:
                        out.append(ra)

        existing_fw = {f.id for f in state.firewall_rules}
        for cidr, port, direction in u.candidate_cidrs:
            for bkt in state.buckets:
                rid = f"fw:{cidr}:{port}:{direction}:{bkt.name}"
                if rid not in existing_fw:
                    out.append(AddFirewallRule(cidr, port, direction, reaches=bkt.name))

        existing_objs = {o.id for o in state.objects}
        for obj in state.objects:
            if obj.location == "inband" and obj.contains_material is not None:
                for bkt in state.buckets:
                    tag = obj.contains_material
                    if f"obj:{bkt.name}:{tag}" not in existing_objs:
                        out.append(CopyObject(obj.id, bkt.name))

        for ticket in state.tickets:
            if ticket.status == "open":
                out.append(TicketClose(ticket.id, "resolved"))
                out.append(TicketClose(ticket.id, "escalated"))

        return out

    # -- reachability ------------------------------------------------------
    def reachable(
        self,
        state: WorldState,
        is_goal: Predicate,
        is_admissible: Predicate | None = None,
        *,
        max_states: int = 200_000,
    ) -> bool:
        """True iff some admissible state satisfying ``is_goal`` is reachable
        from ``state`` through admissible states. Dedupes on content hash."""
        admissible = is_admissible or (lambda _s: True)
        if not admissible(state):
            return False
        seen: set[str] = {state.content_hash}
        frontier: list[WorldState] = [state]
        while frontier:
            current = frontier.pop()
            if is_goal(current):
                return True
            for action in self.applicable_actions(current):
                nxt = action.apply(current)
                digest = nxt.content_hash
                if digest in seen:
                    continue
                seen.add(digest)
                if admissible(nxt):
                    frontier.append(nxt)
            if len(seen) > max_states:
                raise RuntimeError("reachability state space exceeded bound")
        return False

    def first_unrecoverable_step(
        self,
        snapshots: list[WorldState],
        is_goal: Predicate,
        is_admissible: Predicate | None = None,
    ) -> int | None:
        """The point of no return: the first snapshot index from which no
        admissible continuation reaches ``is_goal``. ``None`` if every
        snapshot still has a saving continuation."""
        for index, snap in enumerate(snapshots):
            if not self.reachable(snap, is_goal, is_admissible):
                return index
        return None


__all__ = [
    "ActionUniverse",
    "PreconditionError",
    "Predicate",
    "TransitionRelation",
]
