"""Generic, scope-gated recon tools: TCP port scan + HTTP/REST endpoint discovery.

These are the first *network-reaching* tools in the scaffold, so they are written
to the same invariant the guard promises: nothing outside the effective allowlist
is ever contacted. The Dispatcher already checks the single declared target once,
but these handlers can iterate over many concrete destinations (many ports, many
URL paths). So each handler **closes over the ScopeGuard and re-checks the host
itself**, and refuses out-of-scope work as data rather than trusting the one
up-front check. Two consequences worth stating:

  * `target_from` returns the *host* being probed, so the Dispatcher scopes it.
  * HTTP tools **do not follow redirects** — a 3xx is returned verbatim (status +
    Location). Auto-following is the classic way a request to an in-scope host
    silently lands on an out-of-scope one; the model must issue a fresh probe for
    the redirect target, which then passes back through the guard.

Everything here is Python stdlib only (socket, ssl, urllib) — no deps to install,
consistent with the "everything vendored / hostile network" build constraint.
"""
from __future__ import annotations

import json
import socket
import ssl
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Optional
from urllib.parse import urljoin, urlsplit

from .scope_guard import ScopeGuard
from .tools import Tool, ToolRegistry

# --- caps: this is a discovery instrument, not a stress tool -----------------
_MAX_PORTS = 1024
_MAX_PATHS = 200
_MAX_WORKERS = 32
_DEFAULT_CONNECT_TIMEOUT = 1.0        # seconds, per TCP connect
_DEFAULT_HTTP_TIMEOUT = 5.0           # seconds, per HTTP request
_BODY_SNIPPET = 2048                  # bytes of body kept per HTTP response
_BANNER_BYTES = 256                   # bytes read for a plaintext service banner

# Common service ports worth a first look. Ordered roughly by relevance to an
# API/web CTF; the model can override `ports` for anything specific.
_DEFAULT_PORTS = [
    80, 443, 8080, 8443, 8000, 8888, 3000, 5000, 5001, 8081, 9000, 9090,
    22, 21, 23, 25, 53, 110, 143, 3306, 5432, 6379, 27017, 9200, 11211,
    2375, 2376, 4000, 4200, 7000, 7070, 8008, 8090, 8501, 9443, 50000,
]
_PORTS_TLS = frozenset({443, 8443, 9443, 993, 995, 465, 636})
_SERVICE_HINTS = {
    21: "ftp", 22: "ssh", 23: "telnet", 25: "smtp", 53: "dns", 80: "http",
    110: "pop3", 143: "imap", 443: "https", 3306: "mysql", 5432: "postgres",
    6379: "redis", 8080: "http-alt", 8443: "https-alt", 9200: "elasticsearch",
    11211: "memcached", 27017: "mongodb", 2375: "docker", 2376: "docker-tls",
    9090: "prometheus/http", 5000: "http/flask", 3000: "http/node",
}

# Paths worth trying first when mapping a REST/API surface. Kept small on purpose;
# the model adds challenge-specific paths via `extra_paths`.
_DEFAULT_PATHS = [
    "/", "/api", "/api/", "/api/v1", "/api/v2", "/v1", "/v2",
    "/openapi.json", "/openapi.yaml", "/swagger.json", "/swagger.yaml",
    "/swagger-ui.html", "/swagger", "/api-docs", "/v2/api-docs", "/v3/api-docs",
    "/docs", "/redoc", "/graphql", "/graphiql",
    "/health", "/healthz", "/livez", "/readyz", "/status", "/ping", "/version",
    "/metrics", "/info", "/actuator", "/actuator/health",
    "/.well-known/openapi.json", "/.well-known/security.txt",
    "/robots.txt", "/sitemap.xml", "/favicon.ico",
    "/admin", "/login", "/auth", "/token", "/users", "/user", "/config",
    "/.env", "/.git/HEAD",
]
# When a spec doc turns up, we look for declared paths under these top-level keys.
_SPEC_HINTS = ("openapi.json", "swagger.json", "api-docs", "openapi", "swagger")


