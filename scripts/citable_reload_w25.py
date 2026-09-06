#!/usr/bin/env python3
"""Stage 5: reload every sweep and arm cell as citable. Failures are findings
with record ids, never fixes. Read-only."""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from carl_ops_trajectory.citable import (  # noqa: E402
    CitableViolation,
    MarkerUnpopulated,
    load_citable,
    marker_population_gate,
)

ROOTS = ("w24b", "w24c", "w25p", "w26r")


def main() -> None:
    report: dict = {"cells": 0, "records": 0, "violations": {}, "marker_gate": {}}
    all_records: dict[str, list[dict]] = {}
    chosen: dict[tuple[str, str], tuple[str, Path]] = {}
    for root in ROOTS:  # a later root replaces a cell id (the re-run is the record of that cell)
        for sp in sorted((REPO / "runs").glob(f"{root}_sweep_*/sweep_state.json")):
            tag = sp.parent.name.split("_sweep_", 1)[1]
            for cid, cell in json.loads(sp.read_text())["cells"].items():
                d = REPO / cell["dir"]
                if (d / "trajectories.jsonl").exists():
                    chosen[(tag if root not in ("w25p", "w26r") else root + "/" + tag, cid)] = (root, d)
    for (tag, cid), (root, d) in sorted(chosen.items()):
        if True:
            if True:
                report["cells"] += 1
                try:
                    recs, _ = load_citable(d / "trajectories.jsonl", d / "manifest.json", "carl-ops")
                except CitableViolation as exc:
                    report["violations"][f"{root}/{tag}/{cid}"] = str(exc)[:500]
                    recs = [json.loads(line) for line in (d / "trajectories.jsonl").open() if line.strip()]
                report["records"] += len(recs)
                all_records.setdefault(f"{root}/{tag}", []).extend(recs)
    for key, recs in all_records.items():
        try:
            report["marker_gate"][key] = marker_population_gate(recs)
        except MarkerUnpopulated as exc:  # a finding with campaign ids, never a fix
            failures = [f.strip() for f in str(exc).split("campaign ")[1:]]
            report["marker_gate"][key] = {"not_citable": True, "campaigns": len(failures), "detail": failures}
    out = REPO / "runs/w25_stage5/citable_reload.json"
    out.write_text(json.dumps(report, indent=1, default=str))
    print(f"cells {report['cells']} records {report['records']} cells with violations {len(report['violations'])}")
    for k, v in list(report["violations"].items())[:10]:
        print("  ", k, v[:200])
    for k, v in report["marker_gate"].items():
        print("  marker gate", k, {kk: vv for kk, vv in v.items() if not isinstance(vv, (list, dict))} if isinstance(v, dict) else v)


if __name__ == "__main__":
    main()
