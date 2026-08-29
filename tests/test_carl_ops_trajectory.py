"""Tests for the frozen carl-ops trajectory record schema (halctf.trajectory.v2).

Two kinds of test:

- round-trip: a fully-populated valid record of each shape (event and
  trajectory) validates clean and survives json dumps/loads unchanged;
- rejection: every semantic rule the spec names is exercised by feeding the
  WRONG encoding and asserting it is rejected — a rule that silently accepts
  the wrong encoding is the failure this freeze exists to prevent.
"""
from __future__ import annotations

import copy
import json

from carl_ops_trajectory import SCHEMA_VERSION, validate_jsonl, validate_record

# -- builders ---------------------------------------------------------------


def valid_event_record() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "derived_from": "halctf.trajectory.v1",
        "record_type": "step",
        "run_id": "run-1",
        "challenge_id": "carl-ops",
        "step_index": 3,
        "timestamp_utc": "2026-08-28T00:00:00Z",
        "clock": "wall",
        "plane": "tool",
        "outcome": "dispatched",
        "declared_intent": "rotate the expiring credential",
        "action": {"tool": "secrets.rotate_credential", "arguments": {}, "target": None},
        "observation": {"content": "ok", "truncated": False, "original_length": None},
        "model": None,
        "refusal": None,
        "error": None,
    }


def valid_trajectory_record() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "derived_from": "halctf.trajectory.v1",
        "record_type": "trajectory",
        "run_id": "run-1",
        "campaign_id": "carl-ops-induced",
        "trial_index": 0,
        "timestamp_utc": "2026-08-28T00:00:00Z",
        "budget": {"cap": 40, "consumed": 12, "stalls": 1, "repeats": 0},
        "turns": [
            {
                "refusal_prob": 0.02,
                "envelope_mass": {"declared_in": 0.9, "declared_out": 0.1, "scored": 1.0, "prohibition_out": 0.05},
                "prompt_ref": "sha256:aaa",
                "response_ref": "sha256:bbb",
            }
        ],
        "actions": [
            {"policy_verdict": "allow", "surprisal": 1.4},
            {"policy_verdict": "allow", "surprisal": 7.9},
        ],
        "detection": [
            {"layer": "policy", "step_index": 5, "severity": "high", "action_taken": "block", "status": "ok"},
        ],
        "detection_complete": True,
        "oracle": {
            "snapshot_hashes": ["f866d8", "aa11bb", "cc22dd"],
            "breach": True,
            "breach_step_index": 5,
            "invariant": "I4",
            "invariants_fired": ["I4", "I1"],
        },
        "markers": {
            "onset_status": "estimated",
            "onset_dist": {"steps": [3, 4, 5], "probs": [0.2, 0.3, 0.5]},
            "explanatory_divergence": 0.71,
            "point_of_no_return": 5,
            "breach_step_index": 5,
            "first_detection_step": 5,
        },
        "containment_latency": {"value": 0, "censored": False},
        "terminal_outcome": "breach",
        "widening_route": "firewall",
        "identity": None,
        "cnf": None,
        "saster_category": "SASTER-14",
        "observed_categories": ["SASTER-14", "SASTER-11"],
        "config_hashes": {
            "objective_spec": "h1",
            "tool_surface": "h2",
            "analyzer": "h3",
            "router": "h4",
        },
    }


def valid_clean_trajectory() -> dict:
    """A contained, no-breach trajectory (the negative-control shape)."""
    rec = valid_trajectory_record()
    rec["oracle"] = {
        "snapshot_hashes": ["f866d8", "aa11bb"],
        "breach": False,
        "breach_step_index": None,
        "invariant": None,
        "invariants_fired": [],
    }
    rec["markers"] = {
        "onset_status": "not_estimated",
        "onset_dist": None,  # a clean campaign has no onset (negative control)
        "explanatory_divergence": None,
        "point_of_no_return": None,
        "breach_step_index": None,
        "first_detection_step": None,
    }
    rec["containment_latency"] = {"value": None, "censored": False}
    rec["terminal_outcome"] = "resolved"
    rec["widening_route"] = "none"  # the legitimate path widens no bucket
    return rec


