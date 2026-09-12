#!/usr/bin/env python3
"""W34 — addendum §Y: Arm A cross-family invariance over every registered metric.

Reads the six Arm A cells under ``runs/w34_arm_a/<family>/<route>/`` and,
for every entry of ``saster_instrument.METRICS``, compares values across
the families that carry the metric at each comparable key:

* per step  — (route, trial, step): surprisal (per action), refusal_prob,
              declared_in, declared_out, prohibition_out (per turn);
* per record — (route, trial): containment_latency;
* per cell   — (route,): cvr, breach_rate, records_distinct_ratio.

A metric identical to six decimals across every carrying family at every
compared key raises ``SuspectedInstrumentArtifact``. Output: the per-metric
table, the metric × family heatmap ("did this number move") as PNG at
1920×1080 with its JSON, and the between/within variance structure.
"""
from __future__ import annotations

import collections
import json
import os
import statistics
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from saster_instrument import METRICS  # noqa: E402
from saster_instrument import metrics as _m  # noqa: E402
from saster_defense.manifest import grrcon_addendum_sha256  # noqa: E402

ROOT = Path(os.environ.get("W34_ROOT", REPO / "runs/w34_arm_a"))
OUT = Path(os.environ.get("W34_OUT", ROOT / "invariance"))
FAMILIES = ("qwen3", "mistral", "deepseek")
ROUTES = ("firewall", "grant")
DECIMALS = 6
SERVING_SENSITIVE = {"15coarse"}


class SuspectedInstrumentArtifact(Exception):
    pass


def q(x):
    return None if x is None else round(float(x), DECIMALS)


CELL_DIRS: dict[tuple[str, str], str] = {}


def load() -> dict[tuple[str, str], list[dict]]:
    """A cell is ``<family>/<route>``; a cell whose first run aborted before
    writing records is read from its rerun directory ``<route>-r2`` (new run
    id), and the directory used is recorded in the output."""
    cells = {}
    for fam in FAMILIES:
        for route in ROUTES:
            for d in (route, f"{route}-r2"):
                f = ROOT / fam / d / "trajectories.jsonl"
                if f.exists():
                    cells[(fam, route)] = [json.loads(l) for l in f.open() if l.strip()]
                    CELL_DIRS[(fam, route)] = f"{fam}/{d}"
                    break
    return cells


def values(cells) -> dict[str, dict[tuple, dict[str, float | None]]]:
    """metric -> key -> family -> value (None = not carried / null)."""
    out: dict[str, dict[tuple, dict[str, float | None]]] = collections.defaultdict(lambda: collections.defaultdict(dict))
    for (fam, route), recs in cells.items():
        for r in recs:
            t = r["trial_index"]
            for a in r["actions"]:
                out["surprisal"][(route, t, a["step_index"])][fam] = q(a.get("surprisal"))
            for i, turn in enumerate(r["turns"]):
                out["refusal_prob"][(route, t, i)][fam] = q(turn.get("refusal_prob"))
                em = turn.get("envelope_mass") or {}
                for k in ("declared_in", "declared_out", "prohibition_out"):
                    out[k][(route, t, i)][fam] = q(em.get(k))
            out["containment_latency"][(route, t)][fam] = q((r.get("containment_latency") or {}).get("value"))
        actions = [a for r in recs for a in r["actions"]]
        out["cvr"][(route,)][fam] = q(_m.cvr_rate(actions))
        out["breach_rate"][(route,)][fam] = q(_m.breach_within_k([bool(r["oracle"].get("breach")) for r in recs]))
        out["records_distinct_ratio"][(route,)][fam] = q(_m.records_distinct_ratio(recs))
    return out


