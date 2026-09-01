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
| spark4 | 192.168.1.201   | fd00:200::4    | AgentDoG binary  : 8001     | `agentdog10` | `eugr/spark-vllm:latest` |
| spark4 | 192.168.1.201   | fd00:200::4    | AgentDoG FG      : 8002     | `agentdogfg` | `eugr/spark-vllm:latest` |

Note spark4 runs a **different image** from the other two, pinned by digest in
`~/agentdog-serving-pins.txt` on that node:
`eugr/spark-vllm sha256:735caabf4f1e52c5a343a68793aab86690683465cc51d76dd84f7af011750639`.

All four servers run vLLM `0.26.1rc1.dev1188+gd9fbe526c.d20260825` (V1 engine),
`dtype=torch.bfloat16`, `quantization=None`. All run with `HF_HUB_OFFLINE=1`, so
the weights **must** already be in `~/.cache/huggingface` on the node.

**The fabric has eight nodes, and all eight are reachable from spark1.**
`fd00:200::1` through `::8` all answer ICMP, and as of 2026-08-31 spark1's key
(`spark1-saster-push`) is installed on **all seven** peers. Key-only SSH
(`BatchMode=yes`) to spark2 through spark8 succeeds and each answers with its
own hostname.

**spark2, spark5, spark7 and spark8 are not idle.** Earlier revisions of this
file described them that way; that was wrong. Each runs a
`rayworker` container on `vllm-node:pinned` and is a live, registered member of
the Ray cluster. What is true is narrower: they serve nothing on 8000-8002, and
they hold no standalone vLLM. Treat them as committed Ray capacity, not as free
nodes — moving an AgentDoG head onto one means first removing its `rayworker`,
with the same trade described below.

Address these four by their **fabric** address. They hold no DHCP reservation on
the LAN, so their `192.168.1.x` addresses can move; `fd00:200::N` is stable.
`~/.ssh/config` on spark1 defines `spark2`, `spark5`, `spark7` and `spark8`
keyed off the fabric address for exactly this reason.

> **Cloned host keys.** spark2/spark3 and spark7/spark8 were built from common
> images and were never re-keyed, so each pair presents an *identical* SSH host
> key: spark2 and spark3 both show
> `SHA256:DLqscEJ0o78f3tLf6s4xmlKmm3VIhEQ+988adSbvXkM`, spark7 and spark8 both
> show `SHA256:2tJO+DmA0HeG5UmWiOKDwUytXBqFd0jXwmlfJGiOLy8`. `known_hosts`
> therefore cannot distinguish the members of a pair — an entry for one silently
> validates the other. Host-key verification will not catch a wrong-node
> connection here; the fabric address is what keeps you honest.

### Ray membership is not a fault signal

The Ray head runs on spark1. `ray status` prints all eight nodes under
`Active:`, which is misleading — the authoritative view is `ray.nodes()`, which
splits them:

| Node   | Ray state | Note                                              |
|--------|-----------|---------------------------------------------------|
| spark1 | ALIVE     | head, 1 GPU                                       |
| spark2 | ALIVE     | `rayworker`, 1 GPU                                |
| spark3 | **DEAD**  | by design — serves Qwen3-8B standalone            |
| spark4 | **DEAD**  | by design — serves both AgentDoG heads standalone |
| spark5 | ALIVE     | `rayworker`, 1 GPU (see resolved note below)      |
| spark6 | **DEAD**  | by design — serves Ministral-8B standalone        |
| spark7 | ALIVE     | `rayworker`, 1 GPU                                |
| spark8 | ALIVE     | `rayworker`, 1 GPU                                |

**spark3, spark4 and spark6 showing DEAD is correct, not a failure.** Their
`rayworker` containers were removed so they could serve standalone vLLM, which
is precisely the trade documented in the pre-check below. Ray reports them as
`health check failed due to missing too many heartbeats`; that message is the
expected consequence of `docker rm -f rayworker`, not an incident. Do not
"repair" it by restarting a worker on a serving node — that reintroduces the
exact OOM the pre-check exists to prevent.