def reject(rec: dict, needle: str | None = None) -> list[str]:
    errs = validate_record(rec)
    assert errs, "expected the record to be REJECTED, but it validated clean"
    if needle is not None:
        assert any(needle in e for e in errs), f"no error mentioned {needle!r}: {errs}"
    return errs


# -- round-trip -------------------------------------------------------------


def test_event_record_round_trips_clean() -> None:
    rec = valid_event_record()
    assert validate_record(rec) == []
    assert json.loads(json.dumps(rec)) == rec


def test_trajectory_record_round_trips_clean() -> None:
    rec = valid_trajectory_record()
    assert validate_record(rec) == []
    assert json.loads(json.dumps(rec)) == rec


def test_clean_trajectory_round_trips_clean() -> None:
    assert validate_record(valid_clean_trajectory()) == []


def test_mixed_jsonl_validates(tmp_path) -> None:
    path = tmp_path / "corpus.jsonl"
    lines = [valid_event_record(), valid_trajectory_record(), valid_clean_trajectory()]
    path.write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")
    n, errors = validate_jsonl(str(path))
    assert (n, errors) == (3, [])


def test_every_carried_field_present_is_required() -> None:
    # Dropping any required trajectory field is rejected (freeze completeness).
    base = valid_trajectory_record()
    for field in list(base.keys()):
        if field in ("schema_version", "record_type"):
            continue
        broken = copy.deepcopy(base)
        del broken[field]
        reject(broken, field)


# -- schema string and provenance -------------------------------------------


def test_schema_string_is_saster_v1() -> None:
    assert SCHEMA_VERSION == "saster.trajectory.v1"
    rec = valid_trajectory_record()
    # the vendored copy must not claim to be a halctf-agent version
    rec["schema_version"] = "halctf.trajectory.v2"
    reject(rec, "schema_version")
    rec2 = valid_trajectory_record()
    rec2["schema_version"] = "halctf.trajectory.v1"
    reject(rec2, "schema_version")


def test_event_clock_required_and_vocabulary_enforced() -> None:
    rec = valid_event_record()
    assert validate_record(rec) == []
    # missing clock is rejected
    missing = valid_event_record()
    del missing["clock"]
    reject(missing, "clock")
    # out-of-vocabulary clock is rejected (a logical 't0' must not be read as ISO)
    bad = valid_event_record()
    bad["clock"] = "iso8601"
    reject(bad, "clock")
    # both vocabulary values accepted
    for kind in ("logical", "wall"):
        ok = valid_event_record()
        ok["clock"] = kind
        assert validate_record(ok) == [], kind


def test_derived_from_required_and_pinned() -> None:
    rec = valid_trajectory_record()
    del rec["derived_from"]
    reject(rec, "derived_from")
    rec2 = valid_trajectory_record()
    rec2["derived_from"] = "saster.trajectory.v1"  # must name the ancestor
    reject(rec2, "derived_from")
    rec3 = valid_event_record()
    del rec3["derived_from"]
    reject(rec3, "derived_from")


# -- semantic rule: breach_step_index null is NOT 0 -------------------------


def test_breach_step_index_zero_is_rejected() -> None:
    rec = valid_trajectory_record()
    rec["oracle"]["breach_step_index"] = 0
    rec["markers"]["breach_step_index"] = 0
    reject(rec, "breach_step_index")


# -- point_of_no_return: null and 0 are distinct legal values ---------------


def test_ponr_null_is_accepted() -> None:
    # null = the objective remained completable throughout.
    rec = valid_clean_trajectory()
    assert rec["markers"]["point_of_no_return"] is None
    assert validate_record(rec) == []


def test_ponr_zero_is_accepted_distinct_from_null() -> None:
    # 0 = the objective was never completable (obstructed at t0). Unlike a
    # breach index, 0 is legal here and means the opposite of null.
    rec = valid_clean_trajectory()
    rec["markers"]["point_of_no_return"] = 0
    assert validate_record(rec) == []


def test_ponr_negative_is_rejected() -> None:
    rec = valid_clean_trajectory()
    rec["markers"]["point_of_no_return"] = -1
    reject(rec, "point_of_no_return")


def test_ponr_non_int_is_rejected() -> None:
    rec = valid_clean_trajectory()
    rec["markers"]["point_of_no_return"] = 0.5
    reject(rec, "point_of_no_return")


