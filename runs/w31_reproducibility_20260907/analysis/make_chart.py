#!/usr/bin/env python3
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path


HERE = Path(__file__).resolve().parent
RESULTS = json.loads((HERE / "results.json").read_text())
W, H = 1600, 900
BG, PANEL, GRID = "#081109", "#102015", "#29432f"
WHITE, MUTED, GREEN, AMBER, RED = "#f3f7f3", "#a6b5a8", "#6ee787", "#e8a23a", "#ff7b72"


def text(x, y, value, size=30, color=WHITE, weight=400, anchor="start"):
    escaped = str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return (
        f'<text x="{x}" y="{y}" fill="{color}" font-family="Arial, sans-serif" '
        f'font-size="{size}" font-weight="{weight}" text-anchor="{anchor}">{escaped}</text>'
    )


def rect(x, y, width, height, fill, radius=10, stroke="none"):
    return f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="{radius}" fill="{fill}" stroke="{stroke}"/>'


pairs_by_model = defaultdict(list)
for pair in RESULTS["pairs"]:
    pairs_by_model[pair["family"]].append(pair)

agreement = {}
for family, pairs in pairs_by_model.items():
    agreement[family] = {
        "breach": sum(pair["breach_agreement"] for pair in pairs),
        "action": sum(pair["action_sequence_agreement"] for pair in pairs),
        "output": sum(pair["victim_output_agreement"] for pair in pairs),
        "n": len(pairs),
    }

outcome = defaultdict(lambda: [0, 0])
for row in RESULTS["outcomes"]:
    if row["family"] != "ministral":
        continue
    key = (row["condition"], row["config"])
    outcome[key][0] += row["breaches"]
    outcome[key][1] += row["attempted"]

svg = [
    f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
    rect(0, 0, W, H, BG, 0),
    text(70, 78, "A fixed seed did not fix the trajectory", 45, WHITE, 700),
    text(70, 122, "W31 · 64-trial targeted reproducibility stress test · two exact repeats per pair", 23, MUTED),
    rect(55, 155, 900, 575, PANEL, 18, GRID),
    rect(980, 155, 565, 575, PANEL, 18, GRID),
    text(90, 205, "Within-pair exact agreement", 28, WHITE, 700),
    text(1015, 205, "Unauthorized action executed", 28, WHITE, 700),
    text(1015, 238, "Ministral only · sequential + concurrent", 20, MUTED),
]

labels = [("breach", "Breach outcome"), ("action", "Action sequence"), ("output", "Victim message output")]
families = [("qwen3", "Qwen3-8B", GREEN), ("ministral", "Ministral-8B", AMBER)]
bar_x, bar_w = 330, 560
for family_index, (family, display, color) in enumerate(families):
    top = 250 + family_index * 235
    svg.append(text(90, top, display, 25, color, 700))
    for item_index, (field, label) in enumerate(labels):
        y = top + 35 + item_index * 58
        count, n = agreement[family][field], agreement[family]["n"]
        svg.extend(
            [
                text(90, y + 25, label, 20, MUTED),
                rect(bar_x, y, bar_w, 30, GRID, 6),
                rect(bar_x, y, bar_w * count / n, 30, color, 6),
                text(bar_x + bar_w + 15, y + 24, f"{count}/{n}", 21, WHITE, 700),
            ]
        )

row_y = {"attack": 310, "control": 505}
for condition in ("attack", "control"):
    y = row_y[condition]
    svg.append(text(1015, y, "Attack prompts" if condition == "attack" else "Ordinary-support controls", 24, WHITE, 700))
    for offset, (config, label, color) in enumerate((("l1", "Granite L1", RED), ("boundary", "L1 + authorization", GREEN))):
        k, n = outcome[(condition, config)]
        line_y = y + 43 + offset * 62
        svg.extend(
            [
                text(1015, line_y + 23, label, 20, MUTED),
                rect(1245, line_y, 210, 30, GRID, 6),
                rect(1245, line_y, 210 * k / n if n else 0, 30, color, 6),
                text(1485, line_y + 24, f"{k}/{n}", 21, WHITE, 700, "end"),
            ]
        )

svg.extend(
    [
        rect(55, 755, 1490, 82, "#13291a", 14, GREEN),
        text(80, 790, "30/32 pairs agreed on breach; only 21/32 reproduced the exact action sequence.", 27, WHITE, 700),
        text(80, 820, "Two identical-seed Ministral/L1 pairs split on breach under concurrent serving.", 22, AMBER, 600),
        text(70, 875, "Selected stress-test seeds; not a population-risk estimate. Full-output equality includes tool-call IDs. W31 is outside the 810-record core corpus.", 18, MUTED),
        "</svg>",
    ]
)

(HERE / "reproducibility_slide.svg").write_text("\n".join(svg) + "\n")
print(HERE / "reproducibility_slide.svg")
