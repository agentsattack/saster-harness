#!/usr/bin/env python3
"""W32 — addendum §V-extended: the 1.5 coarse head to n = 90.

Pool: every sweep matrix record whose cell carries the head's sidecar (the
L4-carrying configs, both families, breaching or not) minus the 30 already
replayed in §V. Draw 60 by family × config, largest remainder, at least one
per stratum, seed 20260914. Replay identical to §V. Report the flip rate
with a Wilson 95% interval over the 90, over the 60 alone, and by oracle
breach. No tolerance: the head is qualified; this is its interval.
"""
from __future__ import annotations

import collections
import hashlib
import json
import math
import os
import random
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import relocation_fidelity_w32 as F  # noqa: E402  — same heads, endpoints, replay, allocation
from saster_defense.manifest import grrcon_addendum_sha256  # noqa: E402

RUN_ID = os.environ.get("W32_RUN_ID", "w32-relocation-fidelity-ext-20260912")
OUT = Path(os.environ.get("W32_OUT", REPO / "runs/w32_relocation_fidelity_ext"))
PRIOR = REPO / "runs/w32_relocation_fidelity"
HEAD = "15coarse"
SEED = 20260914
N_NEW = 60
WORKERS = int(os.environ.get("W32_HEAD_WORKERS", "4"))


def wilson(k: int, n: int, z: float = 1.959963985) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def load_pool() -> list[dict]:
    """Every sweep matrix record with a 15coarse sidecar verdict."""
    out = []
    for store in F.STORES:
        family = "qwen3" if store.endswith("qwen3") else "ministral"
        for cell_dir in sorted((REPO / store / "cells").iterdir()):
            tf, sf = cell_dir / "trajectories.jsonl", cell_dir / "diagnoses.jsonl"
            if not tf.exists() or not sf.exists():
                continue
            cell = cell_dir.name
            cfg = cell.split("__")[1]
            sidecar: dict[int, str] = {}
            for line in sf.open():
                d = json.loads(line)
                if d.get("layer") == "l4_auditor" and d.get("head") == HEAD:
                    sidecar[d["trial_index"]] = d["verdict"]
            for line in tf.open():
                r = json.loads(line)
                if r["trial_index"] not in sidecar:
                    continue
                out.append({"id": f"{store}/cells/{cell}#{r['trial_index']}", "store": store, "cell": cell,
                            "trial_index": r["trial_index"], "family": family, "cfg": cfg,
                            "breach": bool(r["oracle"].get("breach")), "campaign_id": r["campaign_id"], "run_id": r["run_id"],
                            "sealed_heads": {HEAD: sidecar[r["trial_index"]]}, "has_sidecar": True, "record": r})
    return out