def _host_only(target: str) -> Optional[str]:
    """Bare host from a URL / host:port / host, for guard checks and target_from."""
    t = (target or "").strip()
    if not t:
        return None
    if "://" in t:
        return (urlsplit(t).hostname or "").lower() or None
    authority = t.split("/", 1)[0]
    if authority.startswith("["):
        end = authority.find("]")
        return authority[1:end].lower() if end != -1 else None
    if authority.count(":") == 1:
        authority = authority.split(":", 1)[0]
    return authority.lower() or None


def _no_redirect_opener() -> urllib.request.OpenerDirector:
    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):  # noqa: D401 - see module docstring
            return None
    return urllib.request.build_opener(_NoRedirect)


def _one_request(opener, url: str, method: str, timeout: float) -> dict:
    """Issue one HTTP(S) request. 3xx/4xx/5xx are returned as data, not raised.
    Redirects are never followed (see module docstring)."""
    req = urllib.request.Request(url=url, method=method.upper())
    req.add_header("User-Agent", "halctf-agent-recon/1")
    try:
        resp = opener.open(req, timeout=timeout)
    except urllib.error.HTTPError as e:      # 3xx (redirects disabled), 4xx, 5xx
        resp = e
    except urllib.error.URLError as e:
        return {"url": url, "method": method.upper(), "error": str(e.reason)}
    except (socket.timeout, TimeoutError):
        return {"url": url, "method": method.upper(), "error": "timeout"}
    except (ssl.SSLError, OSError, ValueError) as e:
        return {"url": url, "method": method.upper(), "error": f"{type(e).__name__}: {e}"}

    status = getattr(resp, "status", None) or getattr(resp, "code", None)
    headers = {k.lower(): v for k, v in (resp.headers.items() if resp.headers else [])}
    try:
        raw = resp.read(_BODY_SNIPPET + 1)
    except Exception:  # noqa: BLE001 - body read faults are just missing data
        raw = b""
    finally:
        try:
            resp.close()
        except Exception:  # noqa: BLE001
            pass
    body = raw[:_BODY_SNIPPET].decode("utf-8", "replace")
    return {
        "url": url,
        "method": method.upper(),
        "status": status,
        "content_type": headers.get("content-type"),
        "content_length": headers.get("content-length"),
        "server": headers.get("server"),
        "location": headers.get("location"),          # redirect target, NOT followed
        "www_authenticate": headers.get("www-authenticate"),
        "body_snippet": body,
        "body_truncated": len(raw) > _BODY_SNIPPET,
    }


def _extract_spec_paths(body: str) -> list[str]:
    """If a body looks like an OpenAPI/Swagger doc, pull out its declared paths."""
    try:
        doc = json.loads(body)
    except (ValueError, TypeError):
        return []
    if not isinstance(doc, dict):
        return []
    paths = doc.get("paths")
    if isinstance(paths, dict):
        return sorted(str(p) for p in paths.keys())[:_MAX_PATHS]
    return []


# --------------------------------------------------------------------------
# port_scan
# --------------------------------------------------------------------------

