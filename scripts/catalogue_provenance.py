#!/usr/bin/env python3
"""Catalogue provenance and survival time (A1). The row table is DATA here so
a corrected assignment is a one-line edit; hours are read from git, never
typed. Writes docs/catalogue-provenance.md and runs/unprompted/catalogue.json."""
from __future__ import annotations

import json
import re
import statistics
import subprocess
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# (row, what, direction, caught_by, introduce, fix, note)
# C rows: the CFP's first table is not in the repository; rows are
# reconstructed from docs/instrument-test-plan.md's class↔row mapping and the
# W-era commit bodies. Flagged in the document; confirm or correct here.
C_ROWS = [
    ("C1", "L4 wrapper: the binary head was asked the fine-grained question, answered with a taxonomy group header, and the layer recorded unavailable on every trajectory — no verdict rendered anywhere (W14)", "neutral", "reading", "3265bef", "c367b14", "reconstructed: plan Class 1"),
    ("C2", "L4 replies capped at max_tokens 8, so every fine-grained reply was truncated before its verdict, and the prompt asked for WARN/ALLOW — tokens the head was never trained to emit (W11)", "toward-held", "reading", "3265bef", "6281260", "reconstructed: plan Class 1; the truncation in docs/w11-fine-grained.md"),
    ("C3", "envelope scorer normalization: summed per-token logprob favours short candidates; SUM saturates Qwen to entropy 0.000 (W13)", "neutral", "reading", "a38d991", "479fe5a", "reconstructed: plan Class 2 (length invariance)"),
    ("C4", "the scorer rendered a prefix the agent never held (chat_template_kwargs not threaded): 1029 tokens vs 1025, every envelope conditioned on the wrong prefix (W9)", "neutral", "reconcile", "a38d991", "562ac77", "reconstructed: plan Class 2 (template round-trip)"),
    ("C5", "denominator: twelve induced cells replayed the same five seeds; 0/60 was really 0/5, Wilson [0, 6.0%] reported where [0, 43.4%] held (W15/W16)", "toward-held", "reading", "94afa50", "385329e", "reconstructed: plan Class 3"),
    ("C6", "unit mismatch: markers in action space subtracted from oracle indices in snapshot space; containment latency came out an integer every rule accepted, 0 on the reference route where 6 holds (W10, Amendment 6)", "toward-held", "reading", "2a13fa4", "951a7d6", "reconstructed: plan Class 4"),
    ("C7", "wrong surface: envelope scored /v1/completions over a prose prefix while the agent sampled /v1/chat/completions with a tools array (W7b)", "neutral", "reading", "a38d991", "eb4c84f", "reconstructed: plan Class 5"),
    ("C8", "wrong object: a teacher-forced ranking over a closed candidate set reported as the agent's action distribution — 99.0% of uniform entropy against an agent at 1.3% (W13, Amendment 9)", "away", "reading", "a38d991", "479fe5a", "reconstructed: plan Class 5"),
    ("C9", "label: 515 records carried saster_category SASTER-24, which the fixture cannot satisfy; nothing read the field (W21)", "neutral", "reading", "2a13fa4", "68a3085", "reconstructed: plan Class 6"),
    ("C10", "scope: a detection entry recorded for an action that detected nothing — first_detection_step named nothing real (W10, Amendment 7)", "toward-held", "reading", "2a13fa4", "951a7d6", "reconstructed: plan Class 7"),
    ("C11", "the Python Rego mirror stood in for OPA under a real-looking label until the real backend was wired and a divergence test added (S1 D1)", "toward-held", "real-backend swap", "3265bef", "0e5cd4b", "in or out per the CFP as submitted — not resolvable from the repository"),
]
D_DIRECTION = {"toward-held": "toward-held", "erased": "erased-toward-held", "neutral": "neutral", "mixed": "mixed", "away": "away", "toward-false-alarm": "toward-false-alarm"}
D_CAUGHT = {**{f"D{i}": "rejection test" for i in range(1, 9)}, "D9": "gate", "D10": "gate", "D11": "gate", "D12": "sweep", "D13": "sweep", "D14": "sweep", "D15": "reading", "D16": "gate", "D17": "reading", "D18": "gate"}


def when(h: str) -> datetime:
    out = subprocess.run(["git", "log", "-1", "--format=%cI", h], cwd=REPO, capture_output=True, text=True, check=True).stdout.strip()
    return datetime.fromisoformat(out)


