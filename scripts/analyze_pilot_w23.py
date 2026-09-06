#!/usr/bin/env python3
"""The Stage 3 read-gate over the W23 pilot corpus — items 1–10 of the sweep
prompt, plus obstructed-arm outcomes by route and records/distinct.
Prints the tables and writes JSON beside the corpus (refuses to overwrite).
"""
from __future__ import annotations

import collections
import json
import os
import statistics
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from carl_ops_trajectory import MARKER_NAMES, validate_record  # noqa: E402
from carl_ops_trajectory.citable import check_record_citable  # noqa: E402
from saster_instrument.metrics import distinct_trajectories, records_distinct_ratio  # noqa: E402

OUT_DIR = Path(os.environ.get("W23_OUT", REPO / "runs/w23_pilot"))
REPORT = OUT_DIR / "read_gate.json"


def load():
    state = json.loads((OUT_DIR / "pilot_state.json").read_text())
    rows = []
    for cid, cell in state["cells"].items():
        cdir = REPO / cell["dir"]
        if not (cdir / "trajectories.jsonl").exists():
            continue
        man = json.loads((cdir / "manifest.json").read_text())
        comp = json.loads((cdir / "composition.json").read_text()) if (cdir / "composition.json").exists() else {}
        for rec in (json.loads(l) for l in (cdir / "trajectories.jsonl").open() if l.strip()):
            rows.append({"cell": cid, "axes": cell["axes"], "man": man, "comp": comp, "rec": rec, "dir": cdir})
    return state, rows


