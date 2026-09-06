"""The citable-corpus gate and the marker-population gate.

A corpus enters corpora/citable/ only through load_citable, which requires
what the optional-field amendments do not: units, the latency-zero flag, a
satisfiable category, no stand-in behind an enabled layer — and, per
breaching campaign, no marker null across ALL trials unless declared
unmeasured.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from carl_ops_markers import MARKER_UNITS
from carl_ops_trajectory.citable import (
    CitableViolation,
    MarkerUnpopulated,
    check_record_citable,
    load_citable,
    marker_population_gate,
)
from tests.test_carl_ops_trajectory import valid_clean_trajectory, valid_trajectory_record

REPO = Path(__file__).resolve().parents[1]


def _citable_breach(trial: int = 0) -> dict:
    rec = valid_trajectory_record()
    rec["trial_index"] = trial
    rec["saster_category"] = "SASTER-31"
    rec["markers"]["units"] = dict(MARKER_UNITS)
    rec["containment_latency"]["detected_at_breach"] = True
    return rec


def _manifest(**layers) -> dict:
    m = {"layers_enabled": {"l1": False, "l2": True, "l3": True, "l4": True, "l5": False},
         "l2": {"backend_status": "real"}, "l3": {"backend_status": "real"},
         "l4": {"backend_status": "real"}}
    m.update(layers)
    return m


def test_a_citable_record_passes():
    assert check_record_citable(_citable_breach(), _manifest(), "carl-ops") == []


def test_each_gate_rejects():
    no_units = _citable_breach()
    del no_units["markers"]["units"]
    assert any("units" in r for r in check_record_citable(no_units, None, "carl-ops"))

    no_flag = _citable_breach()
    del no_flag["containment_latency"]["detected_at_breach"]
    assert any("detected_at_breach" in r for r in check_record_citable(no_flag, None, "carl-ops"))

    wrong_label = _citable_breach()
    wrong_label["saster_category"] = "SASTER-24"
    assert any("SASTER-24" in r for r in check_record_citable(wrong_label, None, "carl-ops"))

    stand_in = _manifest(l4={"backend_status": "stand-in", "stand_in_reason": "no endpoint"})
    assert any("stand-in" in r for r in check_record_citable(_citable_breach(), stand_in, "carl-ops"))
    # a stand-in behind a DISABLED layer does not taint the record
    disabled = _manifest(l1={"backend_status": "stand-in", "stand_in_reason": "no weights"})
    assert check_record_citable(_citable_breach(), disabled, "carl-ops") == []


def test_marker_population_gate():
    a = _citable_breach(0)
    b = _citable_breach(1)
    report = marker_population_gate([a, b])
    assert report["campaigns"][a["campaign_id"]] == {"trials": 2, "breaching": 2}

    # point_of_no_return null on EVERY breaching trial, nothing declares it
    for r in (a, b):
        r["markers"]["point_of_no_return"] = None
        r["index_map"]["snapshot_space_markers"]["point_of_no_return"] = None
    with pytest.raises(MarkerUnpopulated, match="point_of_no_return"):
        marker_population_gate([a, b])

    # null on one trial only: populated on the campaign, passes
    b["markers"]["point_of_no_return"] = 3
    b["index_map"]["snapshot_space_markers"]["point_of_no_return"] = 2
    marker_population_gate([a, b])

    # declared unmeasured: reported, not failed
    for r in (a, b):
        r["markers"]["onset_status"] = "not_estimated"
        r["markers"]["onset_dist"] = None
    report = marker_population_gate([a, b])
    assert report["declared_unmeasured"] == {a["campaign_id"]: ["onset_dist"]}

    # a clean campaign is not gated
    marker_population_gate([valid_clean_trajectory()])


def test_marker_population_gate_accepts_tagged_censored_first_detection():
    """AMENDMENT 19: a campaign whose breaches were never detected carries a
    null first_detection_step tagged censored — that is the measurement, not
    a hole. An untagged null is still rejected, naming the trials."""
    a = _citable_breach(0)
    b = _citable_breach(1)
    for r in (a, b):
        r["markers"]["first_detection_step"] = None
        r["index_map"]["snapshot_space_markers"]["first_detection_step"] = None
        r["containment_latency"] = {"value": None, "censored": True, "detected_at_breach": False}
    report = marker_population_gate([a, b])
    assert report["declared_unmeasured"] == {a["campaign_id"]: ["first_detection_step (censored)"]}

    b["containment_latency"]["censored"] = False
    with pytest.raises(MarkerUnpopulated, match="untagged") as exc:
        marker_population_gate([a, b])
    assert f"{b['campaign_id']}/1" in str(exc.value)
    assert f"{a['campaign_id']}/0" not in str(exc.value)


def test_load_citable_end_to_end(tmp_path):
    path = tmp_path / "trajectories.jsonl"
    man = tmp_path / "manifest.json"
    man.write_text(json.dumps(_manifest()))
    path.write_text("\n".join(json.dumps(_citable_breach(i)) for i in range(3)) + "\n")
    records, report = load_citable(path, man, "carl-ops")
    assert len(records) == 3 and report["n_records"] == 3

    bad = _citable_breach(9)
    bad["saster_category"] = "SASTER-24"
    path.write_text(json.dumps(bad) + "\n")
    with pytest.raises(CitableViolation, match="SASTER-24"):
        load_citable(path, man, "carl-ops")


def test_the_existing_w17_corpus_is_not_citable():
    """The headline corpus fails the gate on the W21 label (and on units).
    Evidence, not revised; a dev corpus under this gate."""
    cell = REPO / "runs/w17_corpus_qwen_paired/cells/matrix__all__obstructed__compromised"
    with pytest.raises(CitableViolation) as exc:
        load_citable(cell / "trajectories.jsonl", cell / "manifest.json", "carl-ops")
    assert any("SASTER-24" in r for r in exc.value.reasons)
    assert any("markers.units" in r for r in exc.value.reasons)


def test_citable_gate_does_not_require_the_negative_control_to_pass():
    """F2 follow-up. A record from a sanctioned completion on which L4 fired
    (breach false, an L4 finding present) is still citable: the gate checks
    the record's own integrity and provenance, never whether a layer behaved
    as predicted. The negative control is a finding about the layer, and it
    is reported, not gated on."""
    rec = valid_clean_trajectory()
    rec["saster_category"] = "SASTER-31"
    rec["markers"]["units"] = dict(MARKER_UNITS)
    rec["detection"] = [{"layer": "l4_auditor", "step_index": 3, "severity": "medium",
                         "action_taken": "warn", "finding": True, "status": "ok"}]
    rec["markers"]["first_detection_step"] = 3
    assert check_record_citable(rec, _manifest(), "carl-ops") == []
    marker_population_gate([rec])
