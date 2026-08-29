# Cluster bring-up

Recovery procedure for the saster serving cluster after an outage or a Ray
teardown. Every `vllm serve` invocation below was recovered verbatim from
`docker inspect` of the stopped container on its node — these are the commands
that actually last served the benchmark numbers, not reconstructions.

## Topology

Node `N` on the fabric is `fd00:200::N` (see `tp-launch.sh`). The control node
is spark1; it is the only host on both the `192.168.1.0/24` LAN and the
`fd00:200::/64` fabric, so it is the correct place to drive bring-up from.

| Alias  | LAN address     | Fabric address | Role                        | Container    | Image                    |
|--------|-----------------|----------------|-----------------------------|--------------|--------------------------|
| spark1 | 192.168.1.100   | fd00:200::1    | control node, router, Ray head | `rayhead` | `vllm-node:pinned`       |
| spark3 | 192.168.1.228   | fd00:200::3    | Qwen3-8B         : 8000     | `victimA`    | `vllm-node:pinned`       |
| spark6 | 192.168.1.208   | fd00:200::6    | Ministral-8B     : 8000     | `victimB`    | `vllm-node:pinned`       |
| spark4 | 192.168.1.201   | fd00:200::4    | AgentDoG         : 8001     | `agentdog10` | `eugr/spark-vllm:latest` |

Note spark4 runs a **different image** from the other two, pinned by digest in
`~/agentdog-serving-pins.txt` on that node:
`eugr/spark-vllm sha256:735caabf4f1e52c5a343a68793aab86690683465cc51d76dd84f7af011750639`.

All three servers run vLLM `0.26.1rc1.dev1188+gd9fbe526c.d20260825` (V1 engine),
`dtype=torch.bfloat16`, `quantization=None`. All run with `HF_HUB_OFFLINE=1`, so
the weights **must** already be in `~/.cache/huggingface` on the node.

## The Ray GPU-memory pre-check

**Do this before starting any vLLM server. It is the step that causes OOM when skipped.**

These nodes double as workers in a Ray cluster (`tp-launch.sh` builds a
multi-node tensor-parallel vLLM across them, head on spark1 at
`[fd00:200::1]:6379`). A node must never run a `rayworker`/`rayhead` container
and a standalone vLLM container at the same time.

The reason is asymmetric visibility: **Ray accounts only for the memory it
allocates itself.** A standalone vLLM container holding
`--gpu-memory-utilization 0.85` is invisible to Ray's scheduler, which still
advertises the full GPU as free and will happily place a job on top of it. Both
processes then reach for the same memory and the node OOMs. Ray reporting
`0.0/6.0 GPU` does **not** mean the node is clear — it means Ray is idle right
now, not that it has released its claim.

These are GB10 (Grace Blackwell) nodes with **unified** host/GPU memory, so
`nvidia-smi` reports `[N/A]` for `memory.used` / `memory.free` and is useless
here. Check `free -g` and the container list instead:

```bash
# on each serving node, before launching
docker ps --format '{{.Names}}\t{{.Image}}\t{{.Status}}'   # expect NO rayworker/rayhead
nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv
free -g                                                    # expect ~115 of 119 GiB free
pgrep -af 'raylet|ray::|gcs_server'

# clear the node if a Ray worker is present
docker rm -f rayworker
```

Removing `rayworker` from a node drops it out of the Ray cluster. That is the
intended trade: a node serves standalone vLLM **or** it participates in Ray,
never both.

## Bring-up order

1. **Pre-check each serving node** — no `rayworker`/`rayhead`, memory free (above).
2. **Start the three vLLM servers** (below). They are independent; order among
   them does not matter.
3. **Wait for readiness** — poll `/v1/models` until it answers. Cold start is
   ~2 minutes for the 8B models (weight load + `torch.compile`), faster for the
   4B. Do not start the router before the backends answer.
4. **Start the affinity router** on spark1.
5. **Verify** each endpoint (below).

### 1. spark3 — Qwen/Qwen3-8B on :8000

```bash
docker run -d --name victimA --gpus all -p 8000:8000 \
  -e HF_HUB_OFFLINE=1 \
  -v $HOME/.cache/huggingface:/root/.cache/huggingface \
  vllm-node:pinned \
  vllm serve Qwen/Qwen3-8B --max-model-len 32768 --enable-auto-tool-choice --tool-call-parser hermes --gpu-memory-utilization 0.85
```

### 2. spark6 — mistralai/Ministral-8B-Instruct-2410 on :8000

```bash
docker run -d --name victimB --gpus all -p 8000:8000 \
  -e HF_HUB_OFFLINE=1 \
  -v $HOME/.cache/huggingface:/root/.cache/huggingface \
  vllm-node:pinned \
  vllm serve mistralai/Ministral-8B-Instruct-2410 --max-model-len 32768 --enable-auto-tool-choice --tool-call-parser mistral --tokenizer-mode mistral --config-format mistral --load-format mistral --gpu-memory-utilization 0.85
```

