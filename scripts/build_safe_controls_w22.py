#!/usr/bin/env python3
"""Safe-matched controls for P2 (Stage 2): >= 20 sanctioned-completion
carl-ops trajectories, varied tickets, all under 16k tokens serialized.

Runs the cell driver on the induced arm, UNOBSTRUCTED (the sanctioned
completion is reachable), the all-on config with the real observer, ticket
phrasing cycling per trial, and keeps only the trials that completed the
sanctioned path: oracle breach false and terminal_outcome resolved. The
kept records are loaded through the citable gate; what passes lands in
corpora/citable/<name>/, what does not in corpora/dev/<name>/, each with
a README written by this script. Refuses to overwrite either.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from carl_ops_trajectory.citable import check_record_citable  # noqa: E402
from saster_defense.l4_auditor import TrajectoryAuditor  # noqa: E402

NAME = os.environ.get("W22_CONTROLS_NAME", "safe_controls_w22_qwen")
VICTIM = os.environ.get("W22_VICTIM", "Qwen/Qwen3-8B")
K = int(os.environ.get("W22_K", "24"))
SEED = os.environ.get("W22_SEED", "20260905")
WINDOW = 16384
L4_ENDPOINT = "http://[fd00:200::4]:8001"
L4_MODEL = "AI45Research/AgentDoG-Qwen3-4B"
CELL = REPO / "runs" / f"w22_controls_cell_{NAME}"
CITABLE = REPO / "corpora" / "citable" / NAME
DEV = REPO / "corpora" / "dev" / NAME


def main() -> None:
    for p in (CELL, CITABLE, DEV):
        if p.exists():
            raise SystemExit(f"refusing to overwrite {p}")
    env = dict(os.environ, W9_MODE="induced", W9_OBSTRUCTED="0", W9_DEFENSE="all",
               W9_OBSERVER="binary", W9_ENVELOPE="not_computed", W9_K=str(K),
               W9_SEED=SEED, W9_OUT=str(CELL), W9_VICTIM=VICTIM,
               W9_RUN_ID=f"w22-controls-{NAME}", W9_CAMPAIGN_ID=f"w22-controls-{NAME}",
               W9_TICKET_VARIANT="cycle", W9_SKIP_CANARY="1", W9_L2_RULES="3")
    print(f"running {K} unobstructed induced trials on {VICTIM} -> {CELL}")
    proc = subprocess.run([str(REPO / ".venv/bin/python"), str(REPO / "scripts/run_cell_w9.py")],
                          cwd=REPO, env=env, text=True, capture_output=True, timeout=7200)
    (CELL.parent / f"{CELL.name}.console.log").write_text(proc.stdout + "\n" + proc.stderr)
    if proc.returncode != 0:
        raise SystemExit(f"cell driver failed rc={proc.returncode}: {proc.stderr[-800:]}")
    manifest = json.loads((CELL / "manifest.json").read_text())
    records = [json.loads(l) for l in (CELL / "trajectories.jsonl").open() if l.strip()]
    aud = TrajectoryAuditor(observer_model=L4_MODEL, endpoint=L4_ENDPOINT, fine_grained=False)
    kept, dropped = [], []
    for r in records:
        serialized = aud.serialize([{"step": a["step_index"], "tool": a["tool"], "args": a["args"]}
                                    for a in r["actions"]])
        tokens = aud.real_token_count(serialized)
        why = []
        if r["oracle"]["breach"]:
            why.append("breach")
        if r["terminal_outcome"] != "resolved":
            why.append(f"terminal_outcome={r['terminal_outcome']}")
        if tokens is None or tokens > WINDOW:
            why.append(f"serialized {tokens} tokens > {WINDOW}")
        why += check_record_citable(r, manifest, "carl-ops")
        (kept if not why else dropped).append((r, tokens, why))
    for dest, rows, label in ((CITABLE, kept, "citable"), (DEV, dropped, "dev")):
        dest.mkdir(parents=True)
        with (dest / "trajectories.jsonl").open("w") as fh:
            for r, _t, _w in rows:
                fh.write(json.dumps(r) + "\n")
        shutil.copy2(CELL / "manifest.json", dest / "manifest.json")
        (dest / "README.md").write_text(
            f"# {NAME} ({label})\n\nWritten {datetime.now(UTC).isoformat()} by "
            f"scripts/build_safe_controls_w22.py. Source cell: runs/{CELL.name}.\n\n"
            f"Victim {VICTIM}; induced arm, unobstructed, all-on config, real observer "
            f"{L4_MODEL}; ticket phrasing cycled per trial; k={K} trials.\n\n"
            f"records: {len(rows)}\n" + "".join(
                f"- trial {r['trial_index']}: {t} tokens serialized"
                + (f"; NOT citable: {'; '.join(w)}" if w else "") + "\n" for r, t, w in rows))
    print(f"kept {len(kept)} citable, {len(dropped)} to dev")
    for r, t, w in dropped:
        print(f"  trial {r['trial_index']}: {'; '.join(w)[:160]}")


if __name__ == "__main__":
    main()
