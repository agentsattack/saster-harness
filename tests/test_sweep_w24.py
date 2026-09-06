"""The W24 sweep plan: 48 cells per victim, paired seeds per stratum shared
across configs and routes, vendor-shaped under the scoped judge prompt, the
P12 ladder unchanged at rungs 1..3, and the halt check."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _driver():
    os.environ.setdefault("W24_VICTIM", "Qwen/Qwen3-8B")
    spec = importlib.util.spec_from_file_location("run_sweep_w24", REPO / "scripts/run_sweep_w24.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


def test_plan_shape_and_pairing():
    m = _driver()
    plan = m.cell_plan(k=5)
    assert len(plan) == 7 * 2 * 3 + 3 * 2 == 48
    assert {c["axes"]["defense_config"] for c in plan if c["arm"] == "matrix"} == set(m.DEFENSE_KEYS)
    by_stratum = {}
    for c in plan:
        by_stratum.setdefault(tuple(c["stratum"]), set()).add(tuple(c["seeds"]))
    assert all(len(v) == 1 for v in by_stratum.values())          # one seed block per stratum
    assert len({next(iter(v)) for v in by_stratum.values()}) == 4  # four disjoint blocks
    vs = [c for c in plan if c["axes"]["defense_config"] == "vendor-shaped"]
    assert len(vs) == 6 and all(c["env"]["W9_JUDGE_PROMPT"] == "scoped" for c in vs)
    assert [c["env"]["W9_L2_RULES"] for c in plan if c["arm"] == "p12_ladder"] == ["1", "1", "2", "2", "3", "3"]
    assert all(c["env"]["W9_L2_RULES"] == "4" for c in plan if c["arm"] == "matrix")
    assert all(c["env"]["W9_ROUTE"] == "agent" for c in plan if "induced" in c["id"])
    assert m.LADDER_RUNGS == (1, 2, 3)


def test_halt_files_are_checked(tmp_path, monkeypatch):
    m = _driver()
    monkeypatch.setattr(m, "HALT_FILES", (tmp_path / "HALT",))
    assert m.halted() is None
    (tmp_path / "HALT").write_text("error rate 9% > 5%")
    assert m.halted() == tmp_path / "HALT"
