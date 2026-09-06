#!/usr/bin/env python3
"""Readback over the W24 sweep corpus (both victims): breach within k=5 by
config × arm × route, CVR per rule (P3 on R1–R3, R4 beside), per-layer
unavailable, heads, terminal outcomes, records/distinct, storage
verification. Prints tables and writes runs/w24_sweep_readback.json once."""
from __future__ import annotations

import collections
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from saster_instrument.metrics import (  # noqa: E402
    cvr_by_rule,
    distinct_trajectories,
    records_distinct_ratio,
)

OUT = Path(os.environ.get("W24_READBACK", REPO / "runs/w24_sweep_readback.json"))
ARMS = ("obstructed", "unobstructed")


def load():
    rows = []
    for sp in sorted((REPO / "runs").glob("w24_sweep_*/sweep_state.json")):
        st = json.loads(sp.read_text()); tag = sp.parent.name.replace("w24_sweep_", "")
        for cid, cell in st["cells"].items():
            traj = REPO / cell["dir"] / "trajectories.jsonl"
            if not traj.exists():
                continue
            for line in traj.open():
                if line.strip():
                    rows.append({"victim": tag, "cell": cid, "arm": cell["arm"], "axes": cell["axes"],
                                 "storage": cell.get("storage", {}), "ok": cell["ok"], "rec": json.loads(line)})
    return rows


def pct(n, d):
    return f"{100*n/d:5.1f}%" if d else "   --"


def main() -> None:
    if OUT.exists():
        raise SystemExit(f"refusing to overwrite {OUT}")
    rows = load()
    R = {"n_records": len(rows)}
    print(f"W24 sweep readback: {len(rows)} records\n")
    # breach within k by victim × config × precondition × route (campaign = cell; any-breach over k)
    print("BREACH WITHIN k=5 (any-breach per cell) and per-trial breach rate — matrix arm")
    print(f"{'victim':<9} {'config':<14} {'arm':<13} {'route':<9} {'k':>2} {'breach trials':>13} {'any':>4} {'denials':>8} {'distinct':>8}")
    table = {}
    for (v, cfg, arm, route), g in sorted(collections.defaultdict(list, {
            (r["victim"], r["axes"]["defense_config"], r["axes"]["precondition"], r["axes"]["route"]): [] for r in rows if r["arm"] == "matrix"}).items()):
        pass
    groups = collections.defaultdict(list)
    for r in rows:
        if r["arm"] == "matrix":
            groups[(r["victim"], r["axes"]["defense_config"], r["axes"]["precondition"], r["axes"]["route"])].append(r["rec"])
    for key, recs in sorted(groups.items()):
        b = sum(1 for x in recs if x["oracle"]["breach"]); den = sum(1 for x in recs for a in x["actions"] if a["policy_verdict"] == "deny")
        table[str(key)] = {"k": len(recs), "breach_trials": b, "any_breach": b > 0, "denials": den, "distinct": distinct_trajectories(recs)}
        print(f"{key[0]:<9} {key[1]:<14} {key[2]:<13} {key[3]:<9} {len(recs):>2} {b:>13} {'yes' if b else 'no':>4} {den:>8} {distinct_trajectories(recs):>8}")
    R["matrix"] = table
    # per config summary per victim
    print("\nBY CONFIG (per-trial breach rate over the matrix arm)")
    for v in sorted({r["victim"] for r in rows}):
        for cfg in ("l2", "l3", "l4", "l3+l4", "all", "none", "vendor-shaped"):
            recs = [r["rec"] for r in rows if r["victim"] == v and r["arm"] == "matrix" and r["axes"]["defense_config"] == cfg]
            if not recs: continue
            b = sum(1 for x in recs if x["oracle"]["breach"]); c = cvr_by_rule([a for x in recs for a in x["actions"]])
            print(f"  {v:<9} {cfg:<14} breach {b:>3}/{len(recs):<3} {pct(b,len(recs))}  CVR total {c['cvr_total'] if c['cvr_total'] is None else round(c['cvr_total'],3)}  R1-R3 {None if c['cvr_preregistered_r1_r3'] is None else round(c['cvr_preregistered_r1_r3'],3)}  R4 {None if c['cvr_r4_beside'] is None else round(c['cvr_r4_beside'],3)}  by rule {c['denies_by_rule']}")
    # P12 ladder
    print("\nP12 LADDER (obstructed, compromised, per victim × rung × route)")
    lad = collections.defaultdict(list)
    for r in rows:
        if r["arm"] == "p12_ladder":
            lad[(r["victim"], r["axes"]["l2_rule_count"], r["axes"]["route"])].append(r["rec"])
    for key, recs in sorted(lad.items()):
        b = sum(1 for x in recs if x["oracle"]["breach"]); c = cvr_by_rule([a for x in recs for a in x["actions"]])
        print(f"  {key[0]:<9} rules={key[1]} {key[2]:<9} breach {b}/{len(recs)}  CVR {None if c['cvr_total'] is None else round(c['cvr_total'],3)}  {c['denies_by_rule']}")
    R["ladder"] = {str(k): {"k": len(v), "breach": sum(1 for x in v if x["oracle"]["breach"])} for k, v in lad.items()}
    # outcomes, unavailable, heads, latency
    outcomes = collections.Counter((r["victim"], r["rec"]["terminal_outcome"]) for r in rows)
    print("\nTERMINAL OUTCOMES by victim:", {str(k): v for k, v in sorted(outcomes.items())})
    unav = collections.Counter(); heads = collections.Counter()
    for r in rows:
        for d in r["rec"]["detection"]:
            if d.get("status") == "unavailable" and d.get("role", "primary") == "primary": unav[(r["victim"], d["layer"])] += 1
            if d["layer"] == "l4_auditor": heads[(r["victim"], d.get("head"), d.get("role", "primary"), d.get("action_taken") or d.get("status"))] += 1
    print("UNAVAILABLE (primary):", {str(k): v for k, v in unav.items()} or "none")
    print("HEADS:"); [print("  ", k, v) for k, v in sorted(heads.items(), key=str)]
    lat = collections.Counter((r["victim"], r["rec"]["containment_latency"]["value"], r["rec"]["containment_latency"]["censored"]) for r in rows if r["rec"]["oracle"]["breach"])
    print("LATENCY on breaches (victim, value, censored):", {str(k): v for k, v in sorted(lat.items(), key=str)} or "no breaches")
    routes = collections.Counter((r["victim"], r["rec"]["widening_route_configured"] if "widening_route_configured" in r["rec"] else r["rec"]["widening_route"], r["rec"]["widening_route"]) for r in rows)
    print("ROUTES (victim, configured, realized):", {str(k): v for k, v in sorted(routes.items(), key=str)})
    per_v = {v: records_distinct_ratio([r["rec"] for r in rows if r["victim"] == v]) for v in {r["victim"] for r in rows}}
    print("RECORDS/DISTINCT per victim:", per_v)
    stor = collections.Counter((r["victim"], bool(r["storage"].get("mirror_verified"))) for r in {r["cell"] + r["victim"]: r for r in rows}.values())
    print("STORAGE mirror verified per cell:", {str(k): v for k, v in stor.items()})
    R.update({"outcomes": {str(k): v for k, v in outcomes.items()}, "unavailable": {str(k): v for k, v in unav.items()},
              "heads": {str(k): v for k, v in heads.items()}, "latency": {str(k): v for k, v in lat.items()},
              "routes": {str(k): v for k, v in routes.items()}, "records_distinct": per_v,
              "storage": {str(k): v for k, v in stor.items()}})
    OUT.write_text(json.dumps(R, indent=2, default=str))
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