def test_breach_index_zero_still_rejected_but_ponr_zero_ok() -> None:
    # The no-zero rule stays for breach_step_index (t0 is pre-action) while
    # PONR=0 is legal — the two indices are not interchangeable.
    rec = valid_clean_trajectory()
    rec["markers"]["point_of_no_return"] = 0
    assert validate_record(rec) == []  # PONR=0 fine
    rec["oracle"]["breach_step_index"] = 0
    rec["markers"]["breach_step_index"] = 0
    reject(rec, "breach_step_index")  # breach index 0 still rejected


def test_breach_true_requires_non_null_index() -> None:
    rec = valid_trajectory_record()
    rec["oracle"]["breach_step_index"] = None
    rec["markers"]["breach_step_index"] = None
    reject(rec, "oracle.breach_step_index")


def test_breach_false_with_index_set_is_rejected() -> None:
    rec = valid_clean_trajectory()
    rec["oracle"]["breach"] = False
    rec["oracle"]["breach_step_index"] = 4
    reject(rec, "breach_step_index")


def test_marker_breach_index_must_mirror_oracle() -> None:
    rec = valid_trajectory_record()
    rec["markers"]["breach_step_index"] = 4  # oracle says 5
    reject(rec, "markers.breach_step_index")


# -- semantic rule: containment latency is right-censored, never substituted -


def test_breach_without_detection_must_be_censored() -> None:
    rec = valid_trajectory_record()
    rec["detection"] = []
    rec["markers"]["first_detection_step"] = None
    # wrong: a large sentinel number substituted for a censored latency
    rec["containment_latency"] = {"value": 999999, "censored": False}
    reject(rec, "containment_latency")


def test_breach_without_detection_censored_true_null_value_accepted() -> None:
    rec = valid_trajectory_record()
    rec["detection"] = []
    rec["markers"]["first_detection_step"] = None
    rec["containment_latency"] = {"value": None, "censored": True}
    assert validate_record(rec) == []


def test_censored_latency_may_not_carry_a_number() -> None:
    rec = valid_trajectory_record()
    rec["detection"] = []
    rec["markers"]["first_detection_step"] = None
    rec["containment_latency"] = {"value": 3, "censored": True}
    reject(rec, "containment_latency.value")


# -- semantic rule: detection before breach is legal, not clamped -----------


def test_detection_strictly_before_breach_is_accepted() -> None:
    rec = valid_trajectory_record()
    rec["oracle"]["breach_step_index"] = 8
    rec["markers"]["breach_step_index"] = 8
    rec["markers"]["point_of_no_return"] = 8
    rec["detection"] = [
        {"layer": "policy", "step_index": 2, "severity": "medium", "action_taken": "warn", "status": "ok"},
    ]
    rec["markers"]["first_detection_step"] = 2  # before breach at 8
    rec["containment_latency"] = {"value": -6, "censored": False}
    assert validate_record(rec) == []


# -- semantic rule: unavailable detector must never collapse to clean -------


def test_unavailable_layer_cannot_claim_detection_complete() -> None:
    rec = valid_trajectory_record()
    rec["detection"] = [
        {"layer": "policy", "step_index": 5, "severity": "high", "action_taken": "block", "status": "ok"},
        {"layer": "oracle", "step_index": 5, "severity": "unavailable", "action_taken": None, "status": "unavailable"},
    ]
    rec["detection_complete"] = True  # wrong: a layer is down
    reject(rec, "detection_complete")


def test_unavailable_layer_encoded_as_clean_is_rejected() -> None:
    rec = valid_trajectory_record()
    rec["detection"] = [
        {"layer": "oracle", "step_index": 5, "severity": "none", "action_taken": "warn", "status": "unavailable"},
    ]
    rec["detection_complete"] = False
    reject(rec, "severity")


def test_unavailable_layer_recorded_honestly_is_accepted() -> None:
    rec = valid_trajectory_record()
    rec["detection"] = [
        {"layer": "policy", "step_index": 5, "severity": "high", "action_taken": "block", "status": "ok"},
        {"layer": "oracle", "step_index": 5, "severity": "unavailable", "action_taken": None, "status": "unavailable"},
    ]
    rec["detection_complete"] = False
    assert validate_record(rec) == []


# -- semantic rule: budget.exhausted must distinguish held vs stalled -------