def make_port_scan_tool(guard: ScopeGuard, connect_timeout: float) -> Tool:
    def handler(args: dict) -> dict:
        host = _host_only(args["host"])
        if not host:
            return {"error": f"unparseable host: {args['host']!r}"}
        # Defense in depth: the Dispatcher checked the host, but re-check here so
        # the tool is safe even if called directly or expanded later.
        decision = guard.check(host)
        if not decision.allowed:
            return {"error": "out-of-scope", "host": host, "reason": decision.reason}

        ports = args.get("ports") or list(_DEFAULT_PORTS)
        clean: list[int] = []
        for p in ports:
            if isinstance(p, bool) or not isinstance(p, int):
                continue
            if 1 <= p <= 65535 and p not in clean:
                clean.append(p)
        clean = clean[:_MAX_PORTS]
        if not clean:
            return {"error": "no valid ports to scan", "host": host}

        timeout = float(args.get("timeout_ms", connect_timeout * 1000)) / 1000.0
        timeout = max(0.1, min(timeout, 10.0))

        def probe(port: int) -> Optional[dict]:
            try:
                with socket.create_connection((host, port), timeout=timeout) as sock:
                    entry = {"port": port, "service_hint": _SERVICE_HINTS.get(port)}
                    if port in _PORTS_TLS:
                        _augment_tls(host, port, timeout, entry)
                    else:
                        _augment_banner(sock, timeout, entry)
                    return entry
            except (socket.timeout, TimeoutError, ConnectionRefusedError, OSError):
                return None

        workers = min(_MAX_WORKERS, len(clean))
        open_ports: list[dict] = []
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for result in pool.map(probe, clean):
                if result is not None:
                    open_ports.append(result)
        open_ports.sort(key=lambda e: e["port"])
        return {
            "host": host,
            "scanned": len(clean),
            "open_count": len(open_ports),
            "open": open_ports,
            "timeout_s": timeout,
        }

    return Tool(
        name="port_scan",
        description=(
            "TCP connect-scan a single in-scope host over a set of ports "
            "(defaults to common web/API/service ports). Reports open ports with "
            "a service hint and, where available, a banner or TLS certificate "
            "subject. Scoped to the one host; ports are not followed off-host."
        ),
        parameters={
            "host": {"type": "string", "required": True},
            "ports": {"type": "array", "required": False},
            "timeout_ms": {"type": "integer", "required": False},
        },
        handler=handler,
        target_from=lambda a: _host_only(a.get("host", "")),
    )


def _augment_banner(sock: socket.socket, timeout: float, entry: dict) -> None:
    try:
        sock.settimeout(min(timeout, 1.0))
        data = sock.recv(_BANNER_BYTES)
        if data:
            entry["banner"] = data.decode("utf-8", "replace").strip()
    except (socket.timeout, TimeoutError, OSError):
        pass


def _augment_tls(host: str, port: int, timeout: float, entry: dict) -> None:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE           # we want the cert, not to trust it
    try:
        with socket.create_connection((host, port), timeout=timeout) as raw:
            with ctx.wrap_socket(raw, server_hostname=host) as tls:
                entry["tls"] = True
                entry["tls_version"] = tls.version()
                cert = tls.getpeercert()
                if cert:
                    subj = {k: v for t in cert.get("subject", ()) for (k, v) in t}
                    entry["tls_subject_cn"] = subj.get("commonName")
                    entry["tls_not_after"] = cert.get("notAfter")
    except (ssl.SSLError, socket.timeout, TimeoutError, OSError):
        entry["tls"] = True                    # port spoke TLS enough to try
        entry["tls_error"] = "handshake/cert unavailable"


# --------------------------------------------------------------------------
# http_probe
# --------------------------------------------------------------------------

def make_http_probe_tool(guard: ScopeGuard, http_timeout: float) -> Tool:
    def handler(args: dict) -> dict:
        url = args["url"]
        host = _host_only(url)
        if not host:
            return {"error": f"unparseable url: {url!r}"}
        decision = guard.check(host)
        if not decision.allowed:
            return {"error": "out-of-scope", "host": host, "reason": decision.reason}
        method = str(args.get("method", "GET"))
        if method.upper() not in ("GET", "HEAD", "OPTIONS", "POST", "PUT", "DELETE", "PATCH"):
            return {"error": f"unsupported method: {method!r}"}
        timeout = max(0.5, min(float(args.get("timeout_ms", http_timeout * 1000)) / 1000.0, 30.0))
        return _one_request(_no_redirect_opener(), url, method, timeout)

    return Tool(
        name="http_probe",
        description=(
            "Issue ONE HTTP(S) request to an in-scope URL and return status, key "
            "headers, and a body snippet. Redirects are reported (Location), never "
            "followed — probe the redirect target explicitly if it is in scope."
        ),
        parameters={
            "url": {"type": "string", "required": True},
            "method": {"type": "string", "required": False},
            "timeout_ms": {"type": "integer", "required": False},
        },
        handler=handler,
        target_from=lambda a: _host_only(a.get("url", "")),
    )


