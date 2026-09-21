#!/usr/bin/env python3
"""Serial repeat after a recorded shared-Z3-context error in the two-thread replay."""
import hashlib
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO))
from scripts import full5_controls_w30 as base


class SerialExecutor(ThreadPoolExecutor):
    def __init__(self, _requested_workers):
        super().__init__(max_workers=1)


if __name__ == "__main__":
    root=REPO / "runs/w30_readiness"
    plan={"created_utc":datetime.now(timezone.utc).isoformat(),
          "reason":"V1 control-00 recorded a Z3Exception in L3 under concurrent threads; an evaluator error, not a false-positive denial. Retain all 24 V1 records. Repeat all 24 fixed source controls serially, not just the failed case.",
          "source":"full5_controls/source_records.json", "parent":"full5_controls/plan.json",
          "change":"One worker instead of two; same models, prompts, policies and action paths. No attack-prompt tuning.",
          "wrapper_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
          "base_driver_sha256":hashlib.sha256(Path(base.__file__).read_bytes()).hexdigest()}
    (root / "full5_controls_v2_plan.json").open("x").write(json.dumps(plan,indent=2)+"\n")
    (root / "full5_controls_v2_wrapper.frozen.py").open("xb").write(Path(__file__).read_bytes())
    base.ROOT=root / "full5_controls_v2"
    base.ThreadPoolExecutor=SerialExecutor
    base.main()
