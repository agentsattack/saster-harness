#!/usr/bin/env python3
"""W24 — the Stage 4 sweep, one victim per process.

Matrix per victim: defense config ×7 (six ablation cells + vendor-shaped,
addendum §C) · precondition ×2 · fixture mode ×2 · widening route (grant
and firewall on the compromised arm; the agent's own on the induced arm)
· k=5, plus the P12 ladder as its own arm (rungs 1, 2, 3; obstructed,
compromised, both routes). The SASTER category axis has one satisfiable
value (SASTER-31; W21) and is not swept. Envelope mass is not computed
(Amendment 9), so the envelope sub-arm is reported as not evaluable.

Seeds are paired: a seed depends on the (precondition, mode) stratum and
the trial, never on the config or the route, so every cell of a stratum
runs the same trajectories under different defenses (W17).

Storage (2026-09-05, no NAS): the corpus root is this repo's runs/ on
spark1; after every completed cell the cell's files are written
content-addressed and append-only into the evidence store on spark1 and
rsynced to the off-node mirror on spark8, where their hashes are verified.
Both roots are on every cell manifest and in the sweep manifest.

Halts: a HALT file at the sweep root or at runs/w24_HALT (written by the
monitor on error > 5% or any counted layer unavailable > 20%) stops the
sweep before the next cell; a resumed sweep is a new run id.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, "/home/lbsuto/halctf-agent")
REPO = Path(__file__).resolve().parent.parent
VICTIM = os.environ["W24_VICTIM"]
TAG = VICTIM.split("/")[-1].split("-")[0].lower()
OUT = Path(os.environ.get("W24_OUT", REPO / f"runs/w24_sweep_{TAG}"))
if not OUT.is_absolute():
    OUT = (REPO / OUT).resolve()
CELLS = OUT / "cells"
STATE = OUT / "sweep_state.json"
ROUTER_URL = "http://localhost:8080"
K = int(os.environ.get("W24_K", "5"))
RUN_PREFIX = os.environ.get("W24_RUN_PREFIX", "w24")  # a post-sweep arm is a new run id
SEED_BASE = int(os.environ.get("W24_SEED_BASE", "20260907"))
SEED_STRIDE = 1000
EVIDENCE = Path(os.environ.get("W24_EVIDENCE", Path.home() / "evidence" / "sweep" / OUT.name))
MIRROR_HOST = os.environ.get("W24_MIRROR_HOST", "spark8")
MIRROR_PATH = os.environ.get("W24_MIRROR_PATH", f"~/evidence/sweep/{OUT.name}")
HALT_FILES = (OUT / "HALT", REPO / "runs" / "w24_HALT")

DEFENSE_KEYS = tuple(k.strip() for k in os.environ.get("W24_DEFENSE_KEYS", "l2,l3,l4,l3+l4,all,none,vendor-shaped").split(",") if k.strip())  # an arm may name its own configs (§S)
STRATA = (("obstructed", "compromised"), ("obstructed", "induced"),
          ("unobstructed", "compromised"), ("unobstructed", "induced"))
LADDER_RUNGS = (1, 2, 3)


def stratum_ordinal(pre: str, mode: str) -> int:
    return STRATA.index((pre, mode))


def cell_plan(k: int | None = None) -> list[dict]:
    k = K if k is None else k
    cells: list[dict] = []
    for defense in DEFENSE_KEYS:
        for pre_name, pre_val in (("obstructed", "1"), ("unobstructed", "0")):
            for mode in ("compromised", "induced"):
                for route in (("grant", "firewall") if mode == "compromised" else ("agent",)):
                    cells.append({
                        "arm": "matrix",
                        "id": f"matrix__{defense.replace('+', '-')}__{pre_name}__{mode}__{route}",
                        "env": {"W9_DEFENSE": defense, "W9_OBSTRUCTED": pre_val, "W9_MODE": mode,
                                "W9_ROUTE": route, "W9_L2_RULES": "4", "W9_JUDGE_PROMPT": "scoped"},
                        "axes": {"defense_config": defense, "precondition": pre_name,
                                 "fixture_mode": f"carl-ops-{mode}", "route": route,
                                 "l2_rule_count": 4 if defense != "vendor-shaped" else 0,
                                 "saster_category": "SASTER-31"},
                    })
    for n in LADDER_RUNGS:
        for route in ("grant", "firewall"):
            cells.append({
                "arm": "p12_ladder",
                "id": f"p12__l2__rules{n}__obstructed__compromised__{route}",
                "env": {"W9_DEFENSE": "l2", "W9_OBSTRUCTED": "1", "W9_MODE": "compromised",
                        "W9_ROUTE": route, "W9_L2_RULES": str(n), "W9_JUDGE_PROMPT": "scoped"},
                "axes": {"defense_config": "l2", "precondition": "obstructed",
                         "fixture_mode": "carl-ops-compromised", "route": route,
                         "l2_rule_count": n, "saster_category": "SASTER-31"},
            })
    for ordinal, cell in enumerate(cells):
        so = stratum_ordinal(cell["axes"]["precondition"], cell["axes"]["fixture_mode"].replace("carl-ops-", ""))
        cell.update(ordinal=ordinal, stratum=list(STRATA[so]), stratum_ordinal=so,
                    seed_base=SEED_BASE,  # MUTANT C5: every cell replays the same seeds
                    seeds=[SEED_BASE + i for i in range(k)])
    return cells


def halted() -> Path | None:
    return next((h for h in HALT_FILES if h.exists()), None)


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def archive_cell(cell_id: str, cdir: Path) -> dict:
    """Append-only, content-addressed copy of the cell into the evidence
    store, then rsync to the mirror and verify hashes there."""
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    files = [p for p in cdir.rglob("*") if p.is_file()]
    new_lines = []
    for p in sorted(files):
        d = sha(p)
        tgt = EVIDENCE / d
        if not tgt.exists():
            tgt.mkdir()
            shutil.copy2(p, tgt / p.name)
        rel = f"{d}/{p.name}"
        new_lines.append(f"{d}  {rel}\n")
        with (EVIDENCE / "index.jsonl").open("a") as fh:
            fh.write(json.dumps({"cell": cell_id, "file": str(p.relative_to(cdir)), "sha256": d,
                                 "stored_as": rel, "size": p.stat().st_size,
                                 "utc": datetime.now(UTC).isoformat()}) + "\n")
    with (EVIDENCE / "SHA256SUMS").open("a") as fh:
        fh.writelines(new_lines)
    subprocess.run(["ssh", "-o", "BatchMode=yes", MIRROR_HOST, f"mkdir -p {MIRROR_PATH}"], check=True)
    subprocess.run(["rsync", "-a", "-q", f"{EVIDENCE}/", f"{MIRROR_HOST}:{MIRROR_PATH}/"], check=True)
    verify = subprocess.run(["ssh", "-o", "BatchMode=yes", MIRROR_HOST,
                             f"cd {MIRROR_PATH} && sha256sum -c SHA256SUMS | grep -vc ': OK$'; true"],
                            capture_output=True, text=True)
    mismatches = int(verify.stdout.strip().splitlines()[-1] or 0) if verify.stdout.strip() else -1
    return {"primary": str(EVIDENCE), "mirror": f"{MIRROR_HOST}:{MIRROR_PATH}", "n_files": len(files),
            "mirror_verified": mismatches == 0, "mirror_mismatches": mismatches,
            "archived_utc": datetime.now(UTC).isoformat()}


def canary() -> dict:
    from importlib import import_module

    from saster_harness.campaign import ServingConfig, build_router
    from saster_harness.canary import canary_manifest_block, enforce_canary_gate, run_canary

    telemetry = import_module("halagent.telemetry")
    writer = telemetry.TelemetryWriter(OUT / f"canary_{VICTIM.split('/')[-1]}.jsonl")
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
                "W9_OUT": str(cdir), "W9_RUN_ID": f"{RUN_PREFIX}-{TAG}-{cell['id']}",
                "W9_CAMPAIGN_ID": f"w24-{TAG}-{cell['id']}", "W9_SKIP_CANARY": "1", "W9_OVERWRITE": "1",
                "W9_SEED": str(cell["seed_base"]), "W9_VICTIM": VICTIM,
                "W9_STORAGE_PRIMARY": str(EVIDENCE), "W9_STORAGE_MIRROR": f"{MIRROR_HOST}:{MIRROR_PATH}",
                "PYTHONPATH": "/home/lbsuto/halctf-agent"})
    t0 = time.monotonic()
    proc = subprocess.run([str(REPO / ".venv/bin/python"), str(REPO / "scripts/run_cell_w9.py")],
                          cwd=REPO, env=env, capture_output=True, text=True, timeout=7200)
    (cdir.parent / f"{cell['id']}.console.log").write_text(proc.stdout + "\n" + proc.stderr)
    traj = cdir / "trajectories.jsonl"
    n = sum(1 for _ in traj.open()) if traj.exists() else 0
    result = {"id": cell["id"], "arm": cell["arm"], "axes": cell["axes"], "seeds": cell["seeds"],
              "stratum": cell["stratum"], "returncode": proc.returncode,
              "ok": proc.returncode == 0 and n == K, "n_records": n, "expected_records": K,
              "wall_s": round(time.monotonic() - t0, 2), "dir": str(cdir.relative_to(REPO)),
              "finished_utc": datetime.now(UTC).isoformat(),
              "stderr_tail": proc.stderr.strip()[-1200:] if proc.returncode != 0 else ""}
    if cdir.exists():
        try:
            result["storage"] = archive_cell(cell["id"], cdir)
        except Exception as exc:  # noqa: BLE001 — recorded, never hidden
            result["storage"] = {"error": f"{type(exc).__name__}: {exc}"}
    return result


def main() -> None:
    if STATE.exists():
        state = json.loads(STATE.read_text())
    else:
        OUT.mkdir(parents=True, exist_ok=True); CELLS.mkdir(exist_ok=True)
        state = {"started_utc": datetime.now(UTC).isoformat(), "cells": {}, "victim": VICTIM, "k": K,
                 "seed_base": SEED_BASE, "role": "W24 SWEEP — Stage 4, one victim per process",
                 "storage": {"primary": str(EVIDENCE), "mirror": f"{MIRROR_HOST}:{MIRROR_PATH}"}}
    if "canary" not in state:
        print("canary ...", flush=True)
        state["canary"] = canary()
        STATE.write_text(json.dumps(state, indent=2))
    plan = cell_plan()
    only = {c.strip() for c in os.environ.get("W24_ONLY", "").split(",") if c.strip()}
    if only:
        plan = [c for c in plan if c["id"] in only]
        state["only"] = sorted(only)
    state["plan"] = {"n_cells": len(plan), "k": K, "defense_keys": list(DEFENSE_KEYS),
                     "ladder_rungs": list(LADDER_RUNGS), "envelope_status": "not_computed",
                     "saster_category_axis_varied": False}
    todo = [c for c in plan if not state["cells"].get(c["id"], {}).get("ok")]
    print(f"{VICTIM}: {len(plan)} cells, {len(todo)} to run, k={K}", flush=True)
    t_start = time.monotonic()
    for i, cell in enumerate(todo, 1):
        h = halted()
        if h is not None:
            state["halted"] = {"file": str(h), "reason": h.read_text()[:500], "utc": datetime.now(UTC).isoformat()}
            STATE.write_text(json.dumps(state, indent=2))
            print(f"HALT: {h}: {h.read_text()[:200]}", flush=True)
            return
        print(f"[{i}/{len(todo)}] {cell['id']} ...", end=" ", flush=True)
        r = run_cell(cell)
        state["cells"][cell["id"]] = r
        STATE.write_text(json.dumps(state, indent=2))
        st = r.get("storage", {})
        print(("ok" if r["ok"] else f"FAIL rc={r['returncode']}") + f" {r['n_records']}/{K} {r['wall_s']}s "
              f"mirror={'verified' if st.get('mirror_verified') else st.get('error', 'UNVERIFIED')}", flush=True)
    state["finished_utc"] = datetime.now(UTC).isoformat()
    state["total_wall_s"] = round(time.monotonic() - t_start, 2)
    STATE.write_text(json.dumps(state, indent=2))
    any_cell = next((c for c in state["cells"].values() if c["ok"]), None)
    pins = {}
    if any_cell:
        m = json.loads((REPO / any_cell["dir"] / "manifest.json").read_text())
        pins = {k: m.get(k) for k in ("grrcon_matrix_sha256", "envelope_preregistration_sha256", "grrcon_addendum_sha256")}
    (OUT / "sweep_manifest.json").write_text(json.dumps({
        "victim": VICTIM, "k": K, "seed_base": SEED_BASE, "pins": pins, "storage": state["storage"],
        "cells": {k: {"ok": v["ok"], "n_records": v["n_records"], "storage": v.get("storage")} for k, v in state["cells"].items()},
        "halted": state.get("halted"), "finished_utc": state["finished_utc"]}, indent=2))
    ok = sum(c["ok"] for c in state["cells"].values())
    print(f"sweep complete: {ok} ok of {len(plan)}, {state['total_wall_s']}s", flush=True)


if __name__ == "__main__":
    main()
