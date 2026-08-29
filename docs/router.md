# Session-affinity router

`scripts/saster_router.py` is the front door every campaign call goes through.
It pins a campaign to one backend for that campaign's whole life so the shared
prefix (system prompt + objective spec + 13 tool definitions), the k=5 trials,
and the ~13 envelope-mass scoring calls per step all reuse the same vLLM prefix
cache. Round-robin across nodes would destroy that cache on every turn.

## Exact invocation used for the sweep

```
/home/lbsuto/agentdog-venv/bin/python scripts/saster_router.py \
  --backends http://192.168.1.228:8000,http://192.168.1.208:8000 \
  --port 8080
```

The backend strings are **load-bearing and must be byte-stable**. Backends are
placed on a consistent-hash ring by `blake2b("{backend}#{replica}")` over the
backend string exactly as given on the command line. Changing a string — even
to an equivalent form such as adding a trailing slash, swapping in a hostname,
or reordering the list — moves ring points and repins campaigns to different
nodes, which silently changes which trials share a KV cache.

Ring construction uses `replicas=200` per backend and is order-independent
(the ring is sorted), so the list order does not affect placement; the string
contents do.

## Health

`GET /router/stats` reports uptime, per-backend request and distinct-campaign
counts, and upstream error counts. Every proxied response also carries
`X-Saster-Backend` (which node served it) and `X-Saster-Affinity` (which of the
four affinity-key sources was used: `header`, `user-field`, `prefix-hash`,
`prompt-hash`, or `fallback`).
