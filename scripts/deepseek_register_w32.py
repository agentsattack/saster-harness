#!/usr/bin/env python3
"""W32 — addendum §W: DeepSeek-V4.1-Flash registration checks.

Verifies, against the served endpoint, the three logprob channels the
envelope instrument reads (completions ``logprobs``; chat ``top_logprobs``;
echo teacher-forcing over template-rendered ids), runs the pre-sweep canary
through the router with the family's template kwargs, records the spark1
memory headroom with the shard resident, and writes the manifest blocks the
judge and victim registrations carry. Writes under
``runs/w32_deepseek_registration/`` and refuses to overwrite.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from saster_defense.judge import JudgeGuard  # noqa: E402
from saster_defense.manifest import grrcon_addendum_sha256  # noqa: E402
from saster_harness.campaign import ServingConfig, build_router, template_kwargs_for  # noqa: E402
from saster_harness.canary import canary_manifest_block, run_canary  # noqa: E402
from saster_harness.families import FAMILIES, family_key_for_model, judge_families_for  # noqa: E402

MODEL = "deepseek-v4.1-flash"
ENDPOINT = os.environ.get("W32_DEEPSEEK", "http://127.0.0.1:8000")
ROUTER = os.environ.get("W9_ROUTER", "http://127.0.0.1:8080")
OUT = Path(os.environ.get("W32_OUT", REPO / "runs/w32_deepseek_registration"))
CANARY_N = 10
PROMPT = "Reply with one word: yes or no. Is water wet?"


def post(path: str, body: dict, timeout: float = 120) -> dict:
    r = httpx.post(f"{ENDPOINT}{path}", json=body, timeout=timeout)
    r.raise_for_status()
    return r.json()


def channels() -> dict:
    out: dict = {}
    # 1. completions logprobs over a plain prompt
    d = post("/v1/completions", {"model": MODEL, "prompt": "The capital of France is", "max_tokens": 3,
                                 "temperature": 0, "logprobs": 1})
    lp = d["choices"][0].get("logprobs") or {}
    out["completions_logprobs"] = {"ok": bool(lp.get("token_logprobs")), "tokens": lp.get("tokens"),
                                   "token_logprobs": lp.get("token_logprobs")}
    # 2. chat top_logprobs
    d = post("/v1/chat/completions", {"model": MODEL, "messages": [{"role": "user", "content": PROMPT}],
                                      "max_tokens": 3, "temperature": 0, "logprobs": True, "top_logprobs": 5,
                                      "chat_template_kwargs": template_kwargs_for(MODEL)})
    c = d["choices"][0]
    content = (c.get("logprobs") or {}).get("content") or []
    out["chat_top_logprobs"] = {"ok": bool(content) and all(len(p.get("top_logprobs", [])) == 5 for p in content),
                                "content": c["message"]["content"], "positions": len(content),
                                "top0": [(t["token"], round(t["logprob"], 3)) for t in content[0]["top_logprobs"]] if content else None}
    # 3. echo teacher-forcing over template-rendered ids: render must come from
    #    the server (render route, else /tokenize with the same body — §W)
    body = {"model": MODEL, "messages": [{"role": "user", "content": PROMPT}], "add_generation_prompt": True,
            "chat_template_kwargs": template_kwargs_for(MODEL)}
    r = httpx.post(f"{ENDPOINT}/v1/chat/completions/render", json=body, timeout=60)
    render_route = r.status_code
    if r.status_code == 200:
        prefix = r.json()["token_ids"]
        rendered_by = "/v1/chat/completions/render"
    else:
        prefix = post("/tokenize", body)["tokens"]
        rendered_by = "/tokenize"
    suffix = post("/tokenize", {"model": MODEL, "prompt": "Yes.", "add_special_tokens": False})["tokens"]
    d = post("/v1/completions", {"model": MODEL, "prompt": prefix + suffix, "max_tokens": 1, "temperature": 0,
                                 "echo": True, "logprobs": 1})
    lp = d["choices"][0].get("logprobs") or {}
    tl = lp.get("token_logprobs") or []
    n = len(prefix) + len(suffix)
    out["echo_teacher_forcing"] = {"ok": len(tl) >= n and all(x is not None for x in tl[len(prefix):n]),
                                   "render_route_status": render_route, "rendered_by": rendered_by,
                                   "n_prefix": len(prefix), "n_suffix": len(suffix), "n_echoed": len(tl),
                                   "suffix_logprobs": [round(x, 4) for x in tl[len(prefix):n]],
                                   "suffix_tokens": (lp.get("tokens") or [])[len(prefix):n]}
    out["all_three"] = all(v["ok"] for k, v in out.items() if isinstance(v, dict) and "ok" in v)
    return out


def canary() -> dict:
    from saster_harness.campaign import import_halagent_router

    import_halagent_router()  # puts the sibling checkout on sys.path, as the runner does
    telemetry = import_module("halagent.telemetry")
    writer = telemetry.TelemetryWriter(OUT / "canary_deepseek.jsonl")
    cfg = ServingConfig(campaign_id=f"canary::{MODEL}", model=MODEL, base_url=ROUTER)
    results = {MODEL: run_canary(build_router(cfg, writer), MODEL, CANARY_N, campaign_id=f"canary::{MODEL}")}
    block = canary_manifest_block(results)
    block["scope"] = "victim family C registration (§W); through the router with the family's template kwargs"
    return block


def headroom() -> dict:
    mem = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        k, v = line.split(":", 1)
        if k in ("MemTotal", "MemFree", "MemAvailable", "Buffers", "Cached", "Shmem"):
            mem[k] = int(v.strip().split()[0]) // 1024  # MiB
    docker = subprocess.run(["docker", "ps", "--format", "{{.Names}} {{.Image}} {{.Status}}"],
                            capture_output=True, text=True).stdout.strip().splitlines()
    return {"host": "spark1", "MiB": mem, "GiB_available": round(mem.get("MemAvailable", 0) / 1024, 1),
            "GiB_total": round(mem.get("MemTotal", 0) / 1024, 1), "containers": docker,
            "note": "unified memory; DeepSeek TP=4 shard resident at --gpu-memory-utilization 0.80 on this node"}


def main() -> None:
    if OUT.exists():
        raise SystemExit(f"refusing to overwrite {OUT}")
    OUT.mkdir(parents=True)
    served = httpx.get(f"{ENDPOINT}/v1/models", timeout=10).json()["data"][0]
    fam = FAMILIES["deepseek"]
    judge = JudgeGuard(model=MODEL, endpoint=ENDPOINT, prompt_style="scoped")
    gate = REPO / "runs/w23_judge_gate_deepseek-v4.1-flash_scoped.json"
    gate_report = json.loads(gate.read_text()) if gate.exists() else None
    ch = channels()
    (OUT / "channels.json").write_text(json.dumps(ch, indent=2))
    print("channels:", {k: v["ok"] for k, v in ch.items() if isinstance(v, dict)}, "all_three", ch["all_three"])
    can = canary()
    (OUT / "canary.json").write_text(json.dumps(can, indent=2))
    print("canary:", json.dumps(can["per_model"][MODEL]))
    reg = {
        "run_id": "w32-deepseek-registration-20260912", "role": "addendum §W registrations",
        "measured_utc": datetime.now(UTC).isoformat(),
        "code_commit": subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True).stdout.strip(),
        "grrcon_addendum_sha256": grrcon_addendum_sha256(),
        "served": {"endpoint": ENDPOINT, "id": served.get("id"), "max_model_len": served.get("max_model_len"),
                   "image": "vllm/vllm-openai:deepseekv41-flash-0909-arm64",
                   "image_digest": "sha256:714a937591e162044e9142b0ba2ed18bd21734edcffb59f651db6ced941a2040",
                   "tensor_parallel": 4, "nodes": "spark1-spark4", "gpu_memory_utilization": 0.80},
        "judge_family_3": {
            "role": "per_action_judge", "model": MODEL, "endpoint": ENDPOINT, "backend": judge.backend,
            "family": family_key_for_model(MODEL), "prompt_style": "scoped", "prompt_sha256": judge.prompt_sha256,
            "max_tokens": judge.max_tokens, "temperature": 0.0, "sees_reasoning": False, "sees_history": False,
            "chat_template_kwargs": template_kwargs_for(MODEL),
            "section_n_gate": None if gate_report is None else {
                "report": str(gate.relative_to(REPO)), "allowed": gate_report["allowed"], "n_actions": gate_report["n_actions"],
                "allowed_rate": gate_report["allowed_rate"], "controls_intact": gate_report["controls_intact"],
                "n_controls": gate_report["n_controls"], "passed": gate_report["passed"]},
            "panel_for_qwen3": [f.key for f in judge_families_for("Qwen/Qwen3-8B")],
            "panel_for_mistral": [f.key for f in judge_families_for("mistralai/Ministral-8B-Instruct-2410")],
        },
        "victim_family_c": {
            "key": fam.key, "model": fam.model, "tool_call_parser": fam.tool_call_parser, "node": fam.node,
            "tool_choice": fam.tool_choice, "chat_template_kwargs": fam.chat_template_kwargs,
            "logprob_channels": {k: v["ok"] for k, v in ch.items() if isinstance(v, dict)},
            "render_route": ch["echo_teacher_forcing"]["rendered_by"],
            "canary": can["per_model"][MODEL],
            "arm_a_rider": "tests/test_instrument_arm_a_roundtrip.py (parametrised over the registry; result recorded beside this file)",
        },
        "spark1_headroom": headroom(),
    }
    (OUT / "registration.json").write_text(json.dumps(reg, indent=2))
    print("headroom:", reg["spark1_headroom"]["GiB_available"], "GiB available of", reg["spark1_headroom"]["GiB_total"])


if __name__ == "__main__":
    main()
