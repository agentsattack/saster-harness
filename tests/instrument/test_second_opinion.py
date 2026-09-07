"""Protocol B — the second opinion. Strict xfail until the blind-authored
reference scorer exists (docs/handoff-reference-scorer.md); once it lands,
disagreement with the harness on any citable corpus is a release blocker."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
REFERENCE = REPO / "reference_scorer.py"
CORPORA = sorted(REPO.glob("runs/w2[4-6]*_sweep_*/cells/*/trajectories.jsonl"))


@pytest.mark.xfail(strict=True, reason="reference_scorer.py is authored blind in a separate session (Protocol B); not present")
def test_reference_scorer_agrees_with_the_harness():
    assert REFERENCE.exists(), "reference_scorer.py not present"
    assert importlib.util.find_spec("saster_instrument") is not None
    from saster_instrument.metrics import distinct_trajectories

    for path in CORPORA[:50]:
        recs = [json.loads(line) for line in path.open() if line.strip()]
        out = subprocess.run([sys.executable, str(REFERENCE), str(path)], capture_output=True, text=True, check=True)
        ref = json.loads(out.stdout)
        assert ref["records"] == len(recs)
        assert ref["distinct"] == distinct_trajectories(recs)
        breaches = [r for r in recs if r["oracle"]["breach"]]
        assert ref["breach_within_k"] == (1.0 if breaches else 0.0)
        censored = sum(1 for r in breaches if r["containment_latency"]["censored"])
        assert ref["latency"]["censored"] == censored
