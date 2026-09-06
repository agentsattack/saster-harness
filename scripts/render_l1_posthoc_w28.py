#!/usr/bin/env python3
"""Post hoc L1 render: firing per group per family for every classifier that
was scored (Granite Guardian, Llama Guard 3 8B), one PNG at 1920x1080 + JSON."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
ROOT = REPO / "runs/w28_l1_posthoc"
OUT = REPO / "runs/w25_stage5/deck"
GROUPS = [("controls/qwen3/controls", "24 controls (Qwen)"), ("sweep/qwen3/breaching", "Qwen breaching"), ("sweep/qwen3/sanctioned_non_breaching", "Qwen non-breaching"),
          ("sweep/ministral/breaching", "Ministral breaching"), ("sweep/ministral/sanctioned_non_breaching", "Ministral non-breaching")]
COLORS = {"granite-guardian": "#2a6f97", "llamaguard": "#d1495b"}


def main() -> None:
    runs = {p.parent.name: json.loads(p.read_text()) for p in sorted(ROOT.glob("*/summary.json"))}
    fig, ax = plt.subplots(figsize=(19.2, 10.8), dpi=100)
    fig.subplots_adjust(left=0.07, right=0.97, top=0.86, bottom=0.14)
    n = len(runs)
    width = 0.8 / max(n, 1)
    for j, (tag, s) in enumerate(runs.items()):
        xs = [i + (j - (n - 1) / 2) * width for i in range(len(GROUPS))]
        vals = [s["groups"].get(k, {"rate": 0, "fired": 0, "n": 0}) for k, _ in GROUPS]
        ax.bar(xs, [v["rate"] for v in vals], width=width * 0.95, color=COLORS.get(tag, "#666666"), label=f"{s['model']} · risk/categories: {s.get('risk')}")
        for x, v in zip(xs, vals, strict=True):
            ax.text(x, v["rate"] + 0.01, f"{v['fired']}/{v['n']}", ha="center", fontsize=11)
    ax.set_xticks(range(len(GROUPS)))
    ax.set_xticklabels([g for _, g in GROUPS], fontsize=13)
    ax.set_ylim(0, max(0.3, max(v["rate"] for s in runs.values() for v in s["groups"].values()) + 0.08))
    ax.set_ylabel("trajectories with at least one turn text denied", fontsize=13)
    ax.grid(axis="y", alpha=0.3)
    ax.legend(fontsize=12)
    ax.set_title("Input classifiers post hoc on every turn text of the 810 citable records and the 24 controls — the compositional path carries nothing overt", fontsize=18)
    fig.savefig(OUT / "l1_posthoc.png")
    plt.close(fig)
    (OUT / "l1_posthoc.json").write_text(json.dumps({tag: {"model": s["model"], "revision": s.get("revision"), "groups": s["groups"], "verdicts": s["verdicts_over_distinct_texts"],
                                                            "breaching_cells_with_a_firing": s["breaching_cells_with_a_firing"]} for tag, s in runs.items()}, indent=1))
    for tag, s in runs.items():
        print(tag, {k: f"{v['fired']}/{v['n']}" for k, v in s["groups"].items() if "w2" not in k})


if __name__ == "__main__":
    main()
