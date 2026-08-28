"""State-graph backends.

The store materializes a single snapshot as a directed graph and answers
reachability queries over it. The default backend is in-memory and pulls in
no database, so a public benchmark can run without one. A Neo4j backend
implements the same interface for callers that want to host the graph in a
database; it is optional and imported lazily.

The graph exposes generic access — nodes, edges, ``reachable_nodes`` — plus
a few obviously neutral convenience queries. It does **not** encode any
invariant: "material readable by a principal outside ``ops-*``" is a
composition a separately-authored oracle makes on top of these primitives
(e.g. filtering ``readers_of_material`` by principal namespace).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Protocol, runtime_checkable

from .model import WorldState

Node = tuple[str, str, dict[str, Any]]  # (id, label, props)
Edge = tuple[str, str, str]  # (src_id, rel, dst_id)


@runtime_checkable
class StateGraphBackend(Protocol):
    def load(self, state: WorldState) -> None: ...
    def nodes(self) -> Iterable[Node]: ...
    def edges(self) -> Iterable[Edge]: ...
    def reachable_nodes(self, start: str, rels: set[str] | None = None) -> set[str]: ...


def _build(state: WorldState) -> tuple[list[Node], list[Edge]]:
    """Materialize the full §3 projection of the handoff doc: every world
    entity is a node; every reference field between entities is an edge.

    ``env`` and ``scope`` are declarations, not world entities, and are not
    materialized; they remain readable on the snapshot itself. An edge is
    emitted only when its referent entity exists in the snapshot — a
    dangling reference stays visible as the holder's property, never as an
    edge to a node that ``nodes()`` does not report.
    """
    nodes: list[Node] = []
    edges: list[Edge] = []

    for hg in state.host_groups:
        nodes.append((f"hostgroup:{hg.name}", "HostGroup", {"tags": list(hg.tags)}))
    for h in state.hosts:
        nodes.append((f"host:{h.id}", "Host", {"tags": list(h.tags)}))
    for m in state.materials:
        nodes.append((f"material:{m.id}", "CredentialMaterial", {"origin": m.origin_cred_ref}))
    for c in state.credentials:
        nodes.append(
            (
                f"credential:{c.ref}",
                "Credential",
                {"expiry": c.expiry, "rotated": c.rotated},
            )
        )
    for o in state.objects:
        nodes.append((f"object:{o.id}", "Object", {"location": o.location}))
    for b in state.buckets:
        nodes.append((f"bucket:{b.name}", "Bucket", {"region": b.region}))
    for p in state.principals:
        nodes.append((f"principal:{p.id}", "Principal", {"namespace": p.namespace}))
    for role in state.roles:
        nodes.append((f"role:{role}", "Role", {}))
    for ra in state.role_attachments:
        nodes.append((f"roleattachment:{ra.id}", "RoleAttachment", {}))
    for frule in state.firewall_rules:
        props: dict[str, Any] = {
            "cidr": frule.cidr,
            "port": frule.port,
            "direction": frule.direction,
        }
        if frule.reaches is not None:
            props["reaches"] = frule.reaches
        nodes.append((f"firewall:{frule.id}", "FirewallRule", props))
    for t in state.tickets:
        tprops: dict[str, Any] = {"subject": t.subject, "status": t.status}
        if t.resolution is not None:
            tprops["resolution"] = t.resolution
        nodes.append((f"ticket:{t.id}", "Ticket", tprops))
    for ar in state.audit_records:
        nodes.append(
            (
                f"auditrecord:{ar.id}",
                "AuditRecord",
                {"target": ar.target, "referenced_actions": list(ar.referenced_actions)},
            )
        )
    for se in state.script_executions:
        nodes.append(
            (
                f"scriptexec:{se.id}",
                "ScriptExecution",
                {
                    "declared_args": [f"{k}={v}" for k, v in se.declared_args],
                    "effects": list(se.effects),
                },
            )
        )

    group_names = {hg.name for hg in state.host_groups}
    host_ids = {h.id for h in state.hosts}
    credential_refs = {c.ref for c in state.credentials}
    material_ids = {m.id for m in state.materials}
    bucket_names = {b.name for b in state.buckets}
    object_ids = {o.id for o in state.objects}
    principal_ids = {p.id for p in state.principals}
    role_names = set(state.roles)
    audit_ids = {ar.id for ar in state.audit_records}

    for hg in state.host_groups:
        for role in hg.roles:
            if role in role_names:
                edges.append((f"hostgroup:{hg.name}", "HAS_ROLE", f"role:{role}"))
    for h in state.hosts:
        if h.group in group_names:
            edges.append((f"host:{h.id}", "IN_GROUP", f"hostgroup:{h.group}"))
        for role in h.roles:
            if role in role_names:
                edges.append((f"host:{h.id}", "HAS_ROLE", f"role:{role}"))
        for ref in h.credential_refs:
            if ref in credential_refs:
                edges.append((f"host:{h.id}", "HAS_CREDENTIAL", f"credential:{ref}"))
    for c in state.credentials:
        if c.material_id in material_ids:
            edges.append((f"credential:{c.ref}", "HAS_MATERIAL", f"material:{c.material_id}"))
        if c.host is not None and c.host in host_ids:
            edges.append((f"credential:{c.ref}", "ON_HOST", f"host:{c.host}"))
    # Exposure edges flow from the material toward anyone who can read it.
    for o in state.objects:
        if o.contains_material is not None and o.contains_material in material_ids:
            edges.append((f"material:{o.contains_material}", "EXPOSED_VIA", f"object:{o.id}"))
        if o.location in bucket_names:
            edges.append((f"object:{o.id}", "IN_BUCKET", f"bucket:{o.location}"))
        elif o.location in object_ids:
            edges.append((f"object:{o.id}", "IN_BUCKET", f"object:{o.location}"))
    for b in state.buckets:
        for grant in b.grants:
            if grant.principal not in principal_ids:
                continue
            for perm in grant.perms:
                edges.append(
                    (
                        f"bucket:{b.name}",
                        f"GRANTS_{perm.upper()}",
                        f"principal:{grant.principal}",
                    )
                )
    for ra in state.role_attachments:
        if ra.principal in principal_ids:
            edges.append(
                (f"principal:{ra.principal}", "HAS_ATTACHMENT", f"roleattachment:{ra.id}")
            )
        if ra.role in role_names:
            edges.append((f"roleattachment:{ra.id}", "FOR_ROLE", f"role:{ra.role}"))
        if ra.target is not None and ra.target in group_names:
            edges.append((f"roleattachment:{ra.id}", "ON_TARGET", f"hostgroup:{ra.target}"))
    for frule in state.firewall_rules:
        if frule.reaches is None:
            continue
        if frule.reaches in bucket_names:
            edges.append((f"firewall:{frule.id}", "REACHES", f"bucket:{frule.reaches}"))
            edges.append((f"bucket:{frule.reaches}", "REACHED_BY", f"firewall:{frule.id}"))
        elif frule.reaches in object_ids:
            edges.append((f"firewall:{frule.id}", "REACHES", f"object:{frule.reaches}"))
        elif frule.reaches in host_ids:
            edges.append((f"firewall:{frule.id}", "REACHES", f"host:{frule.reaches}"))
    for t in state.tickets:
        if t.audit_record_id is not None and t.audit_record_id in audit_ids:
            edges.append(
                (f"ticket:{t.id}", "EVIDENCED_BY", f"auditrecord:{t.audit_record_id}")
            )
    for ar in state.audit_records:
        if ar.target in bucket_names:
            edges.append((f"auditrecord:{ar.id}", "TARGETS", f"bucket:{ar.target}"))

    return nodes, edges


class InMemoryStateGraph:
    """Default backend. Builds an adjacency map from a snapshot."""

    def __init__(self, state: WorldState | None = None) -> None:
        self._nodes: list[Node] = []
        self._edges: list[Edge] = []
        self._adj: dict[str, list[tuple[str, str]]] = {}
        if state is not None:
            self.load(state)

    def load(self, state: WorldState) -> None:
        self._nodes, self._edges = _build(state)
        adj: dict[str, list[tuple[str, str]]] = {}
        for src, rel, dst in self._edges:
            adj.setdefault(src, []).append((rel, dst))
        self._adj = adj

    def nodes(self) -> Iterable[Node]:
        return list(self._nodes)

    def edges(self) -> Iterable[Edge]:
        return list(self._edges)

    def reachable_nodes(self, start: str, rels: set[str] | None = None) -> set[str]:
        seen: set[str] = set()
        stack = [start]
        while stack:
            node = stack.pop()
            for rel, dst in self._adj.get(node, ()):
                if rels is not None and rel not in rels:
                    continue
                if dst not in seen:
                    seen.add(dst)
                    stack.append(dst)
        return seen

    # -- neutral convenience queries --------------------------------------
    def buckets_holding_material(self, material_id: str) -> set[str]:
        reached = self.reachable_nodes(
            f"material:{material_id}", {"EXPOSED_VIA", "IN_BUCKET"}
        )
        return {n[len("bucket:") :] for n in reached if n.startswith("bucket:")}

    def readers_of_material(self, material_id: str) -> set[str]:
        reached = self.reachable_nodes(f"material:{material_id}")
        return {n[len("principal:") :] for n in reached if n.startswith("principal:")}

    def firewall_rules_reaching(self, bucket: str) -> set[str]:
        reached = self.reachable_nodes(f"bucket:{bucket}", {"REACHED_BY"})
        return {n[len("firewall:") :] for n in reached if n.startswith("firewall:")}


class Neo4jStateGraph:
    """Optional Neo4j-hosted backend behind the same interface.

    The snapshot is written under a caller-chosen namespace label so the
    oracle's graph never shares storage with the trajectory corpus. Requires
    the ``neo4j`` driver; construction fails clearly if it is absent. Not
    exercised by the benchmark suite, which runs entirely in memory.
    """

    def __init__(self, uri: str, auth: tuple[str, str], namespace: str = "carl_ops_state") -> None:
        try:
            from neo4j import GraphDatabase  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "Neo4jStateGraph requires the 'neo4j' driver; the in-memory "
                "backend is the default and needs no database."
            ) from exc
        self._driver = GraphDatabase.driver(uri, auth=auth)
        self._ns = namespace

    def load(self, state: WorldState) -> None:  # pragma: no cover - needs a DB
        nodes, edges = _build(state)
        label = self._ns
        with self._driver.session() as session:
            session.run(f"MATCH (n:`{label}`) DETACH DELETE n")
            for nid, ntype, props in nodes:
                session.run(
                    f"CREATE (n:`{label}` {{gid:$gid, ntype:$ntype}}) SET n += $props",
                    gid=nid,
                    ntype=ntype,
                    props=props,
                )
            for src, rel, dst in edges:
                session.run(
                    f"MATCH (a:`{label}` {{gid:$src}}), (b:`{label}` {{gid:$dst}}) "
                    f"CREATE (a)-[:`{rel}`]->(b)",
                    src=src,
                    dst=dst,
                )

    def nodes(self) -> Iterable[Node]:  # pragma: no cover - needs a DB
        with self._driver.session() as session:
            rows = session.run(
                f"MATCH (n:`{self._ns}`) RETURN n.gid AS gid, n.ntype AS ntype, properties(n) AS props"
            )
            return [(r["gid"], r["ntype"], dict(r["props"])) for r in rows]

    def edges(self) -> Iterable[Edge]:  # pragma: no cover - needs a DB
        with self._driver.session() as session:
            rows = session.run(
                f"MATCH (a:`{self._ns}`)-[r]->(b:`{self._ns}`) "
                f"RETURN a.gid AS src, type(r) AS rel, b.gid AS dst"
            )
            return [(r["src"], r["rel"], r["dst"]) for r in rows]

    def reachable_nodes(
        self, start: str, rels: set[str] | None = None
    ) -> set[str]:  # pragma: no cover - needs a DB
        rel_filter = ""
        if rels:
            rel_filter = ":" + "|".join(f"`{r}`" for r in rels)
        with self._driver.session() as session:
            rows = session.run(
                f"MATCH (a:`{self._ns}` {{gid:$start}})-[{rel_filter}*1..]->(b:`{self._ns}`) "
                f"RETURN DISTINCT b.gid AS gid",
                start=start,
            )
            return {r["gid"] for r in rows}

    def close(self) -> None:  # pragma: no cover - needs a DB
        self._driver.close()


__all__ = [
    "Edge",
    "InMemoryStateGraph",
    "Neo4jStateGraph",
    "Node",
    "StateGraphBackend",
]
