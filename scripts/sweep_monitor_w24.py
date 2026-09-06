#!/usr/bin/env python3
"""Hourly monitor for the W24 sweep (Stage 4): terminal-outcome distribution,
unavailable per COUNTED layer, stalls/repeats, free space on spark1 and the
mirror. Halts the sweep — writes runs/w24_HALT — on error (error +
filtered_or_empty) > 5% or any counted layer unavailable > 20%. Never
retries, never overwrites. Exits when every watched sweep has finished."""
from __future__ import annotations

import collections
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
STATES = [Path(p) for p in sys.argv[1:]] or sorted((REPO / "runs").glob("w24_sweep_*/sweep_state.json"))
INTERVAL = int(os.environ.get("W24_MONITOR_INTERVAL", "3600"))
LOG = REPO / "runs" / "w24_sweep_monitor.log"
HALT = REPO / "runs" / "w24_HALT"
MIRROR_HOST = os.environ.get("W24_MIRROR_HOST", "spark8")
COUNTED = {"l2_policy": ("l2", "all", "all5"), "l3_trace": ("l3", "l3+l4", "all", "all5"),
           "l4_auditor": ("l4", "l3+l4", "all", "all5"), "scope_lock": ("vendor-shaped",), "judge": ("vendor-shaped",)}


def tick() -> dict:
    outcomes = collections.Counter(); unav = collections.Counter(); enabled = collections.Counter()
    stalls = repeats = n = 0; finished = 0
    for st_path in STATES:
        if not st_path.exists():
            continue
        st = json.loads(st_path.read_text())
        finished += "finished_utc" in st or "halted" in st
        for cid, cell in st["cells"].items():
            cfg = cell["axes"]["defense_config"]
            traj = REPO / cell["dir"] / "trajectories.jsonl"
            if not traj.exists():
                continue
            for line in traj.open():
                if not line.strip():
                    continue
                r = json.loads(line); n += 1
                outcomes[r["terminal_outcome"]] += 1
                stalls += r["budget"]["stalls"]; repeats += r["budget"]["repeats"]
                for layer, cfgs in COUNTED.items():
                    if cfg in cfgs:
                        enabled[layer] += 1
                        if any(d["layer"] == layer and d.get("status") == "unavailable" and d.get("role", "primary") == "primary"
                               for d in r["detection"]):
                            unav[layer] += 1
    err_rate = (outcomes["error"] + outcomes["filtered_or_empty"]) / n if n else 0.0
    unav_rate = {k: (unav[k] / enabled[k]) for k in enabled if enabled[k]}
    def df(cmd):
        try: return subprocess.run(cmd, capture_output=True, text=True, timeout=20, shell=True).stdout.strip().splitlines()[-1]
        except Exception as exc: return f"unavailable: {exc}"  # noqa: BLE001
    rep = {"utc": datetime.now(UTC).isoformat(), "records": n, "outcomes": dict(outcomes), "error_rate": err_rate,
           "unavailable_rate_counted": unav_rate, "stalls": stalls, "repeats": repeats,
           "free_spark1": df("df -h ~ | tail -1"), "free_mirror": df(f"ssh -o BatchMode=yes {MIRROR_HOST} 'df -h ~ | tail -1'"),
           "sweeps_finished": finished, "sweeps_watched": len(STATES)}
    reasons = []
    if n and err_rate > 0.05:
        reasons.append(f"error rate {err_rate:.1%} > 5%")
    for k, v in unav_rate.items():
        if v > 0.20:
            reasons.append(f"counted layer {k} unavailable {v:.1%} > 20%")
    if reasons and not HALT.exists():
        HALT.write_text(f"{rep['utc']} " + "; ".join(reasons) + "\n")
        rep["halt"] = reasons
    return rep


def main() -> None:
    while True:
        rep = tick()
        with LOG.open("a") as fh:
            fh.write(json.dumps(rep) + "\n")
        print(json.dumps(rep), flush=True)
        if rep.get("halt") or rep["sweeps_finished"] >= rep["sweeps_watched"] > 0:
            return
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