def main() -> None:
    if OUT.exists():
        raise SystemExit(f"refusing to overwrite {OUT}")
    OUT.mkdir(parents=True)
    t_start = datetime.now(UTC).isoformat()
    prior_rows = [json.loads(l) for l in (PRIOR / "replay_heads.jsonl").open() if json.loads(l)["head"] == HEAD]
    prior_ids = {x["id"] for x in prior_rows}
    pool = load_pool()
    eligible = [r for r in pool if r["id"] not in prior_ids]
    new = F.draw(eligible, N_NEW, SEED)
    for r in new:
        r["draw"] = "extension"
    strata = collections.Counter((r["family"], r["cfg"]) for r in eligible)
    sample = {"run_id": RUN_ID, "seed": SEED, "pool_with_sidecar": len(pool), "prior_ids": sorted(prior_ids),
              "eligible": len(eligible), "strata_eligible": {f"{f}/{c}": n for (f, c), n in sorted(strata.items())},
              "allocation": {f"{f}/{c}": n for (f, c), n in sorted(F.allocate(dict(strata), N_NEW).items())},
              "extension": [F.sample_view(r, "extension") | {"breach": r["breach"]} for r in new]}
    (OUT / "sample.json").write_text(json.dumps(sample, indent=2))
    sample_sha = hashlib.sha256((OUT / "sample.json").read_bytes()).hexdigest()
    print(f"sample written: pool {len(pool)}, eligible {len(eligible)}, drawn {len(new)}; sha256 {sample_sha[:12]}")
    served = F.served(F.HEADS[HEAD][1])
    if "error" in served:
        raise SystemExit(f"{HEAD} not served: {served['error']}")

    with ThreadPoolExecutor(max_workers=WORKERS) as pool_, (OUT / "replay_heads.jsonl").open("w") as fh:
        for row in pool_.map(lambda r: F.replay_head(HEAD, r) | {"breach": r["breach"]}, new):
            fh.write(json.dumps(row) + "\n")
            fh.flush()
    new_rows = [json.loads(l) for l in (OUT / "replay_heads.jsonl").open()]
    breach_of = {r["id"]: r["breach"] for r in pool}
    for x in prior_rows:
        x["breach"] = breach_of.get(x["id"])

    def stats(rows: list[dict]) -> dict:
        n = len(rows)
        flips = [x for x in rows if x["sealed"] != x["replay"]]
        unav = sum(1 for x in rows if x["replay"] == "unavailable")
        lo, hi = wilson(len(flips), n)
        return {"n": n, "flips": len(flips), "unavailable_on_replay": unav, "rate": len(flips) / n if n else None,
                "wilson95": [round(lo, 4), round(hi, 4)],
                "flip_ids": [{"id": x["id"], "sealed": x["sealed"], "replay": x["replay"], "breach": x.get("breach")} for x in flips]}

    combined = prior_rows + new_rows
    result = {
        "head": HEAD, "serving_sensitive": True, "run_id": RUN_ID,
        "combined_90": stats(combined), "extension_60": stats(new_rows), "section_v_30": stats(prior_rows),
        "by_breach": {"breaching": stats([x for x in combined if x.get("breach")]),
                      "non_breaching": stats([x for x in combined if x.get("breach") is False])},
        "by_direction": dict(collections.Counter(f"{x['sealed']}->{x['replay']}" for x in combined if x["sealed"] != x["replay"])),
    }
    (OUT / "result.json").write_text(json.dumps(result, indent=2))
    manifest = {"run_id": RUN_ID, "role": "addendum §V-extended", "started_utc": t_start,
                "finished_utc": datetime.now(UTC).isoformat(),
                "code_commit": subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True).stdout.strip(),
                "grrcon_addendum_sha256": grrcon_addendum_sha256(), "sample_sha256": sample_sha,
                "head": {"key": HEAD, "model": F.HEADS[HEAD][0], "endpoint": F.HEADS[HEAD][1], "prompt_style": F.HEADS[HEAD][2],
                         "fine_grained": F.HEADS[HEAD][3], "gpu_memory_utilization": F.HEADS[HEAD][4], "served": served,
                         "serving_sensitive": True},
                "image": F.IMAGE, "temperature": 0.0, "replay_role": "recorded", "prior_run": str(PRIOR.relative_to(REPO)),
                "corpus_written": False}
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2))
    c = result["combined_90"]
    lines = [f"# §V-extended — {RUN_ID}", "", "| set | n | flips | unavailable | rate | Wilson 95% |", "|---|---|---|---|---|---|"]
    for name in ("combined_90", "extension_60", "section_v_30"):
        s = result[name]
        lines.append(f"| {name} | {s['n']} | {s['flips']} | {s['unavailable_on_replay']} | {s['rate']:.3f} | {s['wilson95'][0]:.3f}–{s['wilson95'][1]:.3f} |")
    for name, s in result["by_breach"].items():
        lines.append(f"| {name} | {s['n']} | {s['flips']} | {s['unavailable_on_replay']} | {s['rate']:.3f} | {s['wilson95'][0]:.3f}–{s['wilson95'][1]:.3f} |")
    lines += ["", "Directions: " + json.dumps(result["by_direction"]), "", "## Flips", ""]
    lines += [f"- `{f['id']}` sealed `{f['sealed']}` replay `{f['replay']}` (breach={f['breach']})" for f in c["flip_ids"]] or ["none"]
    (OUT / "report.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
