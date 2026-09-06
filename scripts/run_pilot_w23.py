#!/usr/bin/env python3
"""W23 — the Stage 3 pilot, as specified: all-on config, Qwen, both
obstruction arms, both fixture modes, both routes on the compromised arm,
k=5, vendor-shaped excluded.

Six cells, paired seeds per (precondition, mode) stratum so the two route
cells of a stratum share seeds (W17's design). One subprocess per cell,
state file checkpointed per cell, canary once at start.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, "/home/lbsuto/halctf-agent")
REPO = Path(__file__).resolve().parent.parent
OUT = Path(os.environ.get("W23_OUT", REPO / "runs/w23_pilot"))
if not OUT.is_absolute():
    OUT = (REPO / OUT).resolve()
CELLS = OUT / "cells"
STATE = OUT / "pilot_state.json"
VICTIM = "Qwen/Qwen3-8B"
ROUTER_URL = "http://localhost:8080"
K = int(os.environ.get("W23_K", "5"))
SEED_BASE = int(os.environ.get("W23_SEED_BASE", "20260906"))
SEED_STRIDE = 1000
STRATA = (("obstructed", "compromised"), ("obstructed", "induced"),
          ("unobstructed", "compromised"), ("unobstructed", "induced"))


def cell_plan() -> list[dict]:
    cells = []
    for pre_name, pre_val in (("obstructed", "1"), ("unobstructed", "0")):
        for mode in ("compromised", "induced"):
            routes = ("grant", "firewall") if mode == "compromised" else ("agent",)
            so = STRATA.index((pre_name, mode))
            for route in routes:
                cells.append({
                    "id": f"pilot__all__{pre_name}__{mode}__{route}",
                    "env": {"W9_DEFENSE": "all", "W9_OBSTRUCTED": pre_val, "W9_MODE": mode,
                            "W9_ROUTE": route, "W9_L2_RULES": "4"},
                    "axes": {"defense_config": "all", "precondition": pre_name,
                             "fixture_mode": f"carl-ops-{mode}", "route": route,
                             "l2_rule_count": 4, "saster_category": "SASTER-31"},
                    "stratum": [pre_name, mode], "seed_base": SEED_BASE + so * SEED_STRIDE,
                    "seeds": [SEED_BASE + so * SEED_STRIDE + i for i in range(K)],
                })
    return cells


def canary() -> dict:
    from importlib import import_module

    from saster_harness.campaign import ServingConfig, build_router
    from saster_harness.canary import canary_manifest_block, enforce_canary_gate, run_canary

    telemetry = import_module("halagent.telemetry")
    writer = telemetry.TelemetryWriter(OUT / "canary_Qwen3-8B.jsonl")
    cfg = ServingConfig(campaign_id=f"canary::{VICTIM}", model=VICTIM, base_url=ROUTER_URL)
    results = {VICTIM: run_canary(build_router(cfg, writer), VICTIM, 10, campaign_id=f"canary::{VICTIM}")}
    block = canary_manifest_block(results)
    enforce_canary_gate(results)
    return block


def run_cell(cell: dict) -> dict:
    cdir = CELLS / cell["id"]
    env = dict(os.environ)
    env.update(cell["env"])
    env.update({"W9_ENVELOPE": "not_computed", "W9_OBSERVER": "binary", "W9_K": str(K),
                "W9_OUT": str(cdir), "W9_RUN_ID": f"w23-{cell['id']}",
                "W9_CAMPAIGN_ID": f"w23-{cell['id']}", "W9_SKIP_CANARY": "1",
                "W9_OVERWRITE": "1", "W9_SEED": str(cell["seed_base"]), "W9_VICTIM": VICTIM,
                "PYTHONPATH": "/home/lbsuto/halctf-agent"})
    t0 = time.monotonic()
    proc = subprocess.run([str(REPO / ".venv/bin/python"), str(REPO / "scripts/run_cell_w9.py")],
                          cwd=REPO, env=env, capture_output=True, text=True, timeout=7200)
    (cdir.parent / f"{cell['id']}.console.log").write_text(proc.stdout + "\n" + proc.stderr)
    traj = cdir / "trajectories.jsonl"
    n = sum(1 for _ in traj.open()) if traj.exists() else 0
    return {"id": cell["id"], "axes": cell["axes"], "seeds": cell["seeds"], "returncode": proc.returncode,
            "ok": proc.returncode == 0 and n == K, "n_records": n, "expected_records": K,
            "wall_s": round(time.monotonic() - t0, 2), "dir": str(cdir.relative_to(REPO)),
            "finished_utc": datetime.now(UTC).isoformat(),
            "stderr_tail": proc.stderr.strip()[-1200:] if proc.returncode != 0 else ""}


def main() -> None:
    if STATE.exists():
        state = json.loads(STATE.read_text())
    else:
        OUT.mkdir(parents=True, exist_ok=True); CELLS.mkdir(exist_ok=True)
        state = {"started_utc": datetime.now(UTC).isoformat(), "cells": {},
                 "role": "W23 PILOT — Stage 3; all-on, Qwen, both arms, both modes, both routes, k=5; "
                         "vendor-shaped excluded", "victim": VICTIM, "k": K, "seed_base": SEED_BASE}
    if "canary" not in state:
        print("canary ...", flush=True)
        state["canary"] = canary()
        STATE.write_text(json.dumps(state, indent=2))
    plan = cell_plan()
    todo = [c for c in plan if not state["cells"].get(c["id"], {}).get("ok")]
    print(f"{len(plan)} cells, {len(todo)} to run, k={K}", flush=True)
    for i, cell in enumerate(todo, 1):
        print(f"[{i}/{len(todo)}] {cell['id']} ...", end=" ", flush=True)
        r = run_cell(cell)
        state["cells"][cell["id"]] = r
        STATE.write_text(json.dumps(state, indent=2))
        print(("ok" if r["ok"] else f"FAIL rc={r['returncode']}") + f" {r['n_records']}/{K} {r['wall_s']}s", flush=True)
    state["finished_utc"] = datetime.now(UTC).isoformat()
    STATE.write_text(json.dumps(state, indent=2))
    print("pilot complete:", sum(c["ok"] for c in state["cells"].values()), "ok of", len(plan))


if __name__ == "__main__":
    main()
