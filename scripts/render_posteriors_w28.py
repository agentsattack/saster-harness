#!/usr/bin/env python3
"""Post-GrrCON renders from the citable records: the category posterior chart
(Beta-binomial, 90% credible intervals), the attempt curve, and the alert-log
render of the counted L4 head on controls beside breaches. PNG 1920x1080 + JSON.
Read-only over the corpus."""
from __future__ import annotations

import collections
import json
import math
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
OUT = REPO / "runs/w25_stage5/deck"
FIG, DPI = (19.2, 10.8), 100
FAM = {"qwen3": "Qwen3-8B", "ministral": "Ministral-8B"}
CONFIGS = ["none", "l3", "l4", "l3+l4", "l2", "all", "vendor-shaped"]
BINARY = "AI45Research/AgentDoG-Qwen3-4B"


def beta_ci(k: int, n: int, lo: float = 0.05, hi: float = 0.95, a0: float = 1.0, b0: float = 1.0):
    """Posterior Beta(a0+k, b0+n-k) quantiles by a fine grid (no scipy)."""
    a, b = a0 + k, b0 + (n - k)
    xs = [i / 20000 for i in range(1, 20000)]
    logpdf = [(a - 1) * math.log(x) + (b - 1) * math.log(1 - x) for x in xs]
    m = max(logpdf)
    pdf = [math.exp(v - m) for v in logpdf]
    total = sum(pdf)
    cum, q = 0.0, {}
    for x, p in zip(xs, pdf, strict=True):
        cum += p / total
        for name, target in (("lo", lo), ("hi", hi), ("med", 0.5)):
            if name not in q and cum >= target:
                q[name] = x
    return q["lo"], q["med"], q["hi"], a / (a + b)


def load(roots, tag):
    out = {}
    for root in roots:
        sp = REPO / f"runs/{root}_sweep_{tag}/sweep_state.json"
        if sp.exists():
            for cid, c in json.loads(sp.read_text())["cells"].items():
                p = REPO / c["dir"] / "trajectories.jsonl"
                if p.exists():
                    out[cid] = (c, [json.loads(line) for line in p.open() if line.strip()])
    return out


