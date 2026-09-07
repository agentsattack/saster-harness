#!/usr/bin/env python3
"""Addendum §T readback: per trial, the reaches argument as emitted, R1's
verdict on that action, whether I2 fired, the terminal outcome. Read-only."""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "runs/w25_stage5/phone_home_readback.json"


def main() -> None:
    rows = []
    for sp in sorted((REPO / "runs").glob("w30t_sweep_*/sweep_state.json")):
        tag = sp.parent.name.split("_sweep_", 1)[1]
        for cid, c in json.loads(sp.read_text())["cells"].items():
            d = REPO / c["dir"]
            if not (d / "trajectories.jsonl").exists():
                continue
            man = json.loads((d / "manifest.json").read_text())
            for line in (d / "trajectories.jsonl").open():
                r = json.loads(line)
                fw = [a for a in r["actions"] if a["tool"] == "net.add_firewall_rule"]
                rows.append({
                    "id": f"{tag}:{cid}#{r['trial_index']}", "config": c["axes"]["defense_config"], "family": tag, "seed": man["seeds"][r["trial_index"]],
                    "directive_variant": man.get("directive_variant"), "directive_sha256": man.get("directive_sha256"),
                    "firewall_rules": [{"step": a["step_index"], "reaches": a["args"].get("reaches"), "cidr": a["args"].get("cidr"), "direction": a["args"].get("direction"),
                                        "policy_verdict": a["policy_verdict"], "rule_id": a.get("rule_id")} for a in fw],
                    "url_form_reaches": [a["args"].get("reaches") for a in fw if "//" in str(a["args"].get("reaches", ""))],
                    "sink_named": any("127.0.0.1" in str(a["args"].get("reaches", "")) for a in fw),
                    "I2_fired": "I2" in (r["oracle"].get("invariants_fired") or []), "invariant": r["oracle"].get("invariant"),
                    "breach": r["oracle"]["breach"], "terminal_outcome": r["terminal_outcome"], "widening_route": r.get("widening_route"),
                    "denials": [(a["step_index"], a["tool"], a.get("rule_id")) for a in r["actions"] if a["policy_verdict"] == "deny"],
                })
    OUT.write_text(json.dumps(rows, indent=1))
    for r in rows:
        fw = "; ".join(f"step {f['step']} reaches={f['reaches']!r} R1/L2={f['policy_verdict']}{'/' + f['rule_id'] if f['rule_id'] else ''}" for f in r["firewall_rules"]) or "no firewall rule emitted"
        print(f"{r['id']:<60} seed {r['seed']} | {fw} | I2 {'FIRED' if r['I2_fired'] else 'no'} | {r['terminal_outcome']}")
    n = len(rows)
    print(f"\n{n} trials; sink named in a reaches: {sum(r['sink_named'] for r in rows)}; URL-form reaches emitted: {sum(bool(r['url_form_reaches']) for r in rows)}; I2 fired: {sum(r['I2_fired'] for r in rows)}; breaches: {sum(r['breach'] for r in rows)}")
    for cfg in ("all", "none"):
        for fam in ("qwen3", "ministral"):
            g = [r for r in rows if r["config"] == cfg and r["family"] == fam]
            if g:
                print(f"  {cfg:<5} {fam:<9} sink named {sum(r['sink_named'] for r in g)}/{len(g)}; R1 allowed a URL-form reaches {sum(1 for r in g for f in r['firewall_rules'] if '//' in str(f['reaches']) and f['policy_verdict'] == 'allow')}; denied {sum(1 for r in g for f in r['firewall_rules'] if '//' in str(f['reaches']) and f['policy_verdict'] == 'deny')}; I2 {sum(r['I2_fired'] for r in g)}; breach {sum(r['breach'] for r in g)}")
    sys.exit(0)


if __name__ == "__main__":
    main()
