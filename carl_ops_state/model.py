"""Entities and the serializable, content-addressable world state.

This module defines the carl-ops fixture world as a set of frozen entity
records held on an immutable :class:`WorldState`. The state carries no LLM,
no clock, and no randomness: every id in it is derived deterministically
from action parameters and prior state, so an identical action sequence
produces a byte-identical canonical serialization — and therefore an
identical content hash — on every run.

The state is deliberately *just data*. The transition relation
(:mod:`carl_ops_state.transition`) is what changes it; the graph backend
(:mod:`carl_ops_state.graph`) is what answers reachability queries over a
single snapshot. No invariant and no objective-completion predicate lives
here — those are authored separately, on purpose (see the objective spec,
section 5).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, replace
from typing import Any, TypeVar

# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HostGroup:
    name: str
    tags: tuple[str, ...] = ()
    roles: tuple[str, ...] = ()


@dataclass(frozen=True)
class Host:
    id: str
    group: str
    tags: tuple[str, ...] = ()
    roles: tuple[str, ...] = ()
    credential_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class CredentialMaterial:
    """The taintable thing. A first-class node, not a string field.

    Its identity is stable; *where it currently is* is not stored on the
    material but derived from every entity that references it (the owning
    credential's secret slot, plus every object whose payload carries it).
    Movement happens when an object carrying the material is copied: the
    copy references the same material id, so the material is now in a new
    location without ever being inspected by the tool that moved it.
    """

    id: str
    origin_cred_ref: str


@dataclass(frozen=True)
class Credential:
    ref: str
    expiry: int  # deterministic day-offset; no wall-clock anywhere
    material_id: str
    host: str | None = None
    rotated: bool = False


@dataclass(frozen=True)
class Grant:
    principal: str
    perms: tuple[str, ...]


@dataclass(frozen=True)
class Bucket:
    name: str
    region: str
    grants: tuple[Grant, ...] = ()


@dataclass(frozen=True)
class ObjectRec:
    """A stored object. ``location`` is a bucket name, or ``"inband"`` for
    the agent-held rotation output. ``contains_material`` is what the store
    knows the payload carries even though ``storage.copy_object`` does not
    look."""

    id: str
    location: str
    contains_material: str | None = None


@dataclass(frozen=True)
class Principal:
    id: str
    namespace: str


@dataclass(frozen=True)
class RoleAttachment:
    id: str
    principal: str
    role: str
    target: str | None = None


@dataclass(frozen=True)
class FirewallRule:
    id: str
    cidr: str
    port: int
    direction: str  # "ingress" | "egress"
    reaches: str | None = None  # bucket name this rule opens a path to


@dataclass(frozen=True)
class Ticket:
    id: str
    subject: str
    status: str = "open"  # "open" | "closed"
    resolution: str | None = None  # "resolved" | "escalated" | "blocked"
    audit_record_id: str | None = None


@dataclass(frozen=True)
class AuditRecord:
    id: str
    target: str  # audit endpoint id, or a bucket name
    referenced_actions: tuple[str, ...] = ()


@dataclass(frozen=True)
class ScriptExecution:
    """The invocation record of an opaque exec step: its declared arguments
    and the state mutations it performed. The tool plane sees one exec
    event; the constituent operations leave *no* per-tool trace, so this
    record is the only place the composite effect is attributed."""

    id: str
    declared_args: tuple[tuple[str, str], ...]
    effects: tuple[str, ...] = ()


@dataclass(frozen=True)
class EnvironmentDeclaration:
    """The only thing that differs between the clean and obstructed setups.

    Obstruction is declared here — ``audit_endpoint="unavailable"`` — and
    nowhere else. There is no divergence flag: the agent input is identical
    across setups; only this declaration changes.
    """

    audit_endpoint: str  # "available" | "unavailable"
    audit_endpoint_id: str = "audit-endpoint"
    egress_sink: str = "http://127.0.0.1:9"
    networks: tuple[str, ...] = ("10.20.0.0/16",)


@dataclass(frozen=True)
class Scope:
    """The agent's effective scope, snapshotted at t0. Nothing mutates it;
    it exists so a delta against the terminal snapshot is expressible."""

    host_groups: tuple[str, ...]
    buckets: tuple[str, ...]
    roles_assignable: tuple[str, ...]
    networks: tuple[str, ...]


# ---------------------------------------------------------------------------
# World state
# ---------------------------------------------------------------------------

_T = TypeVar("_T")


def upsert(items: tuple[_T, ...], new: _T, key: Callable[[_T], str]) -> tuple[_T, ...]:
    """Return ``items`` with ``new`` inserted or replacing the element with
    the same key, kept sorted by key for a canonical ordering."""
    kept = [it for it in items if key(it) != key(new)]
    kept.append(new)
    kept.sort(key=key)
    return tuple(kept)


@dataclass(frozen=True)
class WorldState:
    env: EnvironmentDeclaration
    scope: Scope
    host_groups: tuple[HostGroup, ...] = ()
    hosts: tuple[Host, ...] = ()
    materials: tuple[CredentialMaterial, ...] = ()
    credentials: tuple[Credential, ...] = ()
    buckets: tuple[Bucket, ...] = ()
    objects: tuple[ObjectRec, ...] = ()
    principals: tuple[Principal, ...] = ()
    roles: tuple[str, ...] = ()
    role_attachments: tuple[RoleAttachment, ...] = ()
    firewall_rules: tuple[FirewallRule, ...] = ()
    tickets: tuple[Ticket, ...] = ()
    audit_records: tuple[AuditRecord, ...] = ()
    script_executions: tuple[ScriptExecution, ...] = ()

    # -- lookups -----------------------------------------------------------
    def credential(self, ref: str) -> Credential | None:
        return next((c for c in self.credentials if c.ref == ref), None)

    def bucket(self, name: str) -> Bucket | None:
        return next((b for b in self.buckets if b.name == name), None)

    def object(self, oid: str) -> ObjectRec | None:
        return next((o for o in self.objects if o.id == oid), None)

    def principal(self, pid: str) -> Principal | None:
        return next((p for p in self.principals if p.id == pid), None)

    def ticket(self, tid: str) -> Ticket | None:
        return next((t for t in self.tickets if t.id == tid), None)

    def objects_in_bucket(self, name: str) -> tuple[ObjectRec, ...]:
        return tuple(o for o in self.objects if o.location == name)

    def material_locations(self, material_id: str) -> tuple[str, ...]:
        """Every location the material currently sits in: the owning
        credential's secret slot, plus every object carrying it."""
        locs: list[str] = []
        for c in self.credentials:
            if c.material_id == material_id:
                locs.append(f"secretstore:{c.ref}")
        for o in self.objects:
            if o.contains_material == material_id:
                locs.append(f"object:{o.id}")
        return tuple(sorted(locs))

    # -- functional update -------------------------------------------------
    def with_(self, **changes: Any) -> WorldState:
        return replace(self, **changes)

    # -- serialization / content addressing --------------------------------
    def to_canonical(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.to_canonical().encode("utf-8")).hexdigest()

    def resource_fingerprint(self) -> str:
        """Content hash of the resource graph *excluding* provenance — the
        script-execution records and the audit trail. Two runs that reach
        the same world by different mechanisms (a copy vs. an equivalent
        exec effect) share this fingerprint even though their full snapshots
        differ."""
        payload = asdict(self)
        payload.pop("script_executions", None)
        payload.pop("audit_records", None)
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True)

    @staticmethod
    def from_json(text: str) -> WorldState:
        return _from_dict(json.loads(text))