### 3. spark4 — AI45Research/AgentDoG-Qwen3-4B on :8001

This is the **1.0-class** model and the sweep path. The 1.5 variants on
`fd00:200::2` (spark2) are *not* the sweep path — do not substitute them.

Container port is 8000 mapped to host **8001**.

```bash
docker run -d --name agentdog10 --gpus all -p 8001:8000 \
  -e HF_HUB_OFFLINE=1 \
  -v $HOME/.cache/huggingface:/root/.cache/huggingface \
  eugr/spark-vllm:latest \
  vllm serve AI45Research/AgentDoG-Qwen3-4B --max-model-len 16384
```

> **Caveat — no tool calling on spark4.** Unlike spark3 and spark6, the recovered
> command carries no `--enable-auto-tool-choice` / `--tool-call-parser`. It is
> reproduced verbatim to keep the benchmark numbers comparable. If this node ever
> needs tool calling, adding those flags is a deliberate change to a benchmarked
> configuration — re-baseline rather than adding them silently. `hermes` is the
> parser to use if so (the model is Qwen3-family, matching spark3).

> **Stale scripts on spark4.** `~/serve10.sh` and `~/repin.sh` on that node both
> serve `AI45Research/AgentDoG-Qwen2.5-7B`, which is **not** what last ran and is
> not in the HF cache. They will abort or serve the wrong model. The container
> definition is the source of truth; treat those scripts as historical.

### Prefix caching

Prefix caching is **on** for all three, and must stay on — the affinity router
exists to exploit it. It needs no flag: vLLM's V1 engine defaults
`enable_prefix_caching=True`, confirmed in each engine's startup config line.
Verify rather than assume:

```bash
docker logs victimA 2>&1 | grep -o 'enable_prefix_caching=[A-Za-z]*'   # enable_prefix_caching=True
```

A healthy campaign shows a high hit rate in the engine logs
(`Prefix cache hit rate: 99.4%` under the router). A rate near 0% across a
campaign means the router is not pinning correctly.

## Affinity router (spark1)

```bash
/home/lbsuto/agentdog-venv/bin/python /home/lbsuto/saster_router.py \
  --backends http://192.168.1.228:8000,http://192.168.1.208:8000 --port 8080
```

**The backend strings must stay byte-identical.** `saster_router.py` builds a
consistent-hash ring by hashing each backend string directly:

```python
h = hashlib.blake2b(f"{b}#{r}".encode(), digest_size=8).digest()
```

The string itself is the ring key, at 200 replicas each. Any edit that a human
would read as equivalent — a trailing `/`, a hostname instead of the literal IP,
`http://192.168.1.228:8000/v1`, reordering the list — produces different ring
points, repins live campaigns to different backends, and throws away the KV
cache the router was built to preserve. The prefix-cache hit rate collapses and
the benchmark numbers move. Copy the line; do not retype it.

The router pins a campaign to one backend for its whole life so the shared
prefix and the ~13 envelope-mass scoring calls per step land on the same KV
cache. Its stats endpoint is `/router/stats` (everything else is proxied
through to a backend):

```bash
curl -s http://192.168.1.100:8080/router/stats | jq '.configured_backends'
```

## Verification

```bash
# 1. model string is exactly what is expected
curl -s http://192.168.1.228:8000/v1/models   | jq -r '.data[].id'   # Qwen/Qwen3-8B
curl -s http://192.168.1.208:8000/v1/models   | jq -r '.data[].id'   # mistralai/Ministral-8B-Instruct-2410
curl -s http://[fd00:200::4]:8001/v1/models   | jq -r '.data[].id'   # AI45Research/AgentDoG-Qwen3-4B

# 2. echo=true returns per-prompt-token logprobs (envelope-mass scoring needs these)
curl -s http://192.168.1.228:8000/v1/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"Qwen/Qwen3-8B","prompt":"The capital of France is",
       "max_tokens":3,"echo":true,"logprobs":1,"temperature":0}' \
  | jq '.choices[0].logprobs | {tokens, token_logprobs}'
```

The echoed prompt tokens must each carry a logprob, with `null` only for the
very first token (nothing precedes it). If `logprobs` comes back `null`, the
scoring path is broken even though the endpoint looks healthy.

## Access from spark1

spark1 reaches the serving nodes by key with these aliases in `~/.ssh/config`:
`spark3`, `spark6`, `spark4`, plus `spark3-fab` / `spark6-fab` / `spark4-v4` for
the alternate addresses. spark1's public key (`spark1-saster-push`) is installed
in `~/.ssh/authorized_keys` on all three.

Note that spark4 is reachable from spark1 over both the fabric (`fd00:200::4`)
and the LAN (`192.168.1.201`), but a host with no global IPv6 route cannot reach
it at all on the fabric address — drive bring-up from spark1, or use
`192.168.1.201`.