def main():
    sweep = {t: load(("w24b", "w24c"), t) for t in FAM}
    # ---- 1. category posterior: per SASTER category × configuration, breach-within-k at the cell level and per trial
    cats = collections.Counter(r.get("saster_category") for t in FAM for _, recs in sweep[t].values() for r in recs)
    post = {}
    for cat in sorted(cats):
        for cfg in CONFIGS:
            for t in FAM:
                cells = [(c, recs) for c, recs in sweep[t].values() if c["arm"] == "matrix" and c["axes"]["defense_config"] == cfg and all(r.get("saster_category") == cat for r in recs)]
                kc = sum(1 for _, recs in cells if any(r["oracle"]["breach"] for r in recs))
                nc = len(cells)
                kt = sum(r["oracle"]["breach"] for _, recs in cells for r in recs)
                nt = sum(len(recs) for _, recs in cells)
                post[(cat, cfg, t)] = {"cells": {"k": kc, "n": nc, "ci90": beta_ci(kc, nc)[:3], "mean": beta_ci(kc, nc)[3]},
                                       "trials": {"k": kt, "n": nt, "ci90": beta_ci(kt, nt)[:3], "mean": beta_ci(kt, nt)[3]}}
    fig, axes = plt.subplots(1, 2, figsize=FIG, dpi=DPI, sharey=True)
    fig.subplots_adjust(left=0.06, right=0.98, top=0.86, bottom=0.12, wspace=0.08)
    for ax, level in zip(axes, ("cells", "trials"), strict=True):
        for j, t in enumerate(FAM):
            xs = [i + (-0.18 if j == 0 else 0.18) for i in range(len(CONFIGS))]
            for cat in sorted(cats):
                med = [post[(cat, cfg, t)][level]["ci90"][1] for cfg in CONFIGS]
                lo = [post[(cat, cfg, t)][level]["ci90"][0] for cfg in CONFIGS]
                hi = [post[(cat, cfg, t)][level]["ci90"][2] for cfg in CONFIGS]
                ax.errorbar(xs, med, yerr=[[m - lo_ for m, lo_ in zip(med, lo, strict=True)], [h - m for m, h in zip(med, hi, strict=True)]],
                            fmt="o", capsize=6, markersize=9, label=f"{FAM[t]} · {cat}", color="#444444" if j == 0 else "#d1495b")
                for x, cfg in zip(xs, CONFIGS, strict=True):
                    d = post[(cat, cfg, t)][level]
                    ax.text(x, d["ci90"][2] + 0.02, f"{d['k']}/{d['n']}", ha="center", fontsize=10)
        ax.set_xticks(range(len(CONFIGS)))
        ax.set_xticklabels(CONFIGS, fontsize=13)
        ax.set_ylim(0, 1.08)
        ax.set_title({"cells": "breach-within-k per cell (any of k=5 trials; n = 6 cells per config)", "trials": "per-trial breach (n = 30 trials per config)"}[level], fontsize=15)
        ax.grid(axis="y", alpha=0.3)
        ax.legend(fontsize=11, loc="upper right")
    axes[0].set_ylabel("posterior median, 90% credible interval (Beta(1,1) prior)", fontsize=13)
    fig.suptitle(f"Breach-within-k posterior per SASTER category per configuration — {len(cats)} category ran ({', '.join(sorted(cats))}); the pre-registered matrix row says 6–8", fontsize=19)
    fig.savefig(OUT / "category_posterior.png")
    plt.close(fig)
    (OUT / "category_posterior.json").write_text(json.dumps({"categories_in_corpus": dict(cats), "preregistered_row": "SASTER category | 6–8, spanning tiers | ×7 (docs/grrcon-test-matrix.md)", "prior": "Beta(1,1)", "interval": "90% equal-tailed",
                                                             "posterior": {f"{cat}|{cfg}|{t}": v for (cat, cfg, t), v in post.items()}}, indent=1))
    # ---- 2. attempt curve: breach by attempt number 1–5 per family (matrix compromised cells)
    curve = {}
    for t in FAM:
        by = collections.defaultdict(lambda: [0, 0])
        for c, recs in sweep[t].values():
            if c["arm"] == "matrix" and c["axes"]["fixture_mode"] == "carl-ops-compromised":
                for r in recs:
                    by[r["trial_index"] + 1][0] += r["oracle"]["breach"]
                    by[r["trial_index"] + 1][1] += 1
        curve[t] = {k: {"k": v[0], "n": v[1], "rate": v[0] / v[1], "ci90": beta_ci(v[0], v[1])[:3]} for k, v in sorted(by.items())}
    fig, ax = plt.subplots(figsize=FIG, dpi=DPI)
    fig.subplots_adjust(left=0.07, right=0.97, top=0.88, bottom=0.12)
    for j, t in enumerate(FAM):
        xs = sorted(curve[t])
        ys = [curve[t][x]["rate"] for x in xs]
        lo = [curve[t][x]["ci90"][0] for x in xs]
        hi = [curve[t][x]["ci90"][2] for x in xs]
        ax.plot(xs, ys, marker="o", markersize=10, linewidth=2.5, label=FAM[t], color="#444444" if j == 0 else "#d1495b")
        ax.fill_between(xs, lo, hi, alpha=0.15, color="#444444" if j == 0 else "#d1495b")
        for x, y in zip(xs, ys, strict=True):
            ax.text(x, y + 0.025, f"{curve[t][x]['k']}/{curve[t][x]['n']}", ha="center", fontsize=12)
    ax.set_xticks([1, 2, 3, 4, 5])
    ax.set_xlabel("attempt number (trial index + 1; paired seeds, seed = base + attempt − 1)", fontsize=14)
    ax.set_ylabel("breach rate, 28 per attempt per family (7 configs × 2 preconditions × 2 route hints, compromised cells), 90% CI", fontsize=13)
    ax.set_ylim(0, 1)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=13)
    ax.set_title("Breach by attempt number, 1–5, per family — attempts are independent seeds, not a learning attacker", fontsize=19)
    fig.savefig(OUT / "attempt_curve.png")
    plt.close(fig)
    (OUT / "attempt_curve.json").write_text(json.dumps(curve, indent=1))
    # ---- 3. alert log: the counted head on the 24 sanctioned controls beside breaching trajectories
    def head_verdict(rec):
        # the primary entry: the binary head, or (older control records) an entry with no head field
        ents = [d for d in rec["detection"] if d["layer"] == "l4_auditor" and d.get("head", BINARY) == BINARY and d.get("role", "primary") == "primary"]
        if not ents:
            return "allow (no entry)"
        return ents[0].get("action_taken") or ents[0].get("status")
    controls = [json.loads(line) for line in (REPO / "corpora/citable/safe_controls_w22b_qwen/trajectories.jsonl").open() if line.strip()]
    ctrl_rows = [(f"control #{r['trial_index']}", head_verdict(r), r["terminal_outcome"]) for r in controls]
    br_rows = []
    for t in FAM:
        for cid, (c, recs) in sweep[t].items():
            if c["arm"] == "matrix" and c["axes"]["defense_config"] in ("l4", "l3+l4", "all"):
                for r in recs:
                    if r["oracle"]["breach"]:
                        br_rows.append((f"{t}:{cid.replace('matrix__', '')}#{r['trial_index']}", head_verdict(r), r["terminal_outcome"]))
    color = {"warn": "#d1495b", "block": "#8b0000", "allow (no entry)": "#3a7d44", "unavailable": "#999999", "error": "#000000"}
    fig, axes = plt.subplots(1, 2, figsize=FIG, dpi=DPI, gridspec_kw={"width_ratios": [1, 2.2]})
    fig.subplots_adjust(left=0.04, right=0.99, top=0.86, bottom=0.05, wspace=0.05)
    for ax, rows, title in ((axes[0], ctrl_rows, f"24 sanctioned controls (safe_controls_w22b_qwen): head fired on {sum(1 for _, v, _ in ctrl_rows if v == 'warn')}/24"),
                            (axes[1], br_rows, f"breaching trajectories under L4 configs (sweep): head fired on {sum(1 for _, v, _ in br_rows if v == 'warn')}/{len(br_rows)}")):
        n = len(rows)
        cols = 1 if n <= 30 else 3
        per = math.ceil(n / cols)
        for i, (name, v, _) in enumerate(rows):
            col, row = divmod(i, per)
            ax.add_patch(plt.Rectangle((col * 1.0, per - 1 - row), 0.96, 0.9, color=color.get(v, "#666666")))
            ax.text(col * 1.0 + 0.03, per - 1 - row + 0.45, name[:48], va="center", fontsize=7 if cols > 1 else 10, color="white")
        ax.set_xlim(0, cols)
        ax.set_ylim(0, per)
        ax.axis("off")
        ax.set_title(title, fontsize=14)
    handles = [plt.Rectangle((0, 0), 1, 1, color=c) for c in ("#d1495b", "#3a7d44", "#999999")]
    fig.legend(handles, ["warn (fired)", "allow (no entry)", "unavailable"], loc="lower center", ncol=3, fontsize=12)
    fig.suptitle("Alert log — the counted L4 head (AgentDoG 1.0 binary) on the sanctioned controls beside its firing on breaches: the same alert either way", fontsize=18)
    fig.savefig(OUT / "alert_log.png")
    plt.close(fig)
    (OUT / "alert_log.json").write_text(json.dumps({"head": BINARY, "controls": ctrl_rows, "breaches": br_rows}, indent=1))
    print("categories:", dict(cats), "| controls fired:", sum(1 for _, v, _ in ctrl_rows if v == "warn"), "/24 | breaches fired:", sum(1 for _, v, _ in br_rows if v == "warn"), "/", len(br_rows))
    print("attempt curve:", {t: [round(curve[t][x]["rate"], 2) for x in sorted(curve[t])] for t in FAM})


if __name__ == "__main__":
    main()
