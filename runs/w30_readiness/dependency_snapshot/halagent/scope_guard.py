"""Scope guard — the allowlist enforcement point.

This is a first-class component, not a config flag. It sits in code between the
model's parsed decision and the tool handler (see tools.Dispatcher). It cannot
be relaxed by prompting because no part of it reads the model's output as
policy — it only inspects the concrete target of a resolved action.

Fail-closed rules:
  * An empty or unparseable allowlist raises ScopeConfigError at construction.
    The agent halts rather than defaulting open.
  * Unknown / unparseable targets are refused, not allowed.
  * A target of None means "no network destination" (a local action). That is
    allowed and recorded with reason `no-network-target`; there is nothing to
    scope. Network tools must always carry a concrete target.
"""
from __future__ import annotations

import ipaddress
import json
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlsplit


class ScopeConfigError(RuntimeError):
    """Raised when the allowlist is missing, empty, or unparseable — halt."""


@dataclass(frozen=True)
class ScopeDecision:
    allowed: bool
    reason: str
    target: Optional[str]
    matched: Optional[str] = None


def load_allowlist(path: str) -> list[str]:
    """Load an allowlist from a runtime-mounted file. Never baked into the image.

    Accepts either a JSON array of strings, or a JSON object {"allow": [...]}.
    Raises ScopeConfigError on anything unusable so the agent halts.
    """
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = fh.read()
    except OSError as exc:
        raise ScopeConfigError(f"cannot read allowlist at {path!r}: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ScopeConfigError(f"allowlist at {path!r} is not valid JSON: {exc}") from exc
    if isinstance(data, dict):
        data = data.get("allow", None)
    if not isinstance(data, list) or not all(isinstance(x, str) for x in data):
        raise ScopeConfigError(
            f"allowlist at {path!r} must be a JSON array of strings "
            f"(or an object with an 'allow' array)"
        )
    entries = [x.strip() for x in data if x.strip()]
    if not entries:
        raise ScopeConfigError(f"allowlist at {path!r} is empty — refusing to default open")
    return entries


def _host_of(target: str) -> Optional[str]:
    """Extract a bare host from a URL, host:port, or bare host/IP string."""
    t = target.strip()
    if not t:
        return None
    if "://" in t:
        host = urlsplit(t).hostname
        return host.lower() if host else None
    # Strip a trailing path if present on a bare authority ("host:port/x").
    authority = t.split("/", 1)[0]
    # IPv6 literal in brackets: [::1]:8080
    if authority.startswith("["):
        end = authority.find("]")
        if end != -1:
            return authority[1:end].lower()
        return None
    # host:port — but do not mangle a bare IPv6 (which has many colons).
    if authority.count(":") == 1:
        authority = authority.split(":", 1)[0]
    return authority.lower() or None


class ScopeGuard:
    def __init__(self, allowlist: list[str]):
        if not allowlist:
            raise ScopeConfigError("empty allowlist — refusing to default open")
        self._exact: set[str] = set()
        self._suffixes: list[str] = []          # from "*.example.com"
        self._networks: list[ipaddress._BaseNetwork] = []
        for entry in allowlist:
            self._add_entry(entry)
        if not (self._exact or self._suffixes or self._networks):
            raise ScopeConfigError("allowlist parsed to zero usable matchers — halt")

    def _add_entry(self, entry: str) -> Optional[str]:
        """Add one matcher. Returns the normalized entry if it was new, else None."""
        e = entry.strip().lower()
        if not e:
            return None
        if e.startswith("*."):
            suffix = e[1:]                       # ".example.com"
            if suffix in self._suffixes:
                return None
            self._suffixes.append(suffix)
            return e
        try:
            net = ipaddress.ip_network(e, strict=False)
            if net in self._networks:
                return None
            self._networks.append(net)
            return str(net)
        except ValueError:
            pass
        host = _host_of(e) or e
        if host in self._exact:
            return None
        self._exact.add(host)
        return host

    def populate(self, entries: list[str], source: str) -> list[str]:
        """Add challenge-scoped targets at runtime (default-deny stays in force).

        Returns the list of entries actually added (deduplicated/normalized) so
        the caller can log a scope_grant trajectory record showing exactly what
        the agent was authorized for, and when. `source` is informational.
        """
        added: list[str] = []
        for entry in entries or []:
            norm = self._add_entry(entry)
            if norm is not None:
                added.append(norm)
        return added

    def effective_size(self) -> int:
        return len(self._exact) + len(self._suffixes) + len(self._networks)

    def check(self, target: Optional[str]) -> ScopeDecision:
        if target is None:
            return ScopeDecision(True, "no-network-target", None)
        host = _host_of(target)
        if not host:
            return ScopeDecision(False, "unparseable-target", target)
        if host in self._exact:
            return ScopeDecision(True, "exact-match", target, host)
        for suffix in self._suffixes:
            if host.endswith(suffix):
                return ScopeDecision(True, "suffix-match", target, "*" + suffix)
        try:
            ip = ipaddress.ip_address(host)
            for net in self._networks:
                if ip in net:
                    return ScopeDecision(True, "cidr-match", target, str(net))
        except ValueError:
            pass
        return ScopeDecision(False, "not-in-allowlist", target)
