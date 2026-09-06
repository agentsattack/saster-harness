"""Class 6 — label validity (catalogue C9).

Any label that CAN be derived from the trajectory MUST be, and the assembler
raises on disagreement: ``widening_route`` from terminal state (already), and
``saster_category`` against the fixture's capability manifest (new). A record
labelled with a category the fixture cannot satisfy is not emitted.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from carl_ops_agent import WideningRouteMismatch
from carl_ops_agent.capabilities import (
    FIXTURE_CAPABILITIES,
    CategoryNotSatisfiable,
    UnknownFixture,
    capabilities_for,
    check_category,
)
from carl_ops_assembly import assemble_trajectory_record
from carl_ops_oracle import evaluate_snapshots
from carl_ops_state import TransitionRelation, apply_path
from carl_ops_state.fixture import divergence_path, initial_state, obstructed_environment

REPO = Path(__file__).resolve().parents[1]


def _assemble(**overrides):
    from carl_ops_agent import derive_widening_route

    rel = TransitionRelation()
    path = divergence_path()
    states = apply_path(rel, initial_state(obstructed_environment()), path).states()
    a2s, idx = [], 0
    for a in path:
        idx += 1 if a.mutating else 0
        a2s.append(idx)
    verdict = evaluate_snapshots([s.to_json() for s in states])
    n = len(path)
    nc = {"declared_in": None, "declared_out": None, "envelope_status": "not_computed",
          "scored": None, "scored_status": "not_computed", "prohibition_out": None}
    terminal = states[-1].to_json()
    kw = dict(
        run_id="c6", campaign_id="c6", trial_index=0, timestamp_utc="2026-09-05T00:00:00Z",
        verdict=verdict, snapshot_hashes=[s.content_hash for s in states],
        turns=[{"refusal_prob": 0.0, "refusal_prob_status": "not_measured",
                "envelope_mass": dict(nc), "prompt_ref": f"sha256:p{i}",
                "response_ref": f"sha256:r{i}"} for i in range(n)],
        actions=[{"step_index": i, "tool": a.name, "args": {}, "policy_verdict": "allow",
                  "surprisal": None, "surprisal_status": "not_computed"}
                 for i, a in enumerate(path)],
        detection=[], detection_complete=True,
        budget={"cap": 100, "consumed": n, "stalls": 0, "repeats": 0},
        envelope_masses=[dict(nc) for _ in range(n)], relation=rel, snapshots=states,
        action_to_snapshot=a2s, terminal_state_json=terminal,
        configured_widening_route=derive_widening_route(terminal),
        runner_outcome="completed", saster_category="SASTER-31", observed_categories=[],
        config_hashes={"objective_spec": "h", "tool_surface": "h", "analyzer": "h", "router": "h"},
        fixture_id="carl-ops",
    )
    kw.update(overrides)
    return assemble_trajectory_record(**kw)


def test_capability_manifest_declares_carl_ops_as_saster_31_only():
    caps = capabilities_for("carl-ops")
    assert caps.satisfiable_categories == ("SASTER-31",)
    assert len(caps.sha256) == 64
    assert caps.sha256 == capabilities_for("carl-ops").sha256  # stable
    with pytest.raises(UnknownFixture):
        capabilities_for("carl-support")


def test_assembler_rejects_a_category_the_fixture_cannot_satisfy():
    with pytest.raises(CategoryNotSatisfiable, match="SASTER-24"):
        _assemble(saster_category="SASTER-24")
    rec = _assemble(saster_category="SASTER-31")
    assert rec["saster_category"] == "SASTER-31"


def test_assembler_without_a_fixture_id_is_unchecked_and_the_loader_is_not():
    """Backwards compatibility for callers that do not name the fixture — but
    the citable loader always names it, so the label cannot enter citable."""
    from carl_ops_trajectory.citable import check_record_citable

    rec = _assemble(saster_category="SASTER-24", fixture_id=None)
    assert rec["saster_category"] == "SASTER-24"
    reasons = check_record_citable(rec, None, "carl-ops")
    assert any("SASTER-24" in r for r in reasons)


def test_assembler_rejects_a_widening_route_that_disagrees_with_terminal_state():
    with pytest.raises(WideningRouteMismatch):
        _assemble(configured_widening_route="none")  # terminal state derives grant


def test_every_existing_corpus_record_carries_the_unsatisfiable_label():
    """Documents W21 (runs/SASTER_CATEGORY_CORRECTION.md) as a check: every
    record written BEFORE the correction (every corpus under runs/ other
    than the Stage 2 w22 cells) says SASTER-24, and the manifest rejects
    every one. Records are evidence and are not revised; they are not
    citable. Records written after W21 carry SASTER-31 and pass."""
    labels: set[str] = set()
    after: set[str] = set()
    n = 0
    for path in (REPO / "runs").rglob("trajectories.jsonl"):
        target = after if path.relative_to(REPO / "runs").parts[0].startswith("w22_") else labels
        for line in path.read_text().splitlines():
            if line.strip():
                target.add(json.loads(line)["saster_category"])
                n += 1
    assert n >= 500
    assert labels == {"SASTER-24"}
    for label in labels:
        with pytest.raises(CategoryNotSatisfiable):
            check_category("carl-ops", label)
    assert after <= {"SASTER-31"}
    for label in after:
        check_category("carl-ops", label)


def test_driver_passes_the_fixture_to_the_assembler_and_records_the_manifest():
    src = (REPO / "scripts" / "run_cell_w9.py").read_text()
    assert 'fixture_id="carl-ops"' in src
    assert "fixture_capabilities" in src
    assert "carl-ops" in FIXTURE_CAPABILITIES
