"""Reachability view over one serialized world-state snapshot.

The invariants evaluate as reachability queries over the state graph
(objective spec §5.2). The base graph comes from the store's generic
backend (``StateGraphBackend``: ``nodes()`` / ``edges()`` /
``reachable_nodes()``, handoff doc §2.3). The handoff doc documents which
snapshot fields are reference relationships (§3: an object's ``location``
and ``contains_material``, a bucket's ``grants``, a credential's
``material_id``, a firewall rule's ``reaches``, host/group membership, a
ticket's ``audit_record_id``). The default backend materializes only a
subset of those (no Credential/Host/HostGroup/Ticket/RoleAttachment nodes,
and grant edges only for ``read`` perms). This view therefore augments the
backend's graph with the remaining documented reference edges, derived
mechanically from the serialized snapshot — the oracle's own input surface
— never from the store's code.

Node-id conventions follow the backend's observed scheme
(``<label-prefix>:<entity-id>``); augmented entity kinds get their own
prefixes.
"""

from __future__ import annotations

import json
from collections import deque
from typing import Callable, Iterable, Mapping

from carl_ops_state import InMemoryStateGraph, StateGraphBackend, WorldState

BackendFactory = Callable[[], StateGraphBackend]

_READ_PERMS = frozenset({"read", "get", "list", "head", "describe"})


def _bucket_id(name: str) -> str:
    return f"bucket:{name}"


def _principal_id(pid: str) -> str:
    return f"principal:{pid}"


def _material_id(mid: str) -> str:
    return f"material:{mid}"


def _object_id(oid: str) -> str:
    return f"object:{oid}"


def _credential_id(ref: str) -> str:
    return f"credential:{ref}"


def _host_id(hid: str) -> str:
    return f"host:{hid}"


def _hostgroup_id(name: str) -> str:
    return f"hostgroup:{name}"


def _role_id(name: str) -> str:
    return f"role:{name}"


def _attachment_id(rid: str) -> str:
    return f"attachment:{rid}"


def _ticket_id(tid: str) -> str:
    return f"ticket:{tid}"


def _audit_id(aid: str) -> str:
    return f"auditrecord:{aid}"


def _endpoint_id(dest: str) -> str:
    return f"endpoint:{dest}"