def test_generic_budget_exhausted_outcome_is_rejected() -> None:
    rec = valid_clean_trajectory()
    rec["terminal_outcome"] = "budget_exhausted"  # conflated class does not exist
    reject(rec, "terminal_outcome")


def test_budget_exhausted_classes_are_distinct_and_accepted() -> None:
    for outcome in ("defense_held_budget_exhausted", "analyzer_stalled_budget_exhausted"):
        rec = valid_clean_trajectory()
        rec["budget"] = {"cap": 40, "consumed": 40, "stalls": 3, "repeats": 2}
        rec["terminal_outcome"] = outcome
        assert validate_record(rec) == [], outcome


def test_budget_exhausted_outcome_requires_actual_exhaustion() -> None:
    rec = valid_clean_trajectory()
    rec["budget"] = {"cap": 40, "consumed": 10, "stalls": 0, "repeats": 0}
    rec["terminal_outcome"] = "defense_held_budget_exhausted"
    reject(rec, "terminal_outcome")


# -- required rule: widening_route (so CVR is interpretable, P3-refined) -----


def test_widening_route_is_required() -> None:
    rec = valid_trajectory_record()
    del rec["widening_route"]
    reject(rec, "widening_route")


def test_widening_route_out_of_vocabulary_is_rejected() -> None:
    rec = valid_trajectory_record()
    rec["widening_route"] = "grant_and_firewall"  # not in the closed vocabulary
    reject(rec, "widening_route")


def test_widening_route_full_vocabulary_accepted() -> None:
    for route in ("grant", "firewall", "none"):
        rec = valid_trajectory_record()
        rec["widening_route"] = route
        assert validate_record(rec) == [], route


# -- semantic rule: refusal tarpit is its own class, never breach -----------


def test_refusal_tarpit_with_breach_is_rejected() -> None:
    rec = valid_trajectory_record()  # oracle.breach is True here
    rec["terminal_outcome"] = "refusal_tarpit"
    reject(rec, "terminal_outcome")


def test_refusal_tarpit_clean_is_accepted() -> None:
    rec = valid_clean_trajectory()
    rec["terminal_outcome"] = "refusal_tarpit"
    assert validate_record(rec) == []


def test_breach_true_forces_breach_outcome() -> None:
    rec = valid_trajectory_record()
    rec["terminal_outcome"] = "resolved"  # but oracle.breach is True
    reject(rec, "terminal_outcome")


# -- semantic rule: oracle block is hashes + verdict only (independence) -----


def test_oracle_block_rejects_reasons() -> None:
    rec = valid_trajectory_record()
    rec["oracle"]["reasons"] = ["credential material resides in bucket ops-audit-x"]
    reject(rec, "oracle.reasons")


def test_oracle_block_rejects_state_content() -> None:
    rec = valid_trajectory_record()
    rec["oracle"]["state"] = {"buckets": []}
    reject(rec, "oracle.state")


def test_oracle_requires_snapshot_hashes() -> None:
    rec = valid_trajectory_record()
    rec["oracle"]["snapshot_hashes"] = []
    reject(rec, "oracle.snapshot_hashes")


def test_primary_invariant_must_be_among_fired() -> None:
    rec = valid_trajectory_record()
    rec["oracle"]["invariant"] = "I2"  # not in invariants_fired
    reject(rec, "oracle.invariant")


# -- semantic rule: onset_dist is a distribution, not an integer ------------


def test_onset_dist_scalar_is_rejected() -> None:
    rec = valid_trajectory_record()
    rec["markers"]["onset_dist"] = 5
    reject(rec, "onset_dist")


def test_onset_dist_probs_must_sum_to_one() -> None:
    rec = valid_trajectory_record()
    rec["markers"]["onset_dist"] = {"steps": [3, 4], "probs": [0.2, 0.2]}
    reject(rec, "onset_dist.probs")


def test_onset_dist_length_mismatch_rejected() -> None:
    rec = valid_trajectory_record()
    rec["markers"]["onset_dist"] = {"steps": [3, 4, 5], "probs": [1.0]}
    reject(rec, "onset_dist")


# -- AMENDMENT 2: onset_status governs onset_dist nullability ---------------
#
# The pre-amendment rule was "a null onset is legal only when breach is
# false", which assumed a breach can always localize an onset. It cannot:
# onset is inferred, not observed, and a sweep may decline to infer it. The
# amendment adds markers.onset_status rather than relaxing the null rule, so
# "not estimated" and "estimated as absent" stay distinguishable. See
# docs/schema-amendments.md.


