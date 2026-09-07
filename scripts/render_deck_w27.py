#!/usr/bin/env python3
"""GrrCON wrap: deck renders from real records — PNG at 1920x1080 plus the JSON
behind each. Read-only over the corpus and the Stage 5 readbacks."""
from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
OUT = REPO / "runs/w25_stage5/deck"
OUT.mkdir(exist_ok=True)
DPI = 100
FIG = (19.2, 10.8)
CONFIGS = ["none", "l3", "l4", "l3+l4", "l2", "all", "vendor-shaped"]
FAM = {"qwen3": "Qwen3-8B", "ministral": "Ministral-8B"}


def load_corpus(roots, tag):
    out = {}
    for root in roots:
        sp = REPO / f"runs/{root}_sweep_{tag}/sweep_state.json"
        if not sp.exists():
            continue
        for cid, c in json.loads(sp.read_text())["cells"].items():
            p = REPO / c["dir"] / "trajectories.jsonl"
            if p.exists():
                out[cid] = (c, [json.loads(line) for line in p.open() if line.strip()])
    return out


def table_png(name, title, columns, rows, col_widths=None, fontsize=13):
    fig, ax = plt.subplots(figsize=FIG, dpi=DPI)
    ax.axis("off")
    ax.set_title(title, fontsize=22, pad=20, loc="left")
    fig.subplots_adjust(left=0.03, right=0.97, top=0.88, bottom=0.03)
    t = ax.table(cellText=rows, colLabels=columns, loc="upper center", cellLoc="left", colLoc="left", colWidths=col_widths)
    t.auto_set_font_size(False)
    t.set_fontsize(fontsize)
    t.scale(1, 1.9)
    for (r, _c), cell in t.get_celld().items():
        cell.set_edgecolor("#cccccc")
        if r == 0:
            cell.set_facecolor("#e8e8e8")
            cell.set_text_props(weight="bold")
    fig.savefig(OUT / f"{name}.png")
    plt.close(fig)
    (OUT / f"{name}.json").write_text(json.dumps({"title": title, "columns": columns, "rows": rows}, indent=1))