> **RESOLVED 2026-08-31 — a Ray worker can lose its GPU without anything
> looking wrong.** spark5 was advertising no `GPU` resource to Ray while
> `nvidia-smi` *on the host* reported a healthy `NVIDIA GB10`, so the cluster
> totalled 4.0 GPU across five alive nodes instead of 5.0.
>
> Every static factor was identical to a working node (spark2 as control):
> same `DeviceRequests`/`NVIDIA_VISIBLE_DEVICES=all`, same `/dev/nvidia*` nodes
> bind-mounted *inside* the container, same driver `580.126.09`, same
> `libnvidia-ml.so`. The single discriminator was `nvidia-smi` **inside** the
> container:
>
> ```
> spark5:  Failed to initialize NVML: Unknown Error
> spark2:  NVIDIA GB10
> ```
>
> A running GPU container can lose its device access at the cgroup level — most
> often when `systemctl daemon-reload` rebuilds the device BPF program on
> cgroup v2 and does not restore the container's allowance. The device nodes
> stay bind-mounted and visible, so `docker inspect` and `ls /dev/nvidia*` both
> look correct; only an NVML call fails. Ray's raylet autodetects GPUs *once at
> startup*, so a worker that started before the loss keeps running and simply
> registers `GPU: 0`.
>
> **Fix — restart the worker.** The allowance cannot be restored in place:
>
> ```bash
> ssh spark5 'docker restart rayworker'
> ```
>
> **Diagnose this class of fault by running `nvidia-smi` inside the container,
> never on the host.** The host is healthy in exactly this failure, so a host
> check reports success and hides it. Cross-check against `ray status`: a GPU
> total below the alive-node count means some worker registered without its
> accelerator.

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
2. **Start the four vLLM servers** (below). They are independent; order among
   them does not matter — except that the two spark4 heads must each carry an
   explicit `--gpu-memory-utilization`, or whichever starts first takes the
   whole node (see 3b).
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

### 3. spark4 — AI45Research/AgentDoG-Qwen3-4B (binary head) on :8001

This is the **1.0-class** model and the sweep path. The 1.5 variants on
`fd00:200::2` (spark2) are *not* the sweep path — do not substitute them.

Container port is 8000 mapped to host **8001**.

```bash
docker run -d --name agentdog10 --gpus all -p 8001:8000 \
  -e HF_HUB_OFFLINE=1 \
  -v $HOME/.cache/huggingface:/root/.cache/huggingface \
  eugr/spark-vllm:latest \
  vllm serve AI45Research/AgentDoG-Qwen3-4B --max-model-len 16384 --gpu-memory-utilization 0.20
```

> **`--gpu-memory-utilization 0.20` is a W12 addition to the recovered command,
> and the one place this file is not verbatim.** The recovered command carried
> no such flag, so it inherited the image default of **0.92** — which on a
> 119 GiB unified node reserved ~101 GiB of KV cache (733,744 tokens, 44.78x
> concurrency at 16384) for a 4B model, leaving 2 GiB free and making it
> impossible to serve the FG head beside it. The auditor sends **one** 16k
> request at a time, so 0.20 is still ample: measured, it leaves the binary
> head 13.49 GiB of KV cache (98,224 tokens, 6.00x concurrency at 16384) and
> the FG head 12.02 GiB (87,488 tokens, 5.34x). Two heads at 0.20 use ~57 of
> 119 GiB with ~62 GiB still free.
>
> This changes KV cache capacity only — not weights, dtype, or logits. At
> `temperature: 0` the head is bitwise stable *within* a configuration (3/3
> identical replies on every trial, both heads, W12). Whether the cap moves an
> answer *across* configurations is a separate question and is NOT settled
> here: re-serving W11's cell under 0.20 reproduced 3 of its 5 audits on
> byte-identical inputs and changed 2 — including the single record W11's P10
> result rested on. See `docs/w12-fg-head.md` for what that is and is not
> evidence of before relying on either run's labels.

### 3b. spark4 — AI45Research/AgentDoG-FG-Qwen3-4B (fine-grained head) on :8002

The **separate fine-grained checkpoint**. AgentDoG 1.0 ships the binary and FG
heads as different checkpoints, and the published fine-grained accuracies
(Risk Source 82.0 / Failure Mode 32.4 / Real-world Harm 58.4) — P10's whole
baseline — belong to *this* one. It runs **beside** the binary head, not
instead of it: the binary head is the observer every result to date was
measured against, so both stay served and the observer is selected per run.

Container port is 8000 mapped to host **8002**. Same flags as the binary head,
same `--max-model-len`, and no tool-calling parser.

```bash
docker run -d --name agentdogfg --gpus all -p 8002:8000 \
  -e HF_HUB_OFFLINE=1 \
  -v $HOME/.cache/huggingface:/root/.cache/huggingface \
  eugr/spark-vllm:latest \
  vllm serve AI45Research/AgentDoG-FG-Qwen3-4B --max-model-len 16384 --gpu-memory-utilization 0.20
```