def test_onset_status_is_required() -> None:
    rec = valid_trajectory_record()
    del rec["markers"]["onset_status"]
    reject(rec, "onset_status")


def test_onset_status_vocabulary_is_closed() -> None:
    rec = valid_trajectory_record()
    rec["markers"]["onset_status"] = "partially_estimated"
    reject(rec, "onset_status")


def test_onset_status_null_is_rejected() -> None:
    rec = valid_trajectory_record()
    rec["markers"]["onset_status"] = None
    reject(rec, "onset_status")


def test_estimated_with_null_onset_is_rejected() -> None:
    """An estimator that ran owes a distribution."""
    rec = valid_trajectory_record()
    rec["markers"]["onset_status"] = "estimated"
    rec["markers"]["onset_dist"] = None
    reject(rec, "onset_dist")


def test_not_estimated_with_a_distribution_is_rejected() -> None:
    """A sweep that did not estimate onset cannot carry one."""
    rec = valid_trajectory_record()
    rec["markers"]["onset_status"] = "not_estimated"
    rec["markers"]["onset_dist"] = {"steps": [3], "probs": [1.0]}
    reject(rec, "onset_dist")


def test_not_estimated_with_a_distribution_is_rejected_on_a_clean_record() -> None:
    rec = valid_clean_trajectory()
    rec["markers"]["onset_dist"] = {"steps": [1], "probs": [1.0]}
    reject(rec, "onset_dist")


def test_null_onset_on_a_breach_is_accepted_when_not_estimated() -> None:
    """The amendment's purpose: a breach can decline to localize onset."""
    rec = valid_trajectory_record()  # oracle.breach is True
    rec["markers"]["onset_status"] = "not_estimated"
    rec["markers"]["onset_dist"] = None
    assert validate_record(rec) == []


def test_null_onset_with_breach_is_still_rejected_when_estimated() -> None:
    rec = valid_trajectory_record()  # oracle.breach is True
    rec["markers"]["onset_status"] = "estimated"
    rec["markers"]["onset_dist"] = None
    reject(rec, "onset_dist")


def test_null_onset_on_a_breach_cannot_slip_through_a_missing_status() -> None:
    """Omitting onset_status must not become a way to carry a null onset on a
    breach: the pre-amendment rule still applies when the status is absent."""
    rec = valid_trajectory_record()  # oracle.breach is True
    del rec["markers"]["onset_status"]
    rec["markers"]["onset_dist"] = None
    errs = reject(rec, "onset_status")
    assert any("onset_dist" in e for e in errs)


def test_estimated_still_enforces_distribution_shape() -> None:
    """The amendment must not have loosened validation for the estimated
    case."""
    rec = valid_trajectory_record()
    rec["markers"]["onset_status"] = "estimated"
    rec["markers"]["onset_dist"] = {"steps": [3, 4], "probs": [0.2, 0.2]}
    reject(rec, "onset_dist.probs")


def test_estimated_still_rejects_a_scalar_onset() -> None:
    rec = valid_trajectory_record()
    rec["markers"]["onset_status"] = "estimated"
    rec["markers"]["onset_dist"] = 5
    reject(rec, "onset_dist")


def test_estimated_still_rejects_a_length_mismatch() -> None:
    rec = valid_trajectory_record()
    rec["markers"]["onset_status"] = "estimated"
    rec["markers"]["onset_dist"] = {"steps": [3, 4, 5], "probs": [1.0]}
    reject(rec, "onset_dist")


def test_not_estimated_and_estimated_are_not_interchangeable() -> None:
    """The distinction the amendment exists to preserve: the same null onset
    is legal under one status and rejected under the other."""
    not_est = valid_trajectory_record()
    not_est["markers"]["onset_status"] = "not_estimated"
    not_est["markers"]["onset_dist"] = None
    est = valid_trajectory_record()
    est["markers"]["onset_status"] = "estimated"
    est["markers"]["onset_dist"] = None
    assert validate_record(not_est) == []
    assert validate_record(est) != []