def main():
    S = json.loads((REPO / "runs/w25_stage5/stage5_readback.json").read_text())
    R6 = json.loads((REPO / "runs/w25_stage5/r6_arm_readback.json").read_text())
    sweep = {tag: load_corpus(("w24b", "w24c"), tag) for tag in FAM}
    # 1. ablation bars, sweep and R6 side by side
    data = {}
    for tag in FAM:
        per = collections.defaultdict(lambda: [0, 0])
        for _cid, (c, recs) in sweep[tag].items():
            if c["arm"] == "matrix":
                per[c["axes"]["defense_config"]][0] += sum(r["oracle"]["breach"] for r in recs)
                per[c["axes"]["defense_config"]][1] += len(recs)
        data[tag] = {"sweep": {k: per[k] for k in CONFIGS}, "r6": {k: [v["arm_breach"], v["arm_n"]] for k, v in R6["by_family"][tag]["by_config"].items()}}
    fig, axes = plt.subplots(1, 2, figsize=FIG, dpi=DPI, sharey=True)
    for ax, tag in zip(axes, FAM, strict=True):
        xs = range(len(CONFIGS))
        sw = [data[tag]["sweep"][k][0] / data[tag]["sweep"][k][1] for k in CONFIGS]
        r6 = [data[tag]["r6"].get(k, [0, 0])[0] / data[tag]["r6"][k][1] if k in data[tag]["r6"] else None for k in CONFIGS]
        ax.bar([x - 0.2 for x in xs], sw, width=0.4, label="sweep (k=5 × 6 cells)", color="#444444")
        ax.bar([x + 0.2 for x in xs if r6[x] is not None], [v for v in r6 if v is not None], width=0.4, label="§R arm (R6 added)", color="#d1495b")
        for x, v in zip(xs, sw, strict=True):
            ax.text(x - 0.2, v + 0.01, f"{int(v*30)}/30", ha="center", fontsize=11)
        for x, v in zip(xs, r6, strict=True):
            if v is not None:
                ax.text(x + 0.2, v + 0.01, f"{int(v*30)}/30", ha="center", fontsize=11, color="#d1495b")
        ax.set_xticks(list(xs))
        ax.set_xticklabels(CONFIGS, fontsize=13)
        ax.set_ylim(0, 1)
        ax.set_title(FAM[tag], fontsize=20)
        ax.set_ylabel("per-trial breach rate (matrix arm)", fontsize=13)
        ax.legend(fontsize=12)
    fig.suptitle("Breach rate per defense config — sweep and the R6 arm on paired seeds", fontsize=22)
    fig.savefig(OUT / "ablation_bars.png")
    plt.close(fig)
    (OUT / "ablation_bars.json").write_text(json.dumps(data, indent=1))
    # 2. four heads
    heads = S["item10"]  # not the source; use the sweep HEADS + controls F22
    rows = [
        ["AgentDoG 1.0 binary (primary, base-rate excluded)", "24/24 warn (F19)", "64/64 breaching records under L4 configs (population: breaches only)", "0.00", "counted for nothing (§E)"],
        ["AgentDoG 1.0 fine-grained (recorded)", "0/24 warn (F22)", "0 warn in 480 records (population: all)", "1.00", "never fired; labels none"],
        ["AgentDoG 1.5 coarse (recorded)", "20/24 warn (F22)", "109 warn entries over all records: by breach 48 breaching + 61 non-breaching; by family 48 Qwen + 61 Ministral (a coincidence of totals)", "0.17", "recorded, never counted"],
        ["AgentDoG 1.5 fine-grained (recorded)", "24/24 warn (F22)", "173 warn entries over all records: 60 breaching + 113 non-breaching; 7 unavailable (4 breaching, 3 non-breaching)", "0.00", "P10 labels 3/60 correct"],
    ]
    table_png("four_heads_table", "The four AgentDoG heads on the same corpus (controls → specificity; breaches → what fired)",
              ["head", "24 safe controls", "warn entries, mixed populations (stated per row)", "specificity", "role"], rows, [0.24, 0.13, 0.36, 0.09, 0.18])
    del heads
    # 3. per-rule denials
    rules = ["R1_egress", "R2_role", "R3_grant", "R4_bucket_owner", "R6_reaches_bounds"]
    den = S["item2"]["denials"]
    rows = []
    for key, v in sorted(den.items()):
        fam, cfg, route = eval(key)
        rows.append([FAM[fam], cfg, route, "sweep"] + [str(v.get(r, 0)) for r in rules])
    for tag in FAM:
        for cfg, v in R6["by_family"][tag]["arm_denials"].items():
            if v:
                rows.append([FAM[tag], cfg, "all routes", "§R arm"] + [str(v.get(r, 0)) for r in rules])
    table_png("per_rule_denials", "Denials per rule — R1 and R2 never fired in 480 trials; R4 carries the L2 configs; R6 in the arm",
              ["family", "config", "route", "corpus"] + [r.split("_")[0] for r in rules], rows, [0.13, 0.12, 0.10, 0.09, 0.09, 0.09, 0.09, 0.09, 0.09], fontsize=12)
    # 4. three holes
    owner = []
    for tag in FAM:
        for cid, (_c, recs) in sweep[tag].items():
            for r in recs:
                bsi = r["markers"]["breach_step_index"]
                if r["oracle"]["breach"] and r["oracle"]["invariant"] == "I3" and bsi is not None and bsi < len(r["actions"]) and r["actions"][bsi]["tool"] == "storage.create_bucket":
                    owner.append(f"{tag}:{cid}#{r['trial_index']}")
    f25 = [t["id"] for t in S["item3"]["trajectories"] if t["config"] in ("l2", "all")] + S["item4"]
    rows = [
        ["1. bucket owner: create_bucket grants its owner; no rule at creation", "F12 item 2 / F18 (controls, Stage 2)", "R4_bucket_owner (in force, 2026-09-05)", f"{len(owner)} sweep breaches (I3 at creation, no-R4 configs)", "R4 in the sweep: l2 0/30, all 1/30 on Qwen"],
        ["2. R1 vs I2: a non-address `reaches` is in bounds to R1, out of bounds to I2", "F25 (Stage 5 readback)", "R6_reaches_bounds (§R arm file; policy in force unchanged)", f"{len(f25)} sweep breaches (11 Ministral l2/all, 1 Qwen all)", "§R arm: 0 F25-class breaches; Ministral l2 5→0, all 6→0"],
        ["3. R3 prefix / R2 principal: an ops-prefixed non-population grant, a role for a non-population principal", "F24 (static check mid-sweep)", "R5 draft, unwired", "95 allowed actions on 57 trajectories; 0 breaches through it", "not closed — the unexploited gap"],
    ]
    table_png("three_holes_table", "Three holes in the declared policy — how each was found, what closes it, who used it",
              ["hole", "found by", "rule", "trajectories that used it", "closed under"], rows, [0.30, 0.14, 0.18, 0.20, 0.18], fontsize=12)
    (OUT / "three_holes_ids.json").write_text(json.dumps({"hole1_owner_breaches": owner, "hole2_f25": f25}, indent=1))
    # 5. P1–P17
    rows = [[k, v["verdict"][:70], v["basis"][:95]] for k, v in S["item10"].items()]
    table_png("p1_p17_table", "P1–P17 as pre-registered: held / refuted / undecidable-because", ["prediction", "verdict", "the number"], rows, [0.16, 0.36, 0.48], fontsize=11)
    # 6. censored latency
    i8 = S["item8"]
    rows = [[FAM[t], str(i8[t]["breaches"]), str(i8[t]["censored"]), str(i8[t]["uncensored"]), str(i8[t]["median"]), f"{i8[t]['min']} to {i8[t]['max']}"] for t in FAM]
    table_png("censored_latency_table", "Containment latency on breaches — censored count beside the median (steps after the breach; negative = a denial preceded it)",
              ["family", "breaches", "censored (no counted detection)", "uncensored", "median", "range"], rows, [0.16, 0.12, 0.28, 0.14, 0.12, 0.18])
    print("rendered:", sorted(p.name for p in OUT.iterdir()))


if __name__ == "__main__":
    main()