def d_rows():
    text = (REPO / "docs/defect-log.md").read_text()
    rows = []
    for line in text.splitlines():
        m = re.match(r"^\| (D\d+) \| (.+?) \| ([^|]+?) \| (.+?) \| (.+?) \| (.+?) \|$", line)
        if not m:
            continue
        did, what, direction, _fa, fix, intro = m.groups()
        direction = direction.strip().split(" ")[0]
        fixh = re.findall(r"`([0-9a-f]{7,})`", fix)
        introh = re.findall(r"`([0-9a-f]{7,})`", intro)
        rows.append((did, what, D_DIRECTION.get(direction, direction), D_CAUGHT.get(did, "?"), introh[0] if introh else None, fixh[0] if fixh else None, "no fix" if "no fix" in fix else ""))
    return rows


def main():
    rows = []
    for row, what, direction, caught, intro, fix, note in C_ROWS + d_rows():
        hours = None
        if intro and fix:
            hours = round((when(fix) - when(intro)).total_seconds() / 3600, 1)
        rows.append({"row": row, "what": what, "direction": direction, "caught_by": caught, "introduce": intro, "fix": fix, "hours": hours, "note": note})
    def med(sel):
        xs = [r["hours"] for r in rows if sel(r) and r["hours"] is not None]
        return (round(statistics.median(xs), 1), len(xs)) if xs else (None, 0)
    dirs = sorted({r["direction"] for r in rows})
    caught = sorted({r["caught_by"] for r in rows})
    flattering = med(lambda r: r["direction"] in ("toward-held", "erased-toward-held"))
    unflattering = med(lambda r: r["direction"] in ("away", "toward-false-alarm"))
    neutral = med(lambda r: r["direction"] in ("neutral", "mixed"))
    lines = ["# Catalogue provenance and survival time (A1)", "",
             "Twenty-eight rows: C1–C11 read-caught (the CFP's first table) and D1–D18 instrument-caught (`docs/defect-log.md`). "
             "Hours are `git log %cI` of the fix minus the introducing commit; the introducing commit is the one that first added the code carrying the assumption, "
             "or the file's first commit where the assumption is as old as the file. Generated by `scripts/catalogue_provenance.py`; the row table is data in that script.", "",
             "**Caveat on C1–C11.** `docs/unprompted-cfp-final-v3.md` is not in the repository, so the C rows are reconstructed from the instrument test plan's class↔row mapping "
             "and the W-era commit bodies; each carries its reconstruction note. Row C11 (the Rego mirror) is in or out per the CFP as submitted and could not be resolved here. "
             "A corrected assignment is a one-line edit in the script and the medians recompute.", "",
             "| row | what | direction | caught by | introduce | fix | hours | note |", "|---|---|---|---|---|---|---|---|"]
    lines += [f"| {r['row']} | {r['what']} | {r['direction']} | {r['caught_by']} | `{r['introduce']}` | `{r['fix']}` | {r['hours'] if r['hours'] is not None else '—'} | {r['note']} |" for r in rows]
    lines += ["", "## Median hours to fix, by direction", "", "| direction | median h | n |", "|---|---|---|"]
    lines += [f"| {d} | {med(lambda r, d=d: r['direction'] == d)[0]} | {med(lambda r, d=d: r['direction'] == d)[1]} |" for d in dirs]
    lines += ["", f"Pooled: flattering (toward-held, erased-toward-held) median **{flattering[0]} h** (n={flattering[1]}); unflattering (away, toward-false-alarm) **{unflattering[0]} h** (n={unflattering[1]}); neutral or mixed **{neutral[0]} h** (n={neutral[1]}).", ""]
    verdict = "Flattering errors survived longer" if (flattering[0] or 0) > (unflattering[0] or 0) else "Flattering errors did not survive longer"
    lines += [f"**{verdict}** on these rows, at the medians above; the n on the unflattering side is small enough that the comparison is a statement about this catalogue, not a rate.", "",
              "## Median hours to fix, by caught-by", "", "| caught by | median h | n |", "|---|---|---|"]
    lines += [f"| {c} | {med(lambda r, c=c: r['caught_by'] == c)[0]} | {med(lambda r, c=c: r['caught_by'] == c)[1]} |" for c in caught]
    lines += ["", "Per-row data: `runs/unprompted/catalogue.json`."]
    (REPO / "docs/catalogue-provenance.md").write_text("\n".join(lines) + "\n")
    (REPO / "runs/unprompted").mkdir(parents=True, exist_ok=True)
    (REPO / "runs/unprompted/catalogue.json").write_text(json.dumps(rows, indent=1))
    for r in rows:
        print(f"{r['row']:<4} {r['direction']:<20} {r['caught_by']:<18} {r['introduce']} → {r['fix']}  {r['hours']} h  {r['note'][:40]}")
    print("flattering", flattering, "unflattering", unflattering, "neutral", neutral)


if __name__ == "__main__":
    main()