# --------------------------------------------------------------------------
# api_discover
# --------------------------------------------------------------------------

def make_api_discover_tool(guard: ScopeGuard, http_timeout: float) -> Tool:
    def handler(args: dict) -> dict:
        base = args["base_url"]
        if "://" not in base:
            base = "http://" + base
        host = _host_only(base)
        if not host:
            return {"error": f"unparseable base_url: {args['base_url']!r}"}
        decision = guard.check(host)
        if not decision.allowed:
            return {"error": "out-of-scope", "host": host, "reason": decision.reason}

        paths = list(_DEFAULT_PATHS)
        for p in (args.get("extra_paths") or []):
            if isinstance(p, str) and p not in paths:
                paths.append(p)
        paths = paths[:_MAX_PATHS]
        timeout = max(0.5, min(float(args.get("timeout_ms", http_timeout * 1000)) / 1000.0, 30.0))
        opener = _no_redirect_opener()

        def probe(path: str) -> Optional[dict]:
            url = urljoin(base if base.endswith("/") else base + "/", path.lstrip("/"))
            # Same-host by construction, but re-check: urljoin on an absolute path
            # keeps the host; guard against a caller sneaking a full URL into paths.
            if not guard.check(_host_only(url)).allowed:
                return {"path": path, "skipped": "out-of-scope"}
            r = _one_request(opener, url, "GET", timeout)
            status = r.get("status")
            if status is None and "error" in r:
                return None                       # unreachable path: drop the noise
            hit = {
                "path": path,
                "status": status,
                "content_type": r.get("content_type"),
                "length": r.get("content_length"),
                "location": r.get("location"),
            }
            # Mine any OpenAPI/Swagger doc we stumble on for its declared paths.
            if status == 200 and any(h in path for h in _SPEC_HINTS):
                spec = _extract_spec_paths(r.get("body_snippet", ""))
                if spec:
                    hit["spec_paths"] = spec
            return hit

        workers = min(_MAX_WORKERS, len(paths))
        results: list[dict] = []
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for res in pool.map(probe, paths):
                if res is not None:
                    results.append(res)

        # Surface the interesting ones first: anything that resolved (not 404).
        found = [r for r in results if isinstance(r.get("status"), int) and r["status"] != 404]
        spec_paths = sorted({p for r in results for p in r.get("spec_paths", [])})
        return {
            "host": host,
            "base_url": base,
            "tried": len(paths),
            "found_count": len(found),
            "found": sorted(found, key=lambda r: (r.get("status") or 999, r["path"])),
            "spec_paths": spec_paths,
        }

    return Tool(
        name="api_discover",
        description=(
            "Map the REST/API surface of an in-scope base URL by probing common "
            "paths (openapi/swagger specs, health, docs, versioned API roots, "
            "etc.). Returns paths that resolve (non-404) and, if an OpenAPI/Swagger "
            "doc is found, the endpoints it declares. Redirects are not followed."
        ),
        parameters={
            "base_url": {"type": "string", "required": True},
            "extra_paths": {"type": "array", "required": False},
            "timeout_ms": {"type": "integer", "required": False},
        },
        handler=handler,
        target_from=lambda a: _host_only(a.get("base_url", "")),
    )


def register_recon_tools(
    registry: ToolRegistry,
    guard: ScopeGuard,
    *,
    connect_timeout: float = _DEFAULT_CONNECT_TIMEOUT,
    http_timeout: float = _DEFAULT_HTTP_TIMEOUT,
) -> None:
    """Register the scope-gated recon tools. `guard` is closed over by each tool
    so every concrete destination is re-checked, not just the declared target."""
    registry.register(make_port_scan_tool(guard, connect_timeout))
    registry.register(make_http_probe_tool(guard, http_timeout))
    registry.register(make_api_discover_tool(guard, http_timeout))
