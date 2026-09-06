#!/usr/bin/env python3
"""Which actions on each route the scope lock and the judge each see, and
what each says — the vendor-shaped config against the two fixture routes
with the REAL judge (a cluster model through the affinity router).

No trajectory record is produced; this is the pre-run report the sweep
prompt asks for beside P17. Refuses to overwrite its output.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from carl_ops_state.fixture import initial_state, obstructed_environment  # noqa: E402
from saster_defense import (  # noqa: E402
    DefenseConfig,
    DefenseStack,
    JudgeGuard,
    LockedScope,
    ScopeLock,
)
from saster_defense.types import LayerName  # noqa: E402
from tests.test_defense_stack import (  # noqa: E402
    FIREWALL_ROUTE,
    copy_into,
    create_bucket,
    grant_external,
    rotate,
)

ROUTER = os.environ.get("W22_ROUTER", "http://localhost:8080")
JUDGE_MODEL = os.environ.get("W22_JUDGE_MODEL", "Qwen/Qwen3-8B")
OUT = Path(os.environ.get("W22_OUT", REPO / "runs/w22_vendor_shaped_routes.json"))

ROUTES = {
    "grant": [rotate(), create_bucket(), copy_into(), grant_external()],
    "firewall": list(FIREWALL_ROUTE),
}


def main() -> None:
    if OUT.exists():
        raise SystemExit(f"refusing to overwrite {OUT}")
    lock = LockedScope.from_state(initial_state(obstructed_environment()))
    report = {"judge_model": JUDGE_MODEL, "router": ROUTER, "lock": lock.as_data()["lock"],
              "routes": {}}
    for name, route in ROUTES.items():
        stack = DefenseStack(config=DefenseConfig.vendor(), fixture_id="carl-ops",
                             scope_lock=ScopeLock(lock=lock),
                             judge=JudgeGuard(model=JUDGE_MODEL, endpoint=ROUTER,
                                              campaign_id=f"w22-routes-{name}"))
        rows = []
        print(f"\n== {name} route")
        for i, req in enumerate(route):
            res = stack.submit(req)
            lock_o = next(o for o in res.outcomes if o.layer is LayerName.SCOPE_LOCK)
            judge_o = next(o for o in res.outcomes if o.layer is LayerName.JUDGE)
            row = {"step": i, "tool": req.tool, "args": req.args,
                   "scope_lock": {"verdict": lock_o.verdict.value, "rule_id": lock_o.rule_id},
                   "judge": {"verdict": judge_o.verdict.value, "detail": judge_o.detail[:120]},
                   "blocked": res.blocked}
            rows.append(row)
            print(f"  {i} {req.tool:<26} lock={lock_o.verdict.value:<11} "
                  f"{(lock_o.rule_id or ''):<16} judge={judge_o.verdict.value:<11} "
                  f"{'BLOCKED' if res.blocked else ''}")
        report["routes"][name] = {"steps": rows,
                                  "denials": sum(r["blocked"] for r in rows),
                                  "lock_denials": sum(r["scope_lock"]["verdict"] == "deny" for r in rows),
                                  "judge_denials": sum(r["judge"]["verdict"] == "deny" for r in rows),
                                  "judge_unavailable": sum(r["judge"]["verdict"] == "unavailable" for r in rows)}
    OUT.write_text(json.dumps(report, indent=2))
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
