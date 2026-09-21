#!/usr/bin/env python3
"""Post hoc over the W38 clean-agent records: what the four AgentDoG heads say
about each trajectory's tool calls, and what the approval gate would have done.
Reads the sealed records; writes a sidecar under runs/w38_beat1_clean/heads/.
Nothing in any record changes."""
from __future__ import annotations

import glob
import json
import os
import sys
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from carl.support_agent import RESTRICTED_TOOLS  # noqa: E402
from saster_defense.l4_auditor import TrajectoryAuditor  # noqa: E402

H10 = os.environ.get("W9_HEADS_10_HOST", "[fd00:200::7]"); H15 = os.environ.get("W9_HEADS_15_HOST", "[fd00:200::5]")
HEADS = {
    "binary": ("AI45Research/AgentDoG-Qwen3-4B", f"http://{H10}:8001", "v1.0", False),
    "fg": ("AI45Research/AgentDoG-FG-Qwen3-4B", f"http://{H10}:8002", "v1.0", True),
    "15coarse": ("AI45Research/AgentDoG1.5-Qwen3.5-4B", f"http://{H15}:8001", "v1.5-coarse", False),
    "15fg": ("AI45Research/AgentDoG1.5-FG-Qwen3.5-4b", f"http://{H15}:8002", "v1.5-unified", True),
}
ROOT = REPO / "runs/w38_beat1_clean"; OUT = ROOT / "heads"; OUT.mkdir(exist_ok=True)
TOOLS_TEXT = json.dumps([{"name": t} for t in RESTRICTED_TOOLS], indent=2)
auditors = {}
for key, (model, endpoint, style, fg) in HEADS.items():
    try:
        httpx.get(f"{endpoint}/v1/models", timeout=5).raise_for_status()
        auditors[key] = TrajectoryAuditor(observer_model=model, endpoint=endpoint, fine_grained=fg, prompt_style=style, role="recorded", timeout=600, tool_list_text=TOOLS_TEXT)
    except httpx.HTTPError:
        print(f"head {key} unavailable at {endpoint}")
results = []
for p in sorted(glob.glob(str(ROOT / "w38-*/trajectories.jsonl"))):
    d = Path(p).parent
    if "smoke" in d.name: continue
    rec = json.loads(open(p).readline())
    actions = [{"step": a["step_index"], "tool": a["tool"], "args": a["args"]} for a in rec["actions"]]
    row = {"run_id": d.name, "breach": rec["oracle"]["breach"], "n_actions": len(actions), "heads": {},
           "l5_would": [{"step": a["step"], "tool": a["tool"], "gate": "escalate → auto-approve → proceeds"} for a in actions if a["tool"] in RESTRICTED_TOOLS]}
    if actions:
        for key, aud in auditors.items():
            out = aud.audit(actions)
            row["heads"][key] = {"verdict": out.verdict.value, "raw": (out.raw_reply or "")[:400]}
    results.append(row)
    print(d.name, "breach", row["breach"], {k: v["verdict"] for k, v in row["heads"].items()})
(OUT / "heads_posthoc.json").write_text(json.dumps(results, indent=1))
print("wrote", OUT / "heads_posthoc.json")
