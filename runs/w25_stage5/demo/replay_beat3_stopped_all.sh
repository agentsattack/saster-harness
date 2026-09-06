#!/usr/bin/env bash
# Replay beat3_stopped_all against the live cluster: one trial, the sweep trial's own seed.
# Recorded: qwen3:matrix__all__obstructed__compromised__firewall#3  seed 20260910  run w24-qwen3-matrix__all__obstructed__compromised__firewall
# The 1.5 heads on spark2 are traded for the Ray worker after the sweep, so only the 1.0
# fine-grained head is recorded here; heads are post hoc and do not touch the action sequence.
# Output goes to a NEW directory per run — a replay is a new result beside the record, never over it.
set -euo pipefail
cd "$(dirname "$0")/../../.."
TS=$(date -u +%Y%m%dT%H%M%SZ); OUT=runs/w25_stage5/demo/replays/beat3_stopped_all_$TS; mkdir -p "$OUT"
export W9_VICTIM=Qwen/Qwen3-8B W9_DEFENSE=all W9_OBSTRUCTED=1 W9_MODE=compromised W9_ROUTE=firewall W9_L2_RULES=4 W9_JUDGE_PROMPT=scoped W9_TICKET_VARIANT=0 W9_SEED=20260910 W9_K=1 W9_ENVELOPE=not_computed W9_OBSERVER=binary W9_SKIP_CANARY=1 W9_RECORDED_HEADS=fg PYTHONPATH=/home/lbsuto/halctf-agent
export W9_OUT="$OUT" W9_RUN_ID="demo-beat3_stopped_all-$TS" W9_CAMPAIGN_ID="demo-beat3_stopped_all" W9_STORAGE_PRIMARY="$OUT" W9_STORAGE_MIRROR="none"
.venv/bin/python scripts/run_cell_w9.py
.venv/bin/python scripts/demo_compare_w27.py "$OUT/trajectories.jsonl" runs/w25_stage5/demo/beat3_stopped_all.json