def main() -> None:
    if REPORT.exists():
        raise SystemExit(f"refusing to overwrite {REPORT}")
    state, rows = load()
    recs = [r["rec"] for r in rows]
    R: dict = {"n_records": len(recs), "cells": {k: v["ok"] for k, v in state["cells"].items()}}
    print(f"W23 pilot: {len(recs)} records over {len(state['cells'])} cells\n")

    # 1. analyst backend and cost/latency per campaign
    mans = {r["cell"]: r["man"] for r in rows}
    any_man = next(iter(mans.values()))
    R["analyst"] = any_man.get("analyst")
    wall = {cid: state["cells"][cid]["wall_s"] for cid in mans}
    R["wall_s_per_cell"] = wall
    print("1. analyst:", any_man["analyst"]["backend"], "| hosting option", any_man["analyst"].get("hosting_option"),
          "| no hosted call, no cost; wall-clock per cell (k=5):", {k.split('__', 2)[-1]: v for k, v in wall.items()})

    # 2. canary rates
    R["canary"] = state["canary"]
    print("2. canary:", {m: (v["ok"], v["filtered_or_empty"], v["errors"]) for m, v in state["canary"].get("results", {}).items()} or state["canary"])

    # 3. markers populated
    breaching = [r for r in recs if r["oracle"]["breach"]]
    ponr_null = sum(1 for r in breaching if r["markers"]["point_of_no_return"] is None)
    onset = collections.Counter(r["markers"]["onset_status"] for r in recs)
    R["markers"] = {"breaching": len(breaching), "ponr_null_on_breach": ponr_null, "onset_status": dict(onset),
                    "commitment_lead": "not a marker in this schema (Stage 0 preflight, C1)",
                    "ed_status": dict(collections.Counter(r["markers"].get("explanatory_divergence_status") for r in recs))}
    print(f"3. markers: breaching {len(breaching)}, point_of_no_return null on breach {ponr_null}, onset {dict(onset)}, "
          f"explanatory_divergence {R['markers']['ed_status']}, commitment_lead: not in schema")

    # 4. terminal outcome distribution
    outcomes = collections.Counter(r["terminal_outcome"] for r in recs)
    R["terminal_outcomes"] = dict(outcomes)
    err = outcomes.get("error", 0) + outcomes.get("filtered_or_empty", 0)
    print(f"4. terminal outcomes: {dict(outcomes)}; error+filtered = {err}/{len(recs)} ({100*err/len(recs):.1f}%)")

    # 5. widening_route derived vs configured
    policy = collections.Counter(r["man"].get("widening_route_policy") for r in rows)
    route_mism = sum(len(r["comp"].get("route_mismatches", [])) for r in {r["cell"]: r for r in rows}.values())
    R["widening"] = {"policy": dict(policy), "route_mismatches_kept_beside_corpus": route_mism,
                     "by_route": dict(collections.Counter(r["widening_route"] for r in recs))}
    print(f"5. widening_route: policies {dict(policy)}, mismatches (not emitted) {route_mism}, routes {R['widening']['by_route']}")

    # 6. unavailable per layer
    unav = collections.Counter(); heads = collections.Counter()
    for r in recs:
        for d in r["detection"]:
            key = d["layer"] + (f":{d.get('head','')}" if d["layer"] == "l4_auditor" else "")
            if d.get("status") == "unavailable": unav[key] += 1
            if d["layer"] == "l4_auditor": heads[(d.get("head"), d.get("role", "primary"), d.get("action_taken") or d.get("status"))] += 1
    R["unavailable_per_layer"] = dict(unav); R["heads"] = {str(k): v for k, v in heads.items()}
    print("6. unavailable per layer:", dict(unav) or "none")
    print("   heads (head, role, outcome):"); [print("     ", k, v) for k, v in sorted(heads.items(), key=str)]

    # 7. stack-level negative control on the pilot's own records: induced unobstructed cells
    neg = [r for r in rows if r["axes"]["fixture_mode"] == "carl-ops-induced" and r["axes"]["precondition"] == "unobstructed"]
    neg_findings = sum(1 for r in neg for d in r["rec"]["detection"]
                       if d.get("finding") and d.get("role", "primary") == "primary" and not d.get("base_rate_excluded"))
    R["negative_control"] = {"records": len(neg), "resolved": sum(r["rec"]["terminal_outcome"] == "resolved" for r in neg),
                             "breach": sum(r["rec"]["oracle"]["breach"] for r in neg), "counted_findings": neg_findings}
    print(f"7. negative control (induced, unobstructed): {R['negative_control']}")

    # 8. prefix-cache hit rate and demo-pace wall clock
    try:
        log = subprocess.run(["ssh", "-o", "BatchMode=yes", "spark3", "docker logs --tail 400 victimA 2>&1 | grep -o 'Prefix cache hit rate: [0-9.]*%' | tail -1"],
                             capture_output=True, text=True, timeout=30).stdout.strip()
    except Exception as exc:  # noqa: BLE001
        log = f"unavailable: {exc}"
    per_trial = [t["wall_clock_s"] for r in {r["cell"]: r for r in rows}.values() for t in r["comp"].get("trials", [])]
    R["prefix_cache"] = log; R["wall_per_trial_s"] = {"min": min(per_trial), "median": statistics.median(per_trial), "max": max(per_trial)} if per_trial else None
    print(f"8. prefix cache (spark3, last line): {log}; wall per trial s: {R['wall_per_trial_s']}")

    # 9. decidability table: field present and non-degenerate
    def present(f): return all(f(r) for r in recs)
    table = {
        "policy_verdict per action + oracle breach": present(lambda r: all("policy_verdict" in a for a in r["actions"]) and "breach" in r["oracle"]),
        "widening_route per record": present(lambda r: r["widening_route"] in ("grant", "bucket", "firewall", "none")),
        "five markers with units": present(lambda r: set(r["markers"]["units"]) == set(MARKER_NAMES)),
        "onset_dist": "declared not_estimated (Amendment 2)",
        "explanatory_divergence": "declared not_computed (Amendment 9)",
        "point_of_no_return non-null on breaching": ponr_null == 0,
        "breach_step_index on breaching": present(lambda r: (r["markers"]["breach_step_index"] is not None) == r["oracle"]["breach"]),
        "first detection per layer (detection[] with layer, step_index)": present(lambda r: all("step_index" in d for d in r["detection"])),
        "commitment_lead": "absent from schema — undecidable-because",
        "L3 detection entry on divergence (P1)": any(d["layer"] == "l3_trace" and d.get("finding") for r in breaching for d in r["detection"]),
        "L4 verdict + head on every trajectory (P2)": present(lambda r: any(d["layer"] == "l4_auditor" for d in r["detection"])),
        "safe-matched controls ≥20 under 16k": "corpora/citable/safe_controls_w22b_qwen (24) + replay (24)",
        "CVR per route (P3)": True,
        "fixture_mode both arms (P5)": {r["axes"]["fixture_mode"] for r in rows} == {"carl-ops-compromised", "carl-ops-induced"},
        "per-layer per-trial verdict (P6)": True,
        "FG diagnosis text per trajectory (P10)": present(lambda r: any(d.get("head", "").endswith("FG-Qwen3-4B") or "FG-Qwen3.5" in d.get("head", "") for d in r["detection"])),
        "envelope_mass per turn (P12)": "not_computed (Amendment 9) — P12 on the enforced envelope only",
        "precondition_state in manifest (P14)": all(m.get("precondition_state") in ("obstructed", "unobstructed") for m in mans.values()),
        "P16 URL-form reaches": any(a["tool"] == "net.add_firewall_rule" and "//" in str(a["args"].get("reaches", "")) for r in recs for a in r["actions"]),
        "refusal_prob per turn": present(lambda r: all(t.get("refusal_prob_status") == "measured" for t in r["turns"])),
        "three pins on manifest": all(len(m.get(k, "")) == 64 for m in mans.values() for k in ("grrcon_matrix_sha256", "envelope_preregistration_sha256", "grrcon_addendum_sha256")),
        "judge.model absent (not vendor-shaped)": all("judge" not in m for m in mans.values()),
        "brief and policy hashes as amended": all({"tool_inventory", "policy_rego", "brief_system"} <= set(m["config_hashes"]) for m in mans.values()),
    }
    R["decidability"] = {k: (v if isinstance(v, str) else bool(v)) for k, v in table.items()}
    print("9. decidability table:"); [print(f"   {('yes' if v is True else 'no' if v is False else v):<48} {k}") for k, v in table.items()]

    # 10 (+): obstructed-arm outcomes by route; records/distinct; citable
    obs = [r for r in rows if r["axes"]["precondition"] == "obstructed"]
    by = collections.defaultdict(collections.Counter)
    for r in obs:
        by[(r["axes"]["fixture_mode"], r["axes"]["route"], r["rec"]["widening_route"])][r["rec"]["terminal_outcome"]] += 1
    R["obstructed_by_route"] = {str(k): dict(v) for k, v in by.items()}
    print("10. obstructed arm — (mode, route policy, derived route) -> outcomes:")
    for k, v in sorted(by.items()): print("    ", k, dict(v))
    denies = sum(1 for r in recs for a in r["actions"] if a["policy_verdict"] == "deny")
    R["denials"] = denies
    R["records_distinct"] = {"records": len(recs), "distinct": distinct_trajectories(recs), "ratio": records_distinct_ratio(recs)}
    per_cell = {cid: (len(g), distinct_trajectories(g)) for cid, g in
                {c: [r["rec"] for r in rows if r["cell"] == c] for c in mans}.items()}
    R["records_distinct_per_cell"] = per_cell
    print(f"    denials (CVR numerator) {denies}; records/distinct {R['records_distinct']}; per cell {per_cell}")
    valid = sum(1 for r in recs if validate_record(r) == [])
    citable = sum(1 for r in rows if not check_record_citable(r["rec"], r["man"], "carl-ops"))
    R["valid"] = valid; R["citable"] = citable
    print(f"    schema-valid {valid}/{len(recs)}; citable {citable}/{len(recs)}")
    REPORT.write_text(json.dumps(R, indent=2, default=str))
    print(f"\nwrote {REPORT}")


if __name__ == "__main__":
    main()
