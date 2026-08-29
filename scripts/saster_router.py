#!/usr/bin/env python3
"""
Session-affinity front door for the saster sweep.

Round-robin across nodes destroys the vLLM prefix cache on every turn. This router
pins a campaign to one backend for its whole life, so the shared prefix (system
prompt + objective spec + 13 tool definitions), the k=5 trials of a campaign, and
the ~13 envelope-mass scoring calls per step all land on the same KV cache.

Affinity key, in priority order:
  1. X-Campaign-ID header (explicit, preferred)
  2. "user" field in the JSON body (OpenAI-compatible session marker)
  3. hash of the first message's content prefix (fallback, still stable per campaign)

Backends are chosen by consistent hashing over the key, so adding or removing a
node only remaps 1/N of campaigns rather than reshuffling everything.
"""
import argparse, asyncio, hashlib, json, time
from collections import defaultdict

from aiohttp import web, ClientSession, ClientTimeout


class Router:
    def __init__(self, backends, replicas=200):
        self.backends = backends
        self.ring = []
        for b in backends:
            for r in range(replicas):
                h = hashlib.blake2b(f"{b}#{r}".encode(), digest_size=8).digest()
                self.ring.append((int.from_bytes(h, "big"), b))
        self.ring.sort()
        self.stats = defaultdict(lambda: {"requests": 0, "campaigns": set(), "errors": 0})
        self.started = time.time()

    def pick(self, key):
        h = int.from_bytes(hashlib.blake2b(key.encode(), digest_size=8).digest(), "big")
        lo, hi = 0, len(self.ring)
        while lo < hi:                      # first ring point >= h
            mid = (lo + hi) // 2
            if self.ring[mid][0] < h:
                lo = mid + 1
            else:
                hi = mid
        return self.ring[lo % len(self.ring)][1]

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
    backend = router.pick(key)
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
    })


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backends", required=True, help="comma-separated base URLs")
    ap.add_argument("--port", type=int, default=8080)
    a = ap.parse_args()

    app = web.Application(client_max_size=256 * 1024 * 1024)
    app["router"] = Router([b.strip() for b in a.backends.split(",") if b.strip()])

    async def on_start(app):
        app["session"] = ClientSession(timeout=ClientTimeout(total=1800))

    async def on_stop(app):
        await app["session"].close()

    app.on_startup.append(on_start)
    app.on_cleanup.append(on_stop)
    app.router.add_get("/router/stats", stats)
    app.router.add_route("*", "/{tail:.*}", proxy)
    web.run_app(app, port=a.port, access_log=None)


if __name__ == "__main__":
    main()
