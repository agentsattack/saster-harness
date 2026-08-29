#!/usr/bin/env python3
"""
Session-affinity front door for the saster sweep.

Round-robin across nodes destroys the vLLM prefix cache on every turn. This router
pins a campaign to one backend for its whole life, so the shared prefix (system
prompt + objective spec + 13 tool definitions), the k=5 trials of a campaign, and
the ~13 envelope-mass scoring calls per step all land on the same KV cache.

Affinity is resolved WITHIN the set of backends that serve the requested model.
Each backend hosts one model, so hashing a campaign across every backend — as
this router did until the W6c pilot — sends roughly half of all campaigns to a
node that does not have their model, and vLLM answers "The model `X` does not
exist." with a 404. That is exactly what happened to the Qwen3-8B canary: its
affinity key hashed onto the Ministral replica and every one of its 10 attempts
404'd, while Ministral's key happened to hash onto its own replica and passed
10/10. The bug was invisible in the routing layer because the 404 is upstream's,
and it was worked around by hand-picking campaign ids that happen to hash the
right way.

Resolution order, per request:
  1. the requested model (body "model") selects the candidate backends;
  2. the affinity key selects one of them by consistent hashing.

So a campaign is still pinned to one replica for its whole life — the prefix
cache guarantee is unchanged — but it is pinned to a replica that can actually
serve it. With one replica per model, step 2 is trivially stable; with several
replicas of one model it distributes campaigns across exactly those.

Affinity key, in priority order:
  1. X-Campaign-ID header (explicit, preferred)
  2. "user" field in the JSON body (OpenAI-compatible session marker)
  3. hash of the first message's content prefix (fallback, still stable per campaign)

Backends are chosen by consistent hashing over the key, so adding or removing a
node only remaps 1/N of the campaigns for that model rather than reshuffling
everything.

Which model each backend serves is DISCOVERED from its /v1/models at startup,
not configured, so the map cannot drift from what the nodes are actually
running. A backend that is unreachable at startup is retried on demand, so a
slow-booting vLLM does not permanently strand its model.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import time
from collections import defaultdict

# The serving deps live in the router's own venv, not the harness's. The
# routing logic below is pure stdlib and is unit-tested from the harness venv
# (tests/test_router_affinity.py), so the import is optional and only the
# server entry points require it. Annotations are lazy (PEP 563) so the
# handler signatures below do not evaluate `web` at import time.
try:
    from aiohttp import ClientSession, ClientTimeout, web
except ModuleNotFoundError:  # pragma: no cover - exercised by the router venv
    ClientSession = ClientTimeout = web = None

#: Requests that name no model still have to go somewhere (health probes and
#: the like). They hash over every backend, which is the pre-existing
#: behaviour and is safe precisely because they are not model-specific.
ANY_MODEL = None


class Router:
    def __init__(self, backends, replicas=200):
        self.backends = backends
        self.replicas = replicas
        #: backend -> frozenset of model ids it serves, as discovered.
        self.backend_models = {}
        #: model id (or ANY_MODEL) -> sorted consistent-hash ring.
        self.rings = {}
        self.stats = defaultdict(lambda: {"requests": 0, "campaigns": set(), "errors": 0})
        self.discovery_errors = {}
        self.started = time.time()
        self.rebuild_rings()

    # -- ring construction --------------------------------------------------

    def _ring_for(self, backends):
        ring = []
        for b in backends:
            for r in range(self.replicas):
                h = hashlib.blake2b(f"{b}#{r}".encode(), digest_size=8).digest()
                ring.append((int.from_bytes(h, "big"), b))
        ring.sort()
        return ring

    def rebuild_rings(self):
        """One ring per model, over exactly the backends serving that model.

        The ring for a model is built from the backend list in configured
        order, so a given (model, key) pair resolves identically on every
        process with the same configuration — the affinity has to survive a
        router restart or a campaign's trials would scatter across replicas.
        """
        rings = {ANY_MODEL: self._ring_for(self.backends)}
        by_model = defaultdict(list)
        for backend in self.backends:  # configured order, not dict order
            for model in self.backend_models.get(backend, ()):
                by_model[model].append(backend)
        for model, backends in by_model.items():
            rings[model] = self._ring_for(backends)
        self.rings = rings

    def set_backend_models(self, mapping):
        """Install a discovered backend -> models map and rebuild the rings."""
        self.backend_models = {b: frozenset(m) for b, m in mapping.items()}
        self.rebuild_rings()

    def known_models(self):
        return sorted(m for m in self.rings if m is not ANY_MODEL)

    # -- selection ----------------------------------------------------------

    def pick(self, key, model=ANY_MODEL):
        """The backend this (model, key) pair pins to, or None if no backend
        serves ``model``. Returning None rather than falling back is
        deliberate: silently routing to a backend that lacks the model is the
        defect this router had, and an honest failure is worth more than a
        confusing upstream 404."""
        ring = self.rings.get(model)
        if not ring:
            return None
        h = int.from_bytes(hashlib.blake2b(key.encode(), digest_size=8).digest(), "big")
        lo, hi = 0, len(ring)
        while lo < hi:                      # first ring point >= h
            mid = (lo + hi) // 2
            if ring[mid][0] < h:
                lo = mid + 1
            else:
                hi = mid
        return ring[lo % len(ring)][1]

    @staticmethod
    def requested_model(body):
        if isinstance(body, dict):
            model = body.get("model")
            if isinstance(model, str) and model:
                return model
        return ANY_MODEL

    @staticmethod
    def affinity_key(headers, body):
        k = headers.get("X-Campaign-ID")
        if k:
            return k, "header"
        if isinstance(body, dict):
            if body.get("user"):
                return str(body["user"]), "user-field"
            msgs = body.get("messages")
            if isinstance(msgs, list) and msgs:
                c = msgs[0].get("content")
                if isinstance(c, list):     # multimodal content blocks
                    c = json.dumps(c)
                if c:
                    return hashlib.blake2b(str(c)[:4096].encode(), digest_size=16).hexdigest(), "prefix-hash"
            p = body.get("prompt")
            if p:
                if isinstance(p, list):
                    p = p[0] if p else ""
                return hashlib.blake2b(str(p)[:4096].encode(), digest_size=16).hexdigest(), "prompt-hash"
        return "default", "fallback"


# -- backend model discovery ------------------------------------------------


async def discover_models(session, backends, timeout=10.0):
    """Ask every backend what it serves. Returns (mapping, errors).

    Unreachable backends come back in ``errors`` and simply own no models, so
    they are absent from every ring rather than silently receiving traffic for
    a model they may not have.
    """
    mapping, errors = {}, {}

    async def one(backend):
        url = backend.rstrip("/") + "/v1/models"
        try:
            async with session.get(url, timeout=ClientTimeout(total=timeout)) as resp:
                if resp.status != 200:
                    errors[backend] = f"HTTP {resp.status} from {url}"
                    return
                payload = await resp.json()
        except Exception as e:  # noqa: BLE001 — any failure means "unknown"
            errors[backend] = f"{type(e).__name__}: {e}"
            return
        ids = [m.get("id") for m in (payload.get("data") or []) if isinstance(m, dict)]
        mapping[backend] = [i for i in ids if isinstance(i, str) and i]

    await asyncio.gather(*(one(b) for b in backends))
    return mapping, errors


async def refresh(app):
    router: Router = app["router"]
    mapping, errors = await discover_models(app["session"], router.backends)
    router.set_backend_models(mapping)
    router.discovery_errors = errors
    for backend, models in sorted(mapping.items()):
        print(f"[router] {backend} serves {', '.join(sorted(models)) or '(nothing)'}", flush=True)
    for backend, err in sorted(errors.items()):
        print(f"[router] {backend} UNREACHABLE at startup: {err}", flush=True)
    return mapping, errors


# -- handlers ---------------------------------------------------------------


async def models(request: web.Request):
    """Aggregate /v1/models across every backend.

    Routing this like any other request would answer from whichever single
    backend the fallback key happened to hash to, so the front door would
    advertise one model and serve two — which is what it did, listing only
    Qwen while Ministral was up.
    """
    router: Router = request.app["router"]
    if not router.backend_models:
        await refresh(request.app)
    seen, data = set(), []
    for backend in router.backends:
        for model in sorted(router.backend_models.get(backend, ())):
            if model in seen:
                continue
            seen.add(model)
            data.append({"id": model, "object": "model", "owned_by": "vllm",
                         "root": model, "parent": None,
                         "x_saster_backend": backend})
    return web.json_response({"object": "list", "data": data})


async def proxy(request: web.Request):
    router: Router = request.app["router"]
    raw = await request.read()
    body = None
    if raw:
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            body = None

    key, how = Router.affinity_key(request.headers, body)
    model = Router.requested_model(body)
    backend = router.pick(key, model)

    if backend is None and model is not ANY_MODEL:
        # Re-discover once: a backend that was down at startup may be up now,
        # and stranding its model until the router restarts would be its own
        # outage.
        await refresh(request.app)
        backend = router.pick(key, model)

    if backend is None:
        known = router.known_models()
        detail = {
            "message": (
                f"no backend serves model `{model}`; router knows {known or 'no models'}"
            ),
            "type": "RouterNoBackendForModel",
            "param": "model",
            "code": 503,
            "requested_model": model,
            "known_models": known,
            "unreachable_backends": router.discovery_errors,
        }
        return web.json_response({"error": detail}, status=503)

    st = router.stats[backend]
    st["requests"] += 1
    st["campaigns"].add(key)

    url = backend.rstrip("/") + request.rel_url.path_qs
    headers = {k: v for k, v in request.headers.items()
               if k.lower() not in ("host", "content-length", "connection")}
    session: ClientSession = request.app["session"]
    try:
        async with session.request(request.method, url, data=raw, headers=headers) as up:
            data = await up.read()
            out = web.StreamResponse(status=up.status)
            for k, v in up.headers.items():
                if k.lower() not in ("content-length", "transfer-encoding", "content-encoding", "connection"):
                    out.headers[k] = v
            out.headers["X-Saster-Backend"] = backend
            out.headers["X-Saster-Affinity"] = how
            if model is not ANY_MODEL:
                out.headers["X-Saster-Model"] = model
            await out.prepare(request)
            await out.write(data)
            await out.write_eof()
            return out
    except Exception as e:
        st["errors"] += 1
        return web.json_response({"error": {"message": f"router upstream failure: {e}",
                                            "backend": backend}}, status=502)


async def stats(request: web.Request):
    router: Router = request.app["router"]
    return web.json_response({
        "uptime_s": round(time.time() - router.started, 1),
        "backends": [
            {"backend": b,
             "requests": s["requests"],
             "distinct_campaigns": len(s["campaigns"]),
             "errors": s["errors"]}
            for b, s in sorted(router.stats.items())
        ],
        "configured_backends": router.backends,
        "backend_models": {b: sorted(m) for b, m in sorted(router.backend_models.items())},
        "known_models": router.known_models(),
        "unreachable_backends": router.discovery_errors,
    })


def main():
    if web is None:
        raise SystemExit(
            "saster_router needs aiohttp to serve; run it from the router venv "
            "(e.g. /home/lbsuto/agentdog-venv/bin/python). The routing logic "
            "itself imports without it, which is how the harness tests it."
        )
    ap = argparse.ArgumentParser()
    ap.add_argument("--backends", required=True, help="comma-separated base URLs")
    ap.add_argument("--port", type=int, default=8080)
    a = ap.parse_args()

    app = web.Application(client_max_size=256 * 1024 * 1024)
    app["router"] = Router([b.strip() for b in a.backends.split(",") if b.strip()])

    async def on_start(app):
        app["session"] = ClientSession(timeout=ClientTimeout(total=1800))
        await refresh(app)

    async def on_stop(app):
        await app["session"].close()

    app.on_startup.append(on_start)
    app.on_cleanup.append(on_stop)
    app.router.add_get("/router/stats", stats)
    app.router.add_get("/v1/models", models)
    app.router.add_route("*", "/{tail:.*}", proxy)
    web.run_app(app, port=a.port, access_log=None)


if __name__ == "__main__":
    main()