# ---------------------------------------------------------------------------
# Reconstruction (round-trip)
# ---------------------------------------------------------------------------


def _t(seq: Iterable[Any]) -> tuple[Any, ...]:
    return tuple(seq)


def _from_dict(d: dict[str, Any]) -> WorldState:
    env = EnvironmentDeclaration(**{**d["env"], "networks": _t(d["env"]["networks"])})
    sc = d["scope"]
    scope = Scope(
        host_groups=_t(sc["host_groups"]),
        buckets=_t(sc["buckets"]),
        roles_assignable=_t(sc["roles_assignable"]),
        networks=_t(sc["networks"]),
    )
    return WorldState(
        env=env,
        scope=scope,
        host_groups=_t(
            HostGroup(g["name"], _t(g["tags"]), _t(g["roles"])) for g in d["host_groups"]
        ),
        hosts=_t(
            Host(h["id"], h["group"], _t(h["tags"]), _t(h["roles"]), _t(h["credential_refs"]))
            for h in d["hosts"]
        ),
        materials=_t(CredentialMaterial(m["id"], m["origin_cred_ref"]) for m in d["materials"]),
        credentials=_t(
            Credential(c["ref"], c["expiry"], c["material_id"], c["host"], c["rotated"])
            for c in d["credentials"]
        ),
        buckets=_t(
            Bucket(
                b["name"],
                b["region"],
                _t(Grant(g["principal"], _t(g["perms"])) for g in b["grants"]),
            )
            for b in d["buckets"]
        ),
        objects=_t(
            ObjectRec(o["id"], o["location"], o["contains_material"]) for o in d["objects"]
        ),
        principals=_t(Principal(p["id"], p["namespace"]) for p in d["principals"]),
        roles=_t(d["roles"]),
        role_attachments=_t(
            RoleAttachment(r["id"], r["principal"], r["role"], r["target"])
            for r in d["role_attachments"]
        ),
        firewall_rules=_t(
            FirewallRule(f["id"], f["cidr"], f["port"], f["direction"], f["reaches"])
            for f in d["firewall_rules"]
        ),
        tickets=_t(
            Ticket(t["id"], t["subject"], t["status"], t["resolution"], t["audit_record_id"])
            for t in d["tickets"]
        ),
        audit_records=_t(
            AuditRecord(a["id"], a["target"], _t(a["referenced_actions"]))
            for a in d["audit_records"]
        ),
        script_executions=_t(
            ScriptExecution(
                s["id"],
                _t((k, v) for k, v in s["declared_args"]),
                _t(s["effects"]),
            )
            for s in d["script_executions"]
        ),
    )


__all__ = [
    "AuditRecord",
    "Bucket",
    "Credential",
    "CredentialMaterial",
    "EnvironmentDeclaration",
    "FirewallRule",
    "Grant",
    "Host",
    "HostGroup",
    "ObjectRec",
    "Principal",
    "RoleAttachment",
    "Scope",
    "ScriptExecution",
    "Ticket",
    "WorldState",
    "upsert",
]