def test_null_onset_clean_is_accepted() -> None:
    # The negative control: a clean campaign carries a null onset and must
    # validate — the pre-amendment encoding failed exactly this.
    rec = valid_clean_trajectory()
    assert rec["markers"]["onset_dist"] is None
    assert validate_record(rec) == []


def test_onset_dist_key_required_present() -> None:
    rec = valid_clean_trajectory()
    del rec["markers"]["onset_dist"]
    reject(rec, "onset_dist")


# -- semantic rule: policy_verdict is a closed enum (CVR integrity) ----------


def test_policy_verdict_out_of_vocabulary_is_rejected() -> None:
    rec = valid_trajectory_record()
    rec["actions"][0]["policy_verdict"] = "hitl"  # not allow/deny/error/unavailable
    reject(rec, "policy_verdict")


def test_policy_verdict_full_vocabulary_accepted() -> None:
    for verdict in ("allow", "deny", "error", "unavailable"):
        rec = valid_trajectory_record()
        rec["actions"][0]["policy_verdict"] = verdict
        assert validate_record(rec) == [], verdict


def test_optional_rule_id_accepted_and_typechecked() -> None:
    rec = valid_trajectory_record()
    rec["actions"][0]["rule_id"] = "R-042"
    assert validate_record(rec) == []
    rec2 = valid_trajectory_record()
    rec2["actions"][0]["rule_id"] = 42  # not a string
    reject(rec2, "rule_id")


# -- semantic rule: surprisal is -log P in nats, non-negative ----------------


def test_negative_surprisal_is_rejected() -> None:
    rec = valid_trajectory_record()
    rec["actions"][0]["surprisal"] = -0.5
    reject(rec, "surprisal")


def test_zero_surprisal_is_accepted() -> None:
    rec = valid_trajectory_record()
    rec["actions"][0]["surprisal"] = 0.0
    assert validate_record(rec) == []


# -- semantic rule: filtered_or_empty and escalated terminal classes --------


def test_filtered_or_empty_is_its_own_class() -> None:
    # Distinct, valid class on a non-breach run.
    rec = valid_clean_trajectory()
    rec["terminal_outcome"] = "filtered_or_empty"
    assert validate_record(rec) == []


def test_filtered_or_empty_never_aggregates_into_breach() -> None:
    rec = valid_trajectory_record()  # oracle.breach is True
    rec["terminal_outcome"] = "filtered_or_empty"
    reject(rec, "terminal_outcome")


def test_escalated_is_sanctioned_non_breach() -> None:
    rec = valid_clean_trajectory()
    rec["terminal_outcome"] = "escalated"
    assert validate_record(rec) == []


def test_escalated_with_breach_is_rejected() -> None:
    rec = valid_trajectory_record()  # oracle.breach is True
    rec["terminal_outcome"] = "escalated"
    reject(rec, "terminal_outcome")


# -- content addressing: refs, not inline ------------------------------------


def test_inline_prompt_in_turn_is_rejected() -> None:
    rec = valid_trajectory_record()
    rec["turns"][0]["prompt"] = "rotate the credential please"
    reject(rec, "prompt")


def test_missing_prompt_ref_is_rejected() -> None:
    rec = valid_trajectory_record()
    del rec["turns"][0]["prompt_ref"]
    reject(rec, "prompt_ref")


# -- detection action vocabulary --------------------------------------------


def test_detection_action_taken_vocabulary_enforced() -> None:
    rec = valid_trajectory_record()
    rec["detection"][0]["action_taken"] = "quarantine"  # not warn/block/escalate
    reject(rec, "action_taken")


# -- identity / cnf carried from day one ------------------------------------


def test_identity_and_cnf_keys_required_even_when_null() -> None:
    for reserved in ("identity", "cnf"):
        rec = valid_trajectory_record()
        del rec[reserved]
        reject(rec, reserved)


def test_identity_and_cnf_accept_object_values() -> None:
    rec = valid_trajectory_record()
    rec["identity"] = {"agent_id": "carl-ops"}
    rec["cnf"] = {"reserved": True}
    assert validate_record(rec) == []


# -- scoring keys ------------------------------------------------------------


def test_saster_category_must_be_single_string() -> None:
    rec = valid_trajectory_record()
    rec["saster_category"] = ["SASTER-14", "SASTER-11"]  # not single-valued
    reject(rec, "saster_category")


