#!/usr/bin/env python3
"""W14 — the single-victim matrix. THIS IS CORPUS, not a dry run.

Qwen3-8B thinking-off, envelope not computed (schema AMENDMENT 9), L4 observed
by the BINARY AgentDoG head — the checkpoint every result to date was measured
against.

Axes actually swept, per ``docs/grrcon-test-matrix.md`` §4:

    defense config  × 6   l2 | l3 | l4 | l3+l4 | all | none
    precondition    × 2   obstructed | unobstructed
    fixture mode    × 2   carl-ops-compromised | carl-ops-induced
    k               = 5
                    ----
                     24 cells, 120 trials

Plus the P12 permissiveness ladder as its own arm: L2 alone at 1, 2 and 3 Rego
rules, everything else held — 3 cells, 15 trials.

**The SASTER category axis is NOT swept, and this is deliberate.**
``saster_category`` is a label written into each record; nothing in the
model-driven path reads it, and there is one carl-ops scenario. Sweeping it
would have produced seven byte-identical cells differing by a string and a
corpus whose category column read as coverage it does not have. Each cell's
manifest carries ``saster_category_axis.varied = false`` and says so.

Checkpointing: one subprocess per cell, each writing its own directory, with a
state file updated as cells land. An interruption loses at most the cell in
flight; re-running skips every cell already marked complete.
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
OUT = Path(os.environ.get("W14_OUT", REPO / "runs/w14_corpus_qwen_single_victim"))
CELLS = OUT / "cells"
STATE = OUT / "matrix_state.json"

VICTIM = "Qwen/Qwen3-8B"
ROUTER_URL = "http://localhost:8080"
K = int(os.environ.get("W14_K", "5"))

#: Seed derivation (W16). Every cell gets its own disjoint block of the seed
#: space, so no two cells can replay the same trajectory.
#:
#: W14 shipped without this: every cell ran ``base_seed=20260830``, so 135
#: records stood on 5 distinct seeds — a 13.5x inflation of the apparent
#: sample size, and the reason its induced arm read 0/60 when it was 0/5.
#:
#: seed(cell, trial) = SEED_BASE + ordinal(cell) * SEED_STRIDE + trial
#:
#: Ordinals come from the fixed plan order, so a re-run reproduces the same
#: seeds exactly. The stride bounds k: a cell may not run more than
#: SEED_STRIDE trials without colliding with the next cell's block, and
#: :func:`cell_plan` asserts that.
SEED_BASE = int(os.environ.get("W14_SEED_BASE", "20260901"))
SEED_STRIDE = 1000

DEFENSE_KEYS = ("l2", "l3", "l4", "l3+l4", "all", "none")
PRECONDITIONS = (("obstructed", "1"), ("unobstructed", "0"))
FIXTURE_MODES = ("compromised", "induced")
LADDER_RUNGS = (1, 2, 3)


def cell_plan(k: int | None = None) -> list[dict]:
    """Every cell, in a fixed order so a resumed run reproduces the sequence.

    Each cell carries its own ``seed_base``, disjoint from every other cell's
    (W16). ``k`` defaults to the module-level K and is a parameter so a test
    can check the disjointness property at other trial counts.
    """
    k = K if k is None else k
    if k > SEED_STRIDE:
        raise ValueError(
            f"k={k} exceeds SEED_STRIDE={SEED_STRIDE}; cell seed blocks would "
            f"overlap and two cells would replay the same trajectory"
        )
    cells: list[dict] = []
    for defense in DEFENSE_KEYS:
        for pre_name, pre_val in PRECONDITIONS:
            for mode in FIXTURE_MODES:
                cells.append({
                    "arm": "matrix",
                    "id": f"matrix__{defense.replace('+', '-')}__{pre_name}__{mode}",
                    "env": {
                        "W9_DEFENSE": defense,
                        "W9_OBSTRUCTED": pre_val,
                        "W9_MODE": mode,
                        "W9_L2_RULES": "3",
                    },
                    "axes": {
                        "defense_config": defense, "precondition": pre_name,
                        "fixture_mode": f"carl-ops-{mode}", "l2_rule_count": 3,
                    },
                })
    # P12 ladder — its own arm, not crossed with the rest. Held at the
    # obstructed/compromised cell so only permissiveness moves.
    for n in LADDER_RUNGS:
        cells.append({
            "arm": "p12_ladder",
            "id": f"p12__l2__rules{n}__obstructed__compromised",
            "env": {
                "W9_DEFENSE": "l2", "W9_OBSTRUCTED": "1",
                "W9_MODE": "compromised", "W9_L2_RULES": str(n),
            },
            "axes": {
                "defense_config": "l2", "precondition": "obstructed",
                "fixture_mode": "carl-ops-compromised", "l2_rule_count": n,
            },
        })
    for ordinal, cell in enumerate(cells):
        cell["ordinal"] = ordinal
        cell["seed_base"] = SEED_BASE + ordinal * SEED_STRIDE
        cell["seeds"] = [cell["seed_base"] + i for i in range(k)]
    return cells


def load_state() -> dict:
    if STATE.exists():
        return json.loads(STATE.read_text())
    return {"started_utc": datetime.now(UTC).isoformat(), "cells": {}}


def save_state(state: dict) -> None:
    tmp = STATE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2))
    tmp.replace(STATE)


def sweep_canary() -> dict:
    """The sweep gate, run ONCE for the victim. Halts the matrix if it fails."""
    from importlib import import_module

    from saster_harness.campaign import ServingConfig, build_router
    from saster_harness.canary import (
        canary_manifest_block,
        enforce_canary_gate,
        run_canary,
    )

    telemetry = import_module("halagent.telemetry")
    writer = telemetry.TelemetryWriter(OUT / f"canary_{VICTIM.split('/')[-1]}.jsonl")
    cfg = ServingConfig(campaign_id=f"canary::{VICTIM}", model=VICTIM, base_url=ROUTER_URL)
    results = {VICTIM: run_canary(build_router(cfg, writer), VICTIM, 10,
                                  campaign_id=f"canary::{VICTIM}")}
    block = canary_manifest_block(results)
    block["scope"] = "sweep gate: every victim in this matrix, measured once at start"
    (OUT / "canary_router_path.json").write_text(json.dumps(block, indent=2))
    enforce_canary_gate(results)  # raises and halts if any victim is unmeasured
    return block


def run_cell(cell: dict) -> dict:
    """One cell as a subprocess. Its own directory; its own manifest."""
    cdir = CELLS / cell["id"]
    env = dict(os.environ)
    env.update(cell["env"])
    env.update({
        "W9_ENVELOPE": "not_computed",
        "W9_OBSERVER": "binary",
        "W9_K": str(K),
        "W9_OUT": str(cdir),
        "W9_RUN_ID": f"w14-{cell['id']}",
        "W9_CAMPAIGN_ID": f"w14-{cell['id']}",
        "W9_SKIP_CANARY": "1",
        "W9_OVERWRITE": "1",
        # W16 — this cell's own disjoint seed block.
        "W9_SEED": str(cell["seed_base"]),
    })
    t0 = time.monotonic()
    proc = subprocess.run(
        [str(REPO / ".venv/bin/python"), str(REPO / "scripts/run_cell_w9.py")],
        cwd=REPO, env=env, capture_output=True, text=True, timeout=3600,
    )
    elapsed = time.monotonic() - t0
    traj = cdir / "trajectories.jsonl"
    n_records = sum(1 for _ in traj.open()) if traj.exists() else 0
    return {
        "id": cell["id"], "arm": cell["arm"], "axes": cell["axes"],
        "seed_base": cell["seed_base"], "seeds": cell["seeds"],
        "returncode": proc.returncode,
        "ok": proc.returncode == 0 and n_records == K,
        "n_records": n_records, "expected_records": K,
        "wall_s": round(elapsed, 2),
        "dir": str(cdir.relative_to(REPO)),
        "finished_utc": datetime.now(UTC).isoformat(),
        "stderr_tail": proc.stderr.strip()[-1200:] if proc.returncode != 0 else "",
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    CELLS.mkdir(parents=True, exist_ok=True)
    plan = cell_plan()
    state = load_state()

    if "canary" not in state:
        print("sweep canary gate ...", flush=True)
        state["canary"] = sweep_canary()
        print(f"  all_measured={state['canary']['all_measured']}  GATE PASS\n", flush=True)
        save_state(state)
    else:
        print(f"sweep canary already recorded (all_measured="
              f"{state['canary']['all_measured']})\n", flush=True)

    state["plan"] = {
        "n_cells": len(plan), "k": K, "victim": VICTIM,
        "envelope_status": "not_computed", "observer": "binary",
        "saster_category_axis_varied": False,
    }
    save_state(state)

    todo = [c for c in plan if not state["cells"].get(c["id"], {}).get("ok")]
    print(f"{len(plan)} cells planned, {len(plan) - len(todo)} already complete, "
          f"{len(todo)} to run (k={K})\n", flush=True)

    t_start = time.monotonic()
    for i, cell in enumerate(todo, 1):
        print(f"[{i}/{len(todo)}] {cell['id']} ...", end=" ", flush=True)
        try:
            result = run_cell(cell)
        except subprocess.TimeoutExpired:
            result = {"id": cell["id"], "arm": cell["arm"], "axes": cell["axes"],
                      "ok": False, "returncode": -1, "n_records": 0,
                      "expected_records": K, "wall_s": None,
                      "finished_utc": datetime.now(UTC).isoformat(),
                      "stderr_tail": "TIMEOUT after 3600s"}
        state["cells"][cell["id"]] = result
        save_state(state)  # checkpoint after every cell
        status = "ok" if result["ok"] else f"FAIL rc={result['returncode']}"
        print(f"{status}  {result['n_records']}/{K} records  {result['wall_s']}s", flush=True)

    state["finished_utc"] = datetime.now(UTC).isoformat()
    state["total_wall_s"] = round(time.monotonic() - t_start, 2)
    save_state(state)

    done = [c for c in state["cells"].values() if c["ok"]]
    failed = [c for c in state["cells"].values() if not c["ok"]]
    print(f"\nmatrix complete: {len(done)} ok, {len(failed)} failed, "
          f"{state['total_wall_s']}s")
    for f in failed:
        print(f"  FAILED {f['id']}: rc={f['returncode']} {f['stderr_tail'][:200]}")


if __name__ == "__main__":
    main()
