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
    nodes: list[Node] = []
    edges: list[Edge] = []

    for m in state.materials:
        nodes.append((f"material:{m.id}", "CredentialMaterial", {"origin": m.origin_cred_ref}))
    for o in state.objects:
        nodes.append((f"object:{o.id}", "Object", {"location": o.location}))
    for b in state.buckets:
        nodes.append((f"bucket:{b.name}", "Bucket", {"region": b.region}))
    for p in state.principals:
        nodes.append((f"principal:{p.id}", "Principal", {"namespace": p.namespace}))
    for frule in state.firewall_rules:
        nodes.append(
            (
                f"firewall:{frule.id}",
                "FirewallRule",
                {"cidr": frule.cidr, "port": frule.port, "direction": frule.direction},
            )
        )

    bucket_names = {b.name for b in state.buckets}
    # Exposure edges flow from the material toward anyone who can read it.
    for o in state.objects:
        if o.contains_material is not None:
            edges.append((f"material:{o.contains_material}", "EXPOSED_VIA", f"object:{o.id}"))
        if o.location in bucket_names:
            edges.append((f"object:{o.id}", "IN_BUCKET", f"bucket:{o.location}"))
    for b in state.buckets:
        for grant in b.grants:
            if "read" in grant.perms:
                edges.append((f"bucket:{b.name}", "GRANTS_READ", f"principal:{grant.principal}"))
    for frule in state.firewall_rules:
        if frule.reaches in bucket_names:
            edges.append((f"bucket:{frule.reaches}", "REACHED_BY", f"firewall:{frule.id}"))

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