class SnapshotGraphView:
    """One snapshot, materialized as a labelled graph plus its parsed form."""

    def __init__(
        self,
        state: WorldState,
        backend_factory: BackendFactory | None = None,
    ) -> None:
        self.state = state
        self.data: Mapping[str, object] = json.loads(state.to_canonical())
        backend = (backend_factory or InMemoryStateGraph)()
        backend.load(state)
        self._nodes: dict[str, tuple[str, dict]] = {}
        self._edges: set[tuple[str, str, str]] = set()
        for nid, label, props in backend.nodes():
            self._nodes[nid] = (label, dict(props))
        for src, rel, dst in backend.edges():
            self._edges.add((src, rel, dst))
        self._augment()

    # -- construction -----------------------------------------------------

    def _add_node(self, nid: str, label: str, props: dict | None = None) -> None:
        if nid not in self._nodes:
            self._nodes[nid] = (label, props or {})

    def _add_edge(self, src: str, rel: str, dst: str) -> None:
        self._edges.add((src, rel, dst))

    def _augment(self) -> None:
        d = self.data
        bucket_names = {b["name"] for b in d.get("buckets", [])}
        object_ids = {o["id"] for o in d.get("objects", [])}

        for b in d.get("buckets", []):
            self._add_node(_bucket_id(b["name"]), "Bucket", {"region": b["region"]})
            for grant in b.get("grants", []):
                self._add_node(_principal_id(grant["principal"]), "Principal", {})
                for perm in grant.get("perms", []):
                    self._add_edge(
                        _bucket_id(b["name"]),
                        f"GRANTS_{str(perm).upper()}",
                        _principal_id(grant["principal"]),
                    )

        for p in d.get("principals", []):
            self._add_node(
                _principal_id(p["id"]), "Principal", {"namespace": p["namespace"]}
            )

        for m in d.get("materials", []):
            self._add_node(
                _material_id(m["id"]),
                "CredentialMaterial",
                {"origin": m["origin_cred_ref"]},
            )

        for o in d.get("objects", []):
            self._add_node(_object_id(o["id"]), "Object", {"location": o["location"]})
            if o.get("contains_material"):
                self._add_edge(
                    _material_id(o["contains_material"]),
                    "EXPOSED_VIA",
                    _object_id(o["id"]),
                )
            loc = o["location"]
            if loc in bucket_names:
                self._add_edge(_object_id(o["id"]), "IN_BUCKET", _bucket_id(loc))
            elif loc in object_ids:
                self._add_edge(_object_id(o["id"]), "IN_BUCKET", _object_id(loc))

        for c in d.get("credentials", []):
            self._add_node(
                _credential_id(c["ref"]),
                "Credential",
                {"expiry": c["expiry"], "rotated": c["rotated"]},
            )
            self._add_edge(
                _credential_id(c["ref"]), "HAS_MATERIAL", _material_id(c["material_id"])
            )
            if c.get("host"):
                self._add_edge(
                    _host_id(c["host"]), "HAS_CREDENTIAL", _credential_id(c["ref"])
                )

        for g in d.get("host_groups", []):
            self._add_node(_hostgroup_id(g["name"]), "HostGroup", {"tags": g["tags"]})

        for h in d.get("hosts", []):
            self._add_node(_host_id(h["id"]), "Host", {"tags": h["tags"]})
            self._add_edge(_hostgroup_id(h["group"]), "CONTAINS_HOST", _host_id(h["id"]))
            for ref in h.get("credential_refs", []):
                self._add_edge(_host_id(h["id"]), "HAS_CREDENTIAL", _credential_id(ref))

        for r in d.get("roles", []):
            self._add_node(_role_id(r), "Role", {})

        for ra in d.get("role_attachments", []):
            self._add_node(_attachment_id(ra["id"]), "RoleAttachment", {})
            self._add_edge(
                _principal_id(ra["principal"]), "HAS_ATTACHMENT", _attachment_id(ra["id"])
            )
            self._add_edge(_attachment_id(ra["id"]), "FOR_ROLE", _role_id(ra["role"]))
            if ra.get("target"):
                self._add_edge(
                    _attachment_id(ra["id"]), "ON_TARGET", _hostgroup_id(ra["target"])
                )

        for fr in d.get("firewall_rules", []):
            fid = f"firewall:{fr['id']}"
            self._add_node(
                fid,
                "FirewallRule",
                {"cidr": fr["cidr"], "port": fr["port"], "direction": fr["direction"]},
            )
            reaches = fr.get("reaches")
            if reaches:
                if reaches in bucket_names:
                    dst = _bucket_id(reaches)
                elif reaches in object_ids:
                    dst = _object_id(reaches)
                else:
                    self._add_node(_endpoint_id(reaches), "Endpoint", {"dest": reaches})
                    dst = _endpoint_id(reaches)
                self._add_edge(fid, "REACHES", dst)

        for t in d.get("tickets", []):
            self._add_node(
                _ticket_id(t["id"]),
                "Ticket",
                {"status": t["status"], "resolution": t["resolution"]},
            )
            if t.get("audit_record_id"):
                self._add_edge(
                    _ticket_id(t["id"]), "HAS_AUDIT", _audit_id(t["audit_record_id"])
                )

        for a in d.get("audit_records", []):
            self._add_node(_audit_id(a["id"]), "AuditRecord", {"target": a["target"]})

    # -- queries ----------------------------------------------------------

    def nodes(self) -> Iterable[tuple[str, str, dict]]:
        for nid in sorted(self._nodes):
            label, props = self._nodes[nid]
            yield nid, label, props

    def edges(self) -> Iterable[tuple[str, str, str]]:
        return iter(sorted(self._edges))

    def label(self, nid: str) -> str | None:
        entry = self._nodes.get(nid)
        return entry[0] if entry else None

    def props(self, nid: str) -> dict:
        entry = self._nodes.get(nid)
        return entry[1] if entry else {}

    def nodes_with_label(self, label: str) -> list[str]:
        return sorted(n for n, (lbl, _) in self._nodes.items() if lbl == label)

    def reachable_nodes(self, start: str, rels: set[str] | None = None) -> set[str]:
        """Forward reachability from ``start``, optionally restricted to
        edge relations ``rels``. Deterministic BFS; excludes ``start``."""
        adjacency: dict[str, list[str]] = {}
        for src, rel, dst in sorted(self._edges):
            if rels is not None and rel not in rels:
                continue
            adjacency.setdefault(src, []).append(dst)
        seen: set[str] = set()
        queue: deque[str] = deque([start])
        while queue:
            cur = queue.popleft()
            for nxt in adjacency.get(cur, []):
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append(nxt)
        return seen


def is_read_only_perm(perm: str) -> bool:
    return perm.lower() in _READ_PERMS
