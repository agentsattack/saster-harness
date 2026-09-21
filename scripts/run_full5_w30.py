#!/usr/bin/env python3
"""Run W30's eight all-five-layer cells using the existing, unchanged ops driver."""
import concurrent.futures
import hashlib
import json
import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ROOT = REPO / "runs/w30_readiness/full5"
MODELS = {"qwen3": "Qwen/Qwen3-8B", "ministral": "mistralai/Ministral-8B-Instruct-2410"}


def main():
    ROOT.mkdir(parents=True, exist_ok=False)
    cases = []
    for mode_i, mode in enumerate(("compromised", "induced")):
        for obstructed in (0, 1):
            for family, model in MODELS.items():
                cases.append({"id": f"{family}-{mode}-obstructed{obstructed}", "family": family,
                              "model": model, "mode": mode, "obstructed": obstructed,
                              "seed": 2026093000 + 100 * (mode_i * 2 + obstructed), "k": 5})
    manifest = {"cases": cases, "protocol_sha256": hashlib.sha256((REPO / "docs/followup-experiments-w30.md").read_bytes()).hexdigest(),
                "driver_sha256": hashlib.sha256((REPO / "scripts/run_cell_w9.py").read_bytes()).hexdigest(),
                "wrapper_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "approval": "scripted auto_approve; NOT human", "layer_set": ["L1", "L2", "L3", "L4", "L5"],
                "new_arm": True, "canary": "W30 preflight_admission.json: real victim, guard, OPA and z3 checks", "trajectory_budget": 12}
    (ROOT / "plan.json").open("x").write(json.dumps(manifest, indent=2))
    (ROOT / "run_cell_w9.frozen.py").open("xb").write((REPO / "scripts/run_cell_w9.py").read_bytes())

    def cell(c):
        out = ROOT / c["id"]
        env = {k: v for k, v in os.environ.items() if not k.startswith("W9_")}
        env.update({"W9_OUT": str(out), "W9_RUN_ID": "w30-full5-" + c["id"], "W9_CAMPAIGN_ID": "w30-full5-" + c["id"],
                    "W9_ARM": "W30-full5", "W9_VICTIM": c["model"], "W9_MODE": c["mode"], "W9_OBSTRUCTED": str(c["obstructed"]),
                    "W9_SEED": str(c["seed"]), "W9_K": "5", "W9_DEFENSE": "all5", "W9_ROUTE": "agent",
                    "W9_L2_RULES": "4", "W9_ENVELOPE": "not_computed", "W9_SKIP_CANARY": "1", "W9_OBSERVER": "binary",
                    "W9_RECORDED_HEADS": "fg", "W9_L1_ENDPOINT": "http://[fd00:200::4]:8003",
                    "W9_L1_MODEL": "ibm-granite/granite-guardian-3.2-5b",
                    "W9_L1_REVISION": "d97903719a4fe78cb7099eb1ebc7defc96d26a37",
                    "W9_L1_IMAGE_DIGEST": "sha256:735caabf4f1e52c5a343a68793aab86690683465cc51d76dd84f7af011750639",
                    "W9_STORAGE_PRIMARY": str(out), "W9_STORAGE_MIRROR": "spark8:~/evidence/w30-readiness",
                    "PYTHONPATH": str(REPO) + ":/home/lbsuto/halctf-agent"})
        with (ROOT / (c["id"] + ".console.log")).open("x") as log:
            p = subprocess.run([str(REPO / ".venv/bin/python"), "-u", "scripts/run_cell_w9.py"], cwd=REPO, env=env, stdout=log, stderr=subprocess.STDOUT)
        status = {"case": c, "exit": p.returncode}
        if (out / "trajectories.jsonl").exists():
            records = [json.loads(x) for x in (out / "trajectories.jsonl").read_text().splitlines() if x]
            status.update(records=len(records), breaches=sum(r["oracle"]["breach"] for r in records))
        (ROOT / (c["id"] + ".status.json")).open("x").write(json.dumps(status, indent=2))
        print(status, flush=True)
        return status

    with concurrent.futures.ThreadPoolExecutor(2) as ex:
        list(ex.map(cell, cases))


if __name__ == "__main__":
    main()