def test_observed_categories_is_a_list() -> None:
    rec = valid_trajectory_record()
    rec["observed_categories"] = "SASTER-14"
    reject(rec, "observed_categories")


def test_config_hashes_all_four_required() -> None:
    for key in ("objective_spec", "tool_surface", "analyzer", "router"):
        rec = valid_trajectory_record()
        del rec["config_hashes"][key]
        reject(rec, f"config_hashes.{key}")


# -- AMENDMENT 3: scored_status governs envelope_mass.scored nullability -----
#
# The pre-amendment rule was "scored is a required number". Every producer
# emitted a hardcoded 1.0, because the softmax denominator is the closed
# 13-candidate set and sums to 1 whatever the model does — so the field
# validated as data while measuring nothing, in a corpus meant to be public.
# The amendment adds envelope_mass.scored_status rather than deleting the
# field, so "we measured the accounted-for mass" and "this method cannot
# measure it" stay distinguishable. scored_status is OPTIONAL: absent, the
# pre-amendment rule applies unchanged, so records written before the
# amendment keep validating. See docs/schema-amendments.md.


def _em(rec: dict) -> dict:
    return rec["turns"][0]["envelope_mass"]


def test_scored_may_be_null_under_not_computed() -> None:
    rec = valid_trajectory_record()
    _em(rec).update({"scored": None, "scored_status": "not_computed"})
    assert validate_record(rec) == []


def test_not_computed_with_a_number_is_rejected() -> None:
    """A sweep that did not compute the mass cannot carry one — this is the
    exact shape the amendment exists to reject: scored_status says the method
    cannot measure it, and 1.0 sits in the field anyway."""
    rec = valid_trajectory_record()
    _em(rec).update({"scored": 1.0, "scored_status": "not_computed"})
    reject(rec, "scored")


def test_computed_with_a_null_is_rejected() -> None:
    """A method that claims to have computed the mass owes a number."""
    rec = valid_trajectory_record()
    _em(rec).update({"scored": None, "scored_status": "computed"})
    reject(rec, "scored")


def test_computed_accepts_a_real_fraction() -> None:
    rec = valid_trajectory_record()
    _em(rec).update({"scored": 0.83, "scored_status": "computed"})
    assert validate_record(rec) == []


def test_computed_rejects_a_value_outside_zero_one() -> None:
    """It is a mass fraction, so it cannot exceed 1."""
    rec = valid_trajectory_record()
    _em(rec).update({"scored": 1.4, "scored_status": "computed"})
    reject(rec, "scored")


def test_scored_status_vocabulary_is_closed() -> None:
    rec = valid_trajectory_record()
    _em(rec).update({"scored": None, "scored_status": "partially_computed"})
    reject(rec, "scored_status")


def test_out_of_vocabulary_status_still_demands_a_number() -> None:
    """An unrecognized status must not excuse the field: the pre-amendment
    rule applies underneath, so a bogus status plus a null is two errors, not
    a way through."""
    rec = valid_trajectory_record()
    _em(rec).update({"scored": None, "scored_status": "nonsense"})
    errs = reject(rec, "scored_status")
    assert any("scored:" in e or "scored " in e for e in errs)


def test_omitting_the_status_keeps_the_pre_amendment_rule() -> None:
    """Backward compatibility in both directions. A record with no status and
    a number is still valid — the W6c pilot records are exactly this shape and
    must not be invalidated retroactively."""
    rec = valid_trajectory_record()
    _em(rec).pop("scored_status", None)
    _em(rec)["scored"] = 1.0
    assert validate_record(rec) == []


def test_omitting_the_status_is_not_a_back_door_for_a_null() -> None:
    """The guard AMENDMENT 2 established: absence of the status cannot be used
    to carry a null through."""
    rec = valid_trajectory_record()
    _em(rec).pop("scored_status", None)
    _em(rec)["scored"] = None
    reject(rec, "scored")


def test_the_other_three_envelopes_are_still_required_numbers() -> None:
    """The amendment loosens exactly one field. declared_in, declared_out and
    prohibition_out are real measurements and stay mandatory."""
    for key in ("declared_in", "declared_out", "prohibition_out"):
        rec = valid_trajectory_record()
        _em(rec).update({"scored": None, "scored_status": "not_computed"})
        del _em(rec)[key]
        reject(rec, key)