> **The FG weights were not on the node.** W11 recorded them as "already
> downloaded at `~/.cache/huggingface/hub/models--AI45Research--AgentDoG-FG-Qwen3-4B/`".
> On spark4 that path did not exist at all, and on spark1 only the *lock*
> directory `hub/.locks/models--AI45Research--AgentDoG-FG-Qwen3-4B/` existed —
> 4 KB of empty lock files from an attempt that fetched zero weight bytes. A
> `.locks/` entry matches the same glob as the model directory and is what made
> an absent download look present. Check for `snapshots/`, not for the name.
>
> `HF_HUB_OFFLINE=1` means the serving container will not fetch them. Pull into
> the mounted cache first, pinned to a revision, with the same image:
>
> ```bash
> docker run --rm -e HF_HUB_OFFLINE=0 \
>   -v $HOME/.cache/huggingface:/root/.cache/huggingface \
>   eugr/spark-vllm:latest \
>   python3 -c "from huggingface_hub import snapshot_download; \
> snapshot_download('AI45Research/AgentDoG-FG-Qwen3-4B', \
>   revision='d4f62821e09f67b6dbb084aa20e83a7321255df8', \
>   ignore_patterns=['figures/*'])"
> ```
>
> ~8.3 GiB, 2 safetensors shards, Apache 2.0, public (ungated).

> **A revision-pinned download writes no `refs/main`, and offline serving needs
> one.** `snapshot_download(revision=<sha>)` populates `blobs/` and
> `snapshots/<sha>/` but creates no `refs/` directory at all. `vllm serve
> <repo>` with no `--revision` resolves the `main` ref, so under
> `HF_HUB_OFFLINE=1` it aborts with `LocalEntryNotFoundError: Cannot find an
> appropriate cached snapshot folder for the specified revision` — with the
> weights sitting complete on disk. Write the ref once, to the sha you pinned:
>
> ```bash
> docker run --rm -v $HOME/.cache/huggingface:/root/.cache/huggingface \
>   eugr/spark-vllm:latest bash -c \
>   'd=/root/.cache/huggingface/hub/models--AI45Research--AgentDoG-FG-Qwen3-4B; \
>    mkdir -p $d/refs && printf d4f62821e09f67b6dbb084aa20e83a7321255df8 > $d/refs/main'
> ```
>
> Compare against a healthy model directory: the binary head's has
> `refs/main` holding `e7d92a7b650abad6e4aba63f49c4ea63cf1c45b8`.

> **Both heads must carry an explicit `--gpu-memory-utilization`.** vLLM sizes
> the fraction against *total* memory but refuses to start if that much is not
> *free*, so whichever head starts first at the 0.92 default takes the node and
> the second one cannot start. Two heads at 0.20 use ~48 of 119 GiB and leave
> ~70 GiB idle.

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

Prefix caching is **on** for all four, and must stay on — the affinity router
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
curl -s http://[fd00:200::4]:8002/v1/models   | jq -r '.data[].id'   # AI45Research/AgentDoG-FG-Qwen3-4B

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

spark1 reaches **every** other node by key. `~/.ssh/config` defines `spark2`
through `spark8`, plus `spark3-fab` / `spark6-fab` / `spark4-v4` for alternate
addresses on the three original serving nodes. spark1's public key
(`spark1-saster-push`) is installed in `~/.ssh/authorized_keys` on all seven —
spark3, spark4 and spark6 from the original build, and spark2, spark5, spark7
and spark8 added 2026-08-31.

The four added aliases are keyed off the **fabric** address (`fd00:200::N`)
rather than the LAN, because those nodes hold no DHCP reservation and their
`192.168.1.x` addresses can move. Note also the cloned-host-key caveat in
Topology: `known_hosts` cannot tell spark2 from spark3, or spark7 from spark8.

Verify the whole set at once:

```bash
for h in spark2 spark3 spark4 spark5 spark6 spark7 spark8; do
  printf '%-8s -> ' "$h"; ssh -o BatchMode=yes -o ConnectTimeout=8 "$h" hostname
done
```

Note that spark4 is reachable from spark1 over both the fabric (`fd00:200::4`)
and the LAN (`192.168.1.201`), but a host with no global IPv6 route cannot reach
it at all on the fabric address — drive bring-up from spark1, or use
`192.168.1.201`.