def main() -> None:
    if OUT.exists():
        raise SystemExit(f"refusing to overwrite {OUT}")
    cells = load()
    missing = [(f, r) for f in FAMILIES for r in ROUTES if (f, r) not in cells]
    if missing:
        raise SystemExit(f"cells missing: {missing}")
    OUT.mkdir(parents=True)
    vals = values(cells)
    table = {}
    moved = {fam: {} for fam in FAMILIES}
    flagged = []
    for metric in METRICS:
        keys = vals.get(metric, {})
        compared = identical = 0
        carrying = sorted({fam for fv in keys.values() for fam, v in fv.items() if v is not None})
        per_fam_moved = {fam: [0, 0] for fam in carrying}
        for key, fv in keys.items():
            present = {fam: v for fam, v in fv.items() if v is not None}
            if len(present) < 2:
                continue
            compared += 1
            distinct = len(set(present.values()))
            if distinct == 1:
                identical += 1
            for fam, v in present.items():
                per_fam_moved[fam][1] += 1
                if any(v != w for g, w in present.items() if g != fam):
                    per_fam_moved[fam][0] += 1
        # variance structure over per-key values: between families vs within family across k
        by_fam = collections.defaultdict(list)
        for key, fv in keys.items():
            for fam, v in fv.items():
                if v is not None:
                    by_fam[fam].append(v)
        fam_means = [statistics.mean(v) for v in by_fam.values() if v]
        between = statistics.pvariance(fam_means) if len(fam_means) >= 2 else None
        within = statistics.mean([statistics.pvariance(v) for v in by_fam.values() if len(v) >= 2]) if any(len(v) >= 2 for v in by_fam.values()) else None
        row = {"carrying_families": carrying, "n_families": len(carrying), "keys_compared": compared,
               "keys_identical": identical, "fraction_identical": (identical / compared) if compared else None,
               "lower_power": len(carrying) < 3,
               "between_family_variance": between, "within_family_variance": within,
               "variance_note": ("degenerate: zero between and zero within" if between == 0 and within == 0 else
                                 "suspicious: zero between, nonzero within" if between == 0 and (within or 0) > 0 else
                                 "moves"),
               "suspected_instrument_artifact": compared > 0 and identical == compared}
        table[metric] = row
        if row["suspected_instrument_artifact"]:
            flagged.append(metric)
        for fam in FAMILIES:
            m, n = per_fam_moved.get(fam, [0, 0])
            moved[fam][metric] = (m / n) if n else None
    result = {"run_id": "w34-arm-a-invariance-20260912", "metrics": table, "flagged": flagged,
              "expected_informative_flags": ["records_distinct_ratio"],
              "negative_control_surprisal_ok": not table["surprisal"]["suspected_instrument_artifact"],
              "positive_control": {"status": "not run", "reason": "requires re-scoring the Arm A records under the mutant trees "
                                   "(C3, C4, C6, C10); no post hoc marker re-scoring path exists for these mutants in this tree — "
                                   "reported, not simulated"},
              "heatmap": moved, "cells": {f"{f}/{r}": len(v) for (f, r), v in cells.items()},
              "cell_dirs": {f"{f}/{r}": d for (f, r), d in CELL_DIRS.items()},
              "code_commit": subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True).stdout.strip(),
              "grrcon_addendum_sha256": grrcon_addendum_sha256(), "measured_utc": datetime.now(UTC).isoformat()}
    (OUT / "invariance.json").write_text(json.dumps(result, indent=2))

    metrics = list(METRICS)
    fig, ax = plt.subplots(figsize=(19.2, 10.8), dpi=100)
    grid = [[(moved[f][m] if moved[f].get(m) is not None else float("nan")) for f in FAMILIES] for m in metrics]
    im = ax.imshow(grid, cmap="viridis", vmin=0, vmax=1, aspect="auto")
    ax.set_xticks(range(len(FAMILIES)), [f"{f}\n({'A' if f == 'qwen3' else 'B' if f == 'mistral' else 'C'})" for f in FAMILIES], fontsize=14)
    ax.set_yticks(range(len(metrics)), [f"{m}  ⚠ identical everywhere" if table[m]["suspected_instrument_artifact"] else m
                                        for m in metrics], fontsize=14)
    for i, m in enumerate(metrics):
        for j, f in enumerate(FAMILIES):
            v = moved[f].get(m)
            txt = "not carried" if v is None else f"{v:.2f}"
            ax.text(j, i, txt, ha="center", va="center", fontsize=13, color="white" if (v or 0) < 0.6 else "black")
    ax.set_title("Arm A — did this number move? fraction of compared keys where the family's value differs from another family's\n"
                 "(config all-on, obstructed, compromised; routes firewall + grant; k = 5; envelope not computed for C by scope)", fontsize=15)
    fig.colorbar(im, ax=ax, fraction=0.03, label="fraction moved")
    fig.tight_layout()
    fig.savefig(OUT / "invariance_heatmap.png")
    (OUT / "invariance_heatmap.json").write_text(json.dumps({"rows": metrics, "cols": list(FAMILIES), "grid": grid,
                                                             "flagged": flagged}, indent=2))
    print(json.dumps({m: {k: table[m][k] for k in ("n_families", "keys_compared", "fraction_identical", "variance_note",
                                                     "suspected_instrument_artifact")} for m in metrics}, indent=1))
    print("flagged:", flagged, "| surprisal negative control ok:", result["negative_control_surprisal_ok"])
    if flagged:
        raise SuspectedInstrumentArtifact(", ".join(flagged))


if __name__ == "__main__":
    try:
        main()
    except SuspectedInstrumentArtifact as exc:
        print(f"SuspectedInstrumentArtifact: {exc}")
        sys.exit(2)
