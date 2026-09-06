#!/usr/bin/env python3
"""Stage 5: write the records/distinct ratio of the sweep corpus into the
README between markers. The only thing this script edits is that block."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from saster_instrument.metrics import distinct_trajectories  # noqa: E402

START, END = "<!-- sweep-ratio:start -->", "<!-- sweep-ratio:end -->"


def corpus(roots: tuple[str, ...], tag: str) -> list[dict]:
    # A later root replaces a cell id: the re-run is the record of that cell.
    by_cell: dict[str, list[dict]] = {}
    for root in roots:
        sp = REPO / f"runs/{root}_sweep_{tag}/sweep_state.json"
        if sp.exists():
            for cid, cell in json.loads(sp.read_text())["cells"].items():
                p = REPO / cell["dir"] / "trajectories.jsonl"
                if p.exists():
                    by_cell[cid] = [json.loads(line) for line in p.open() if line.strip()]
    return [r for recs in by_cell.values() for r in recs]


def main() -> None:
    rows = []
    for label, roots, tag in (("Qwen3-8B, sweep", ("w24b", "w24c"), "qwen3"),
                              ("Ministral-8B, sweep", ("w24b", "w24c"), "ministral"),
                              ("Qwen3-8B forced, §P arm", ("w25p",), "qwen3")):
        recs = corpus(roots, tag)
        d = distinct_trajectories(recs)
        rows.append(f"| {label} | {len(recs)} | {d} | {len(recs) / d:.2f} |")
    block = "\n".join([START, "", "### Sweep corpus, September 2026 (written by `scripts/write_readme_ratio_w25.py`)", "",
                       "| corpus | records | distinct action sequences | records/distinct |", "|---|---|---|---|", *rows, "",
                       "Distinct is the count of unique tool-and-argument sequences (`saster_instrument.metrics.distinct_trajectories`). "
                       "k=5 paired seeds per cell; a ratio near 1 means the seeds produced different trajectories, a ratio near 5 means they did not.", "", END])
    readme = REPO / "README.md"
    text = readme.read_text()
    if START in text:
        text = re.sub(re.escape(START) + ".*?" + re.escape(END), block, text, flags=re.S)
    else:
        text = text.replace("\n## Documentation", "\n" + block + "\n\n## Documentation", 1)
    readme.write_text(text)
    print("\n".join(rows))


if __name__ == "__main__":
    main()
