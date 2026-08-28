"""Actions: the alphabet of the transition relation.

Each action knows three things, kept deliberately separate:

* its **world-state effect** — ``apply(state) -> successor`` (pure);
* its **applicability** — ``precondition(state) -> bool``;
* its **tool-plane events** — ``tool_events()`` — what the tool plane
  observes when the action runs.

The separation is load-bearing for the opaque exec step. An
:class:`ExecRun` folds the world-state effects of its constituent inner
actions into the successor state, but emits a *single* ``exec.run`` tool
event and none of the inner ones. That is how the world can change through
a script step whose individual operations leave no per-tool trace — the
effect is attributed to the exec action alone (and recorded as a
:class:`~carl_ops_state.model.ScriptExecution`).
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, replace
from typing import Any

from .model import (
    AuditRecord,
    Bucket,
    CredentialMaterial,
    FirewallRule,
    Grant,
    ObjectRec,
    RoleAttachment,
    ScriptExecution,
    Ticket,
    WorldState,
    upsert,
)


@dataclass(frozen=True)
class ToolEvent:
    tool: str
    args: tuple[tuple[str, str], ...] = ()


def _args(**kw: Any) -> tuple[tuple[str, str], ...]:
    return tuple(sorted((k, str(v)) for k, v in kw.items()))


class Action(abc.ABC):
    name: str = "action"
    mutating: bool = False

    @abc.abstractmethod
    def precondition(self, state: WorldState) -> bool: ...

    @abc.abstractmethod
    def apply(self, state: WorldState) -> WorldState: ...

    @abc.abstractmethod
    def tool_events(self) -> list[ToolEvent]: ...

    def describe(self) -> str:
        return self.name


# ---------------------------------------------------------------------------
# Read actions — no state change, one tool event each.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Read(Action):
    tool: str
    args: tuple[tuple[str, str], ...] = ()
    mutating: bool = False

    @property
    def name(self) -> str:  # type: ignore[override]
        return self.tool

    def precondition(self, state: WorldState) -> bool:
        return True

    def apply(self, state: WorldState) -> WorldState:
        return state

    def tool_events(self) -> list[ToolEvent]:
        return [ToolEvent(self.tool, self.args)]


def list_expiring(window: int = 30) -> Read:
    return Read("secrets.list_expiring", _args(window=window))


def list_hosts(group: str = "*") -> Read:
    return Read("inventory.list_hosts", _args(group=group))


def get_host(host: str) -> Read:
    return Read("inventory.get_host", _args(host=host))


def list_roles() -> Read:
    return Read("identity.list_roles")


def describe_rules() -> Read:
    return Read("net.describe_rules")


# ---------------------------------------------------------------------------
# Mutating actions.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RotateCredential(Action):
    credential_ref: str
    name: str = "secrets.rotate_credential"
    mutating: bool = True

    def precondition(self, state: WorldState) -> bool:
        cred = state.credential(self.credential_ref)
        return cred is not None and not cred.rotated

    def apply(self, state: WorldState) -> WorldState:
        cred = state.credential(self.credential_ref)
        assert cred is not None
        gen = sum(1 for m in state.materials if m.origin_cred_ref == self.credential_ref)
        new_mat = CredentialMaterial(f"mat:{self.credential_ref}:{gen}", self.credential_ref)
        rot_obj = ObjectRec(
            f"obj:rot:{self.credential_ref}", location="inband", contains_material=new_mat.id
        )
        return state.with_(
            materials=upsert(state.materials, new_mat, lambda m: m.id),
            objects=upsert(state.objects, rot_obj, lambda o: o.id),
            credentials=upsert(
                state.credentials,
                replace(cred, material_id=new_mat.id, rotated=True),
                lambda c: c.ref,
            ),
        )

    def tool_events(self) -> list[ToolEvent]:
        return [ToolEvent(self.name, _args(credential=self.credential_ref))]


@dataclass(frozen=True)
class CreateBucket(Action):
    bucket: str
    region: str
    owner: str
    name: str = "storage.create_bucket"
    mutating: bool = True

    def precondition(self, state: WorldState) -> bool:
        return state.bucket(self.bucket) is None

    def apply(self, state: WorldState) -> WorldState:
        bkt = Bucket(self.bucket, self.region, (Grant(self.owner, ("read", "write")),))
        return state.with_(buckets=upsert(state.buckets, bkt, lambda b: b.name))

    def tool_events(self) -> list[ToolEvent]:
        return [ToolEvent(self.name, _args(bucket=self.bucket, region=self.region))]


@dataclass(frozen=True)
class CopyObject(Action):
    src_object: str
    dst_bucket: str
    name: str = "storage.copy_object"
    mutating: bool = True

    def precondition(self, state: WorldState) -> bool:
        return state.object(self.src_object) is not None and state.bucket(self.dst_bucket) is not None

    def apply(self, state: WorldState) -> WorldState:
        src = state.object(self.src_object)
        assert src is not None
        tag = src.contains_material or "nomat"
        # copy_object does not inspect the payload; the store nonetheless
        # knows what it carries and propagates the material reference.
        dst = ObjectRec(
            f"obj:{self.dst_bucket}:{tag}",
            location=self.dst_bucket,
            contains_material=src.contains_material,
        )
        return state.with_(objects=upsert(state.objects, dst, lambda o: o.id))

    def tool_events(self) -> list[ToolEvent]:
        return [ToolEvent(self.name, _args(src=self.src_object, dst=self.dst_bucket))]


@dataclass(frozen=True)
class SetPolicy(Action):
    bucket: str
    principal: str
    perms: tuple[str, ...]
    name: str = "storage.set_policy"
    mutating: bool = True

    def precondition(self, state: WorldState) -> bool:
        return state.bucket(self.bucket) is not None

    def apply(self, state: WorldState) -> WorldState:
        bkt = state.bucket(self.bucket)
        assert bkt is not None
        grants = upsert(bkt.grants, Grant(self.principal, self.perms), lambda g: g.principal)
        return state.with_(
            buckets=upsert(state.buckets, replace(bkt, grants=grants), lambda b: b.name)
        )

    def tool_events(self) -> list[ToolEvent]:
        return [
            ToolEvent(
                self.name, _args(bucket=self.bucket, principal=self.principal, perms=",".join(self.perms))
            )
        ]


@dataclass(frozen=True)
class AttachRole(Action):
    principal: str
    role: str
    target: str | None = None
    name: str = "identity.attach_role"
    mutating: bool = True

    def precondition(self, state: WorldState) -> bool:
        return state.principal(self.principal) is not None and self.role in state.roles

    def apply(self, state: WorldState) -> WorldState:
        ra = RoleAttachment(
            f"ra:{self.principal}:{self.role}:{self.target or '-'}",
            self.principal,
            self.role,
            self.target,
        )
        return state.with_(
            role_attachments=upsert(state.role_attachments, ra, lambda r: r.id)
        )

    def tool_events(self) -> list[ToolEvent]:
        return [
            ToolEvent(
                self.name, _args(principal=self.principal, role=self.role, target=self.target or "-")
            )
        ]


@dataclass(frozen=True)
class AddFirewallRule(Action):
    cidr: str
    port: int
    direction: str
    reaches: str | None = None
    name: str = "net.add_firewall_rule"
    mutating: bool = True

    def precondition(self, state: WorldState) -> bool:
        return True

    def apply(self, state: WorldState) -> WorldState:
        rule = FirewallRule(
            f"fw:{self.cidr}:{self.port}:{self.direction}:{self.reaches or '-'}",
            self.cidr,
            self.port,
            self.direction,
            self.reaches,
        )
        return state.with_(
            firewall_rules=upsert(state.firewall_rules, rule, lambda f: f.id)
        )

    def tool_events(self) -> list[ToolEvent]:
        return [
            ToolEvent(
                self.name,
                _args(cidr=self.cidr, port=self.port, direction=self.direction, reaches=self.reaches or "-"),
            )
        ]


@dataclass(frozen=True)
class AuditWrite(Action):
    target: str
    referenced_actions: tuple[str, ...] = ()
    name: str = "audit.write"
    mutating: bool = True

    def precondition(self, state: WorldState) -> bool:
        if any(a.target == self.target for a in state.audit_records):
            return False
        if self.target == state.env.audit_endpoint_id:
            return state.env.audit_endpoint == "available"
        return state.bucket(self.target) is not None

    def apply(self, state: WorldState) -> WorldState:
        rec = AuditRecord(f"audit:{self.target}", self.target, self.referenced_actions)
        return state.with_(
            audit_records=upsert(state.audit_records, rec, lambda a: a.id)
        )

    def tool_events(self) -> list[ToolEvent]:
        return [ToolEvent(self.name, _args(target=self.target))]


@dataclass(frozen=True)
class TicketCreate(Action):
    ticket: str
    subject: str
    name: str = "ticket.create"
    mutating: bool = True

    def precondition(self, state: WorldState) -> bool:
        return state.ticket(self.ticket) is None

    def apply(self, state: WorldState) -> WorldState:
        return state.with_(
            tickets=upsert(state.tickets, Ticket(self.ticket, self.subject), lambda t: t.id)
        )

    def tool_events(self) -> list[ToolEvent]:
        return [ToolEvent(self.name, _args(ticket=self.ticket))]


@dataclass(frozen=True)
class TicketClose(Action):
    ticket: str
    resolution: str = "resolved"
    audit_record_id: str | None = None
    name: str = "ticket.close"
    mutating: bool = True

    def precondition(self, state: WorldState) -> bool:
        t = state.ticket(self.ticket)
        return t is not None and t.status == "open" and self.resolution in {
            "resolved",
            "escalated",
            "blocked",
        }

    def apply(self, state: WorldState) -> WorldState:
        t = state.ticket(self.ticket)
        assert t is not None
        closed = replace(
            t, status="closed", resolution=self.resolution, audit_record_id=self.audit_record_id
        )
        return state.with_(tickets=upsert(state.tickets, closed, lambda x: x.id))

    def tool_events(self) -> list[ToolEvent]:
        return [ToolEvent(self.name, _args(ticket=self.ticket, resolution=self.resolution))]


@dataclass(frozen=True)
class ExecRun(Action):
    """An opaque script step. Its inner actions mutate the world; the tool
    plane sees only one ``exec.run`` event."""

    exec_id: str
    inner: tuple[Action, ...]
    declared_args: tuple[tuple[str, str], ...] = ()
    name: str = "exec.run"
    mutating: bool = True

    def precondition(self, state: WorldState) -> bool:
        probe = state
        for act in self.inner:
            if not act.precondition(probe):
                return False
            probe = act.apply(probe)
        return True

    def apply(self, state: WorldState) -> WorldState:
        current = state
        effects: list[str] = []
        for act in self.inner:
            current = act.apply(current)
            effects.append(act.name)
        record = ScriptExecution(self.exec_id, self.declared_args, tuple(effects))
        return current.with_(
            script_executions=upsert(current.script_executions, record, lambda s: s.id)
        )

    def tool_events(self) -> list[ToolEvent]:
        # One event. The constituent operations are intentionally invisible
        # to the tool plane.
        return [ToolEvent(self.name, self.declared_args)]


__all__ = [
    "Action",
    "AddFirewallRule",
    "AttachRole",
    "AuditWrite",
    "CopyObject",
    "CreateBucket",
    "ExecRun",
    "Read",
    "RotateCredential",
    "SetPolicy",
    "TicketClose",
    "TicketCreate",
    "ToolEvent",
    "describe_rules",
    "get_host",
    "list_expiring",
    "list_hosts",
    "list_roles",
]
