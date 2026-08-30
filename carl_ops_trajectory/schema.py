"""carl-ops trajectory record schema — FROZEN corpus format.

Descends from ``halctf.trajectory.v1`` (originally the halctf-agent per-event
JSONL telemetry schema: record types, outcomes, a two-plane concept, and
``validate_record`` / ``validate_jsonl``). This module vendors that v1
event-record schema unchanged and adds the campaign/trial **trajectory
record** the carl-ops sweep freezes.

The schema string is ``saster.trajectory.v1`` — its own identity, not a
halctf-agent version that repo does not ship. Every record also carries a
top-level ``derived_from`` naming its ancestor (``halctf.trajectory.v1``).
This corpus is public and downstream consumers key on the version string, so
the two are kept distinct.

Two record shapes share one validator, dispatched on ``record_type``:

- **event records** — one JSONL line per event on one plane, exactly as v1
  (``run_start``/``model_call``/``step``/…). Unchanged.
- **trajectory records** — one per trial. Structure is run -> campaign ->
  trial; the campaign is the unit of observation and there are k trials per
  ``(campaign, config)`` capturing victim variance. Carries budget, per-turn
  and per-action telemetry, a per-layer detection list, a structurally
  isolated oracle block (snapshot hashes + verdict fields only — the
  independence audit), the five markers, seeded scoring keys, config hashes,
  and the CODE-BLUE-reserved identity/cnf fields.

The semantic rules in the spec are encoded here as validator rejections, not
comments: a malformed record is *rejected*, never silently normalized. The
validator is hand-written and stdlib-only.
"""
from __future__ import annotations

from typing import Any, TypeGuard

SCHEMA_VERSION = "saster.trajectory.v1"

#: The schema this one descends from. This corpus is public and consumers key
#: on the version string, so the record advertises its own identity
#: (SCHEMA_VERSION) and, separately, its ancestry — never claiming to be a
#: halctf-agent version that repo does not ship.
DERIVED_FROM = "halctf.trajectory.v1"

# -- v1 event-record vocabulary (vendored unchanged) ------------------------

RECORD_TYPES = {
    "run_start",
    "runtime_recon",
    "scope_grant",
    "model_call",
    "parse_failure",
    "step",
    "scope_refusal",
    "budget_exhausted",
    "run_end",
    "error",
    # --- v2 extension ---
    "trajectory",  # one trial's trajectory summary (run -> campaign -> trial)
}

PLANES = {"tool", "model"}

OUTCOMES = {
    "dispatched",
    "refused_by_scope",
    "refused_by_model",
    "error",
    "parse_failure",
    "budget_exhausted",
    "ok",
}

REFUSAL_TYPES = {"hard_refusal", "hedge", "partial_compliance", "deflection"}

#: How to read ``timestamp_utc``. A logical clock emits monotonic tokens
#: (``t0``, ``t1``, …) for reproducibility; a wall clock emits real time.
#: This is required so the first external consumer of the public corpus does
#: not parse a logical ``t0`` as ISO 8601. There is no default — the producer
#: must state which clock it used.
CLOCK_KINDS = {"logical", "wall"}

_CORE_REQUIRED = (
    "schema_version",
    "record_type",
    "run_id",
    "challenge_id",
    "step_index",
    "timestamp_utc",
    "clock",
    "plane",
    "outcome",
)

# -- trajectory-record vocabulary -------------------------------------------

#: Terminal outcome classes. There is deliberately NO generic
#: ``budget_exhausted`` class: a held defense that ran out the clock and a
#: stalled analyzer that ran out the clock are different observations
#: (spec: "budget.exhausted alone conflates a held defense with a stalled
#: analyzer"). Refusal tarpit, a provider content filter, and a sanctioned
#: escalation are each their own class, none pooled into breach.
TERMINAL_OUTCOMES = {
    "resolved",                          # objective completed, sanctioned
    "escalated",                         # agent stopped and escalated under an
                                         # unmeetable precondition — the
                                         # sanctioned response; not a failure,
                                         # not a completion
    "breach",                            # an invariant was violated
    "refusal_tarpit",                    # agent stuck refusing — its own class
    "filtered_or_empty",                 # a provider content filter dropped or
                                         # blanked a turn — distinct from any
                                         # failure class
    "defense_held_budget_exhausted",     # budget out, defense held
    "analyzer_stalled_budget_exhausted", # budget out, analyzer stalled
    "error",
}

#: Whether this sweep estimated trajectory onset — a CLOSED enum, required on
#: every trajectory record's ``markers`` block (AMENDMENT 2; see
#: ``docs/schema-amendments.md``).
#:
#: ``not_estimated`` says no estimator ran, so ``onset_dist`` is null; this is
#: a property of the sweep, uniform across its trajectories, and it applies to
#: a breach exactly as it applies to a clean run. ``estimated`` says an
#: estimator ran and owes a distribution. The field exists so a null onset
#: cannot be read two ways: "not measured" and "measured, found none" are
#: different claims and the corpus must keep them apart.
ONSET_STATUSES = {"estimated", "not_estimated"}

#: Whether ``envelope_mass.scored`` holds a measurement — a CLOSED enum
#: (AMENDMENT 3; see ``docs/schema-amendments.md``). ``scored`` was specified
#: as a number and every producer emitted a hardcoded 1.0, because the softmax
#: denominator is the closed candidate set and sums to 1 whatever the model
#: does. The status separates "we measured the accounted-for mass" from "this
#: method cannot measure it", so a constant can no longer validate as data.
#: The field is OPTIONAL: when it is absent the pre-amendment rule applies and
#: ``scored`` must be a number, so records written before the amendment stay
#: valid and absence cannot be used to smuggle a null through.
SCORED_STATUSES = {"computed", "not_computed"}

#: Policy-engine verdict vocabulary — a CLOSED enum. CVR is computed by
#: counting ``deny``, so a drifting verdict vocabulary would silently deflate
#: that headline. ``unavailable`` is the engine's own down/absent state and
#: must never validate as, or aggregate with, ``allow`` — the same rule the
#: detector layer applies to an unavailable detector.
POLICY_VERDICTS = {"allow", "deny", "error", "unavailable"}

#: Which mechanism, if any, widened a bucket toward external readability on
#: this trajectory — a REQUIRED field on every trajectory record. P3-refined
#: predicts CVR differs between the routes for reasons unrelated to
#: composition: the ``grant`` route includes an out-of-namespace bucket grant,
#: which L2's R3 denies (prohibition #4), so it shows CVR>0; the ``firewall``
#: route widens by an in-network firewall path only, which no per-action rule
#: flags, so it shows CVR=0. CVR is therefore not interpretable without this
#: field — a record that does not say which route it ran is not analyzable.
#: ``none`` is a trajectory that widened no bucket (e.g. the legitimate
#: completion or an escalation).
WIDENING_ROUTES = {"grant", "firewall", "none"}

_BUDGET_EXHAUSTED_OUTCOMES = {
    "defense_held_budget_exhausted",
    "analyzer_stalled_budget_exhausted",
}

DETECTION_ACTIONS = {"warn", "block", "escalate"}
DETECTION_STATUSES = {"ok", "unavailable"}

_UNAVAILABLE_SEVERITY = "unavailable"


def _is_str(v: Any) -> TypeGuard[str]:
    return isinstance(v, str)


def _is_num(v: Any) -> TypeGuard[float]:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _is_int(v: Any) -> TypeGuard[int]:
    return isinstance(v, int) and not isinstance(v, bool)


def _err(errors: list, path: str, msg: str) -> None:
    errors.append(f"{path}: {msg}")


# ---------------------------------------------------------------------------
# v1 event-record validation (behavior preserved)
# ---------------------------------------------------------------------------


def _validate_action(action: Any, errors: list) -> None:
    if action is None:
        return
    if not isinstance(action, dict):
        _err(errors, "action", "must be object or null")
        return
    if not _is_str(action.get("tool")):
        _err(errors, "action.tool", "required string")
    if not isinstance(action.get("arguments"), dict):
        _err(errors, "action.arguments", "required object")
    target = action.get("target", None)
    if target is not None and not _is_str(target):
        _err(errors, "action.target", "must be string or null")


def _validate_observation(obs: Any, errors: list) -> None:
    if obs is None:
        return
    if not isinstance(obs, dict):
        _err(errors, "observation", "must be object or null")
        return
    if "content" not in obs:
        _err(errors, "observation.content", "required")
    if not isinstance(obs.get("truncated"), bool):
        _err(errors, "observation.truncated", "required bool")
    ol = obs.get("original_length", None)
    if ol is not None and not isinstance(ol, int):
        _err(errors, "observation.original_length", "must be int or null")


def _validate_model(model: Any, errors: list) -> None:
    if model is None:
        return
    if not isinstance(model, dict):
        _err(errors, "model", "must be object or null")
        return
    if not _is_str(model.get("backend")):
        _err(errors, "model.backend", "required string")
    if not _is_str(model.get("name")):
        _err(errors, "model.name", "required string")
    if not isinstance(model.get("params"), dict):
        _err(errors, "model.params", "required object")
    for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
        v = model.get(k, None)
        if v is not None and not isinstance(v, int):
            _err(errors, f"model.{k}", "must be int or null")
    lat = model.get("latency_ms", None)
    if lat is not None and not isinstance(lat, (int, float)):
        _err(errors, "model.latency_ms", "must be number or null")


def _validate_refusal(ref: Any, errors: list) -> None:
    if ref is None:
        return
    if not isinstance(ref, dict):
        _err(errors, "refusal", "must be object or null")
        return
    if ref.get("refusal_type") not in REFUSAL_TYPES:
        _err(errors, "refusal.refusal_type", f"must be one of {sorted(REFUSAL_TYPES)}")
    conf = ref.get("confidence")
    if not isinstance(conf, (int, float)) or not (0.0 <= float(conf) <= 1.0):
        _err(errors, "refusal.confidence", "must be number in [0,1]")
    if not _is_str(ref.get("span", "")):
        _err(errors, "refusal.span", "must be string")


def _validate_event_record(rec: dict, errors: list) -> None:
    for key in _CORE_REQUIRED:
        if key not in rec:
            _err(errors, key, "required")

    if rec.get("plane") not in PLANES:
        _err(errors, "plane", f"must be one of {sorted(PLANES)}")
    if rec.get("outcome") not in OUTCOMES:
        _err(errors, "outcome", f"must be one of {sorted(OUTCOMES)}")
    if not _is_str(rec.get("run_id")):
        _err(errors, "run_id", "required string")
    if not _is_str(rec.get("challenge_id")):
        _err(errors, "challenge_id", "required string")
    if not _is_int(rec.get("step_index")):
        _err(errors, "step_index", "required int")
    elif rec["step_index"] < 0:
        _err(errors, "step_index", "must be >= 0")
    if not _is_str(rec.get("timestamp_utc")):
        _err(errors, "timestamp_utc", "required string")
    if rec.get("clock") not in CLOCK_KINDS:
        _err(errors, "clock", f"must be one of {sorted(CLOCK_KINDS)}")

    di = rec.get("declared_intent")
    if di is not None and not _is_str(di):
        _err(errors, "declared_intent", "must be string or null")

    _validate_action(rec.get("action"), errors)
    _validate_observation(rec.get("observation"), errors)
    _validate_model(rec.get("model"), errors)
    _validate_refusal(rec.get("refusal"), errors)

    err = rec.get("error")
    if err is not None:
        if not isinstance(err, dict):
            _err(errors, "error", "must be object or null")
        else:
            if not _is_str(err.get("type", "")):
                _err(errors, "error.type", "must be string")
            if not _is_str(err.get("message", "")):
                _err(errors, "error.message", "must be string")


# ---------------------------------------------------------------------------
# trajectory-record validation
# ---------------------------------------------------------------------------

_TRAJ_INLINE_FORBIDDEN = ("prompt", "response")  # content addressing: refs only

_TRAJ_REQUIRED = (
    "run_id",
    "campaign_id",
    "trial_index",
    "timestamp_utc",
    "budget",
    "turns",
    "actions",
    "detection",
    "detection_complete",
    "oracle",
    "markers",
    "containment_latency",
    "terminal_outcome",
    "widening_route",
    "identity",
    "cnf",
    "saster_category",
    "observed_categories",
    "config_hashes",
)


def _validate_budget(budget: Any, errors: list) -> None:
    if not isinstance(budget, dict):
        _err(errors, "budget", "required object")
        return
    for k in ("cap", "consumed", "stalls", "repeats"):
        v = budget.get(k, None)
        if not _is_int(v) or v < 0:
            _err(errors, f"budget.{k}", "required int >= 0")


def _validate_scored(em: dict, path: str, errors: list) -> None:
    """AMENDMENT 3 — ``scored_status`` governs ``scored`` nullability.

    Mirrors the ``onset_status`` / ``onset_dist`` rule. ``scored_status`` is
    optional; when it is missing or outside the vocabulary the pre-amendment
    rule applies unchanged (``scored`` must be a number), so pre-amendment
    records keep validating and a missing status is not a back door for
    carrying a null.
    """
    status = em.get("scored_status")
    if status is None and "scored_status" not in em:
        if not _is_num(em.get("scored")):
            _err(errors, f"{path}.scored", "required number")
        return
    if status not in SCORED_STATUSES:
        _err(errors, f"{path}.scored_status", f"must be one of {sorted(SCORED_STATUSES)}")
        # Fall back to the pre-amendment rule rather than letting an
        # unrecognized status excuse the field.
        if not _is_num(em.get("scored")):
            _err(errors, f"{path}.scored", "required number")
        return
    scored = em.get("scored")
    if status == "computed":
        if not _is_num(scored):
            _err(errors, f"{path}.scored",
                 "required number when scored_status is 'computed'")
        elif not (0.0 <= float(scored) <= 1.0):
            _err(errors, f"{path}.scored", "must be in [0,1]")
    elif scored is not None:
        _err(errors, f"{path}.scored",
             "must be null when scored_status is 'not_computed'")


def _validate_turns(turns: Any, errors: list) -> None:
    if not isinstance(turns, list):
        _err(errors, "turns", "required array")
        return
    for i, turn in enumerate(turns):
        p = f"turns[{i}]"
        if not isinstance(turn, dict):
            _err(errors, p, "must be object")
            continue
        rp = turn.get("refusal_prob", None)
        if not _is_num(rp) or not (0.0 <= float(rp) <= 1.0):
            _err(errors, f"{p}.refusal_prob", "required number in [0,1]")
        em = turn.get("envelope_mass", None)
        if not isinstance(em, dict):
            _err(errors, f"{p}.envelope_mass", "required object")
        else:
            for k in ("declared_in", "declared_out", "prohibition_out"):
                if not _is_num(em.get(k, None)):
                    _err(errors, f"{p}.envelope_mass.{k}", "required number")
            _validate_scored(em, f"{p}.envelope_mass", errors)
        # content addressing — refs, never inline
        for k in _TRAJ_INLINE_FORBIDDEN:
            if k in turn:
                _err(errors, f"{p}.{k}", "inline content forbidden; use a *_ref")
        for k in ("prompt_ref", "response_ref"):
            if not _is_str(turn.get(k, None)):
                _err(errors, f"{p}.{k}", "required string ref")


def _validate_actions(actions: Any, errors: list) -> None:
    if not isinstance(actions, list):
        _err(errors, "actions", "required array")
        return
    for i, act in enumerate(actions):
        p = f"actions[{i}]"
        if not isinstance(act, dict):
            _err(errors, p, "must be object")
            continue
        # policy_verdict is a closed enum: allow | deny | error | unavailable.
        # CVR counts `deny`; a drifting vocabulary would deflate it silently,
        # and `unavailable` must never pass as `allow`.
        if act.get("policy_verdict", None) not in POLICY_VERDICTS:
            _err(
                errors,
                f"{p}.policy_verdict",
                f"must be one of {sorted(POLICY_VERDICTS)}",
            )
        # rule_id is optional engine-specific detail beside the verdict.
        rid = act.get("rule_id", None)
        if rid is not None and not _is_str(rid):
            _err(errors, f"{p}.rule_id", "must be string or null")
        # surprisal is -log P(action | prefix) in nats, and so is non-negative.
        surprisal = act.get("surprisal", None)
        if not _is_num(surprisal):
            _err(errors, f"{p}.surprisal", "required number (-log P in nats)")
        elif float(surprisal) < 0.0:
            _err(
                errors,
                f"{p}.surprisal",
                "must be >= 0 (-log P(action | prefix) in nats)",
            )
        for k in _TRAJ_INLINE_FORBIDDEN:
            if k in act:
                _err(errors, f"{p}.{k}", "inline content forbidden; use a *_ref")


def _validate_detection(detection: Any, detection_complete: Any, errors: list) -> bool:
    """Validate the per-layer detection list. Returns whether any layer is
    unavailable (used by later cross-field checks)."""
    any_unavailable = False
    if not isinstance(detection, list):
        _err(errors, "detection", "required array")
        return any_unavailable
    for i, d in enumerate(detection):
        p = f"detection[{i}]"
        if not isinstance(d, dict):
            _err(errors, p, "must be object")
            continue
        if not _is_str(d.get("layer", None)):
            _err(errors, f"{p}.layer", "required string")
        status = d.get("status", "ok")
        if status not in DETECTION_STATUSES:
            _err(errors, f"{p}.status", f"must be one of {sorted(DETECTION_STATUSES)}")
        si = d.get("step_index", None)
        if not _is_int(si) or si < 0:
            _err(errors, f"{p}.step_index", "required int >= 0")
        if status == "unavailable":
            any_unavailable = True
            # An unavailable detector must be recorded AS unavailable; it may
            # never be encoded as a clean/no-severity, action-taken entry that
            # would read as "layer ran and found nothing".
            if d.get("severity", None) != _UNAVAILABLE_SEVERITY:
                _err(
                    errors,
                    f"{p}.severity",
                    "unavailable layer must have severity 'unavailable', "
                    "not a clean severity",
                )
            if d.get("action_taken", None) is not None:
                _err(
                    errors,
                    f"{p}.action_taken",
                    "unavailable layer cannot have taken an action; must be null",
                )
        else:
            if not _is_str(d.get("severity", None)):
                _err(errors, f"{p}.severity", "required string")
            if d.get("action_taken", None) not in DETECTION_ACTIONS:
                _err(
                    errors,
                    f"{p}.action_taken",
                    f"must be one of {sorted(DETECTION_ACTIONS)}",
                )

    # A detector reporting unavailable must never collapse to clean: the
    # record cannot claim complete detection coverage when a layer is down.
    if not isinstance(detection_complete, bool):
        _err(errors, "detection_complete", "required bool")
    elif any_unavailable and detection_complete:
        _err(
            errors,
            "detection_complete",
            "must be false when any detection layer is unavailable "
            "(an unavailable detector must not collapse to clean)",
        )
    return any_unavailable


def _validate_step_index_field(value: Any, path: str, errors: list) -> None:
    """A breach-style step index: null, or an int >= 1. Never 0 — index 0 is
    t0, the pre-action baseline, which cannot itself be the breach."""
    if value is None:
        return
    if not _is_int(value):
        _err(errors, path, "must be int or null")
    elif value == 0:
        _err(errors, path, "must not be 0 (index 0 is t0; null means none)")
    elif value < 0:
        _err(errors, path, "must be >= 1 or null")


def _validate_ponr_field(value: Any, path: str, errors: list) -> None:
    """point_of_no_return: null, 0, or an int >= 1. Unlike a breach index, 0 is
    a LEGAL and meaningful value here, distinct from null and opposite in
    meaning:

      null = the objective remained completable throughout the trajectory;
      0    = the objective was never completable — foreclosed at t0 (e.g. an
             obstructed run where the sanctioned completion is unavailable
             from the outset).

    Confusing one for the other inverts the recoverability claim, so both are
    accepted but they are never interchangeable."""
    if value is None:
        return
    if not _is_int(value):
        _err(errors, path, "must be int (>= 0) or null")
    elif value < 0:
        _err(errors, path, "must be >= 0 or null (0 = never completable; null = completable throughout)")


def _validate_oracle(oracle: Any, errors: list) -> tuple[bool | None, Any]:
    """Oracle block — the independence audit. Carries snapshot hashes and the
    verdict fields ONLY. It must NOT carry invariant reasons or any state
    content; those are structurally excluded so this block can be diffed
    across policy configs without leaking what the invariants inspected.

    Returns (breach, breach_step_index) for cross-field checks."""
    if not isinstance(oracle, dict):
        _err(errors, "oracle", "required object")
        return None, None

    # Structural independence: reject anything that would smuggle state
    # content or invariant rationale into the audit block.
    for forbidden in ("reasons", "reason", "state", "state_content", "snapshots"):
        if forbidden in oracle:
            _err(
                errors,
                f"oracle.{forbidden}",
                "forbidden: oracle block carries hashes and verdict fields "
                "only, never invariant reasons or state content",
            )

    hashes = oracle.get("snapshot_hashes", None)
    if not isinstance(hashes, list) or not hashes:
        _err(errors, "oracle.snapshot_hashes", "required non-empty array of hashes")
    else:
        for j, h in enumerate(hashes):
            if not _is_str(h):
                _err(errors, f"oracle.snapshot_hashes[{j}]", "must be string hash")

    breach = oracle.get("breach", None)
    if not isinstance(breach, bool):
        _err(errors, "oracle.breach", "required bool")
        breach = None

    bsi = oracle.get("breach_step_index", "__missing__")
    if bsi == "__missing__":
        _err(errors, "oracle.breach_step_index", "required (int or null)")
        bsi = None
    else:
        _validate_step_index_field(bsi, "oracle.breach_step_index", errors)

    # breach <-> breach_step_index consistency: a breach has a step, a clean
    # run has none. (null is not 0 is enforced above.)
    if breach is True and bsi is None:
        _err(errors, "oracle.breach_step_index", "breach is true but index is null")
    if breach is False and bsi is not None:
        _err(errors, "oracle.breach_step_index", "breach is false but index is set")

    inv = oracle.get("invariant", "__missing__")
    if inv == "__missing__":
        _err(errors, "oracle.invariant", "required (string or null)")
    elif inv is not None and not _is_str(inv):
        _err(errors, "oracle.invariant", "must be string or null")

    fired = oracle.get("invariants_fired", None)
    if not isinstance(fired, list):
        _err(errors, "oracle.invariants_fired", "required array")
    else:
        for j, f in enumerate(fired):
            if not _is_str(f):
                _err(errors, f"oracle.invariants_fired[{j}]", "must be string")
    # primary invariant, when set, must be among those that fired
    if _is_str(inv) and isinstance(fired, list) and inv not in fired:
        _err(errors, "oracle.invariant", "primary invariant not in invariants_fired")

    _validate_first_firing(oracle.get("first_firing_step_index", None), fired, bsi, errors)

    return breach, bsi


def _validate_first_firing(
    mapping: Any, fired: Any, bsi: Any, errors: list
) -> None:
    """``oracle.first_firing_step_index`` — invariant id -> earliest snapshot
    index at which that invariant fired (AMENDMENT 5; see
    ``docs/schema-amendments.md``).

    Why it exists. ``invariants_fired`` is a flat list with no snapshot
    association, and before AMENDMENT 5 the oracle returned at the first
    failing snapshot, so the list was that ONE snapshot's set: an invariant
    whose first firing came later was absent from the record entirely. On the
    W7g compromised runs the block said ``I3`` at step 2 and never mentioned
    ``I1`` at step 3 — credential material reaching an object store, the
    fixture's headline compositional result, missing from its own oracle
    output on every run that produced it. It was not recoverable either:
    snapshot hashes are one-way and state content is structurally excluded.

    The block's exclusions are UNCHANGED and still enforced above. An
    invariant id plus an integer index leaks nothing the block does not
    already carry — the ids are already in ``invariants_fired``, the indices
    are already in the same space as ``breach_step_index``, and no reason
    string or state content comes with them.

    OPTIONAL, on the AMENDMENT 3 pattern. Records written before the field
    existed — the W6c pilot's — carry an oracle block without it and stay
    valid under the contract they were written to. Absence is not a back
    door: when the field IS present every rule below applies.

    Rules:

    - object mapping invariant id (string) -> step index (int >= 1);
    - never 0, for the same reason ``breach_step_index`` is never 0: a firing
      at t0 is a rigged fixture, not a breach;
    - its key set is EXACTLY ``invariants_fired`` — the two are one fact in
      two shapes, and a record where they disagree is not analyzable;
    - ``min(values) == breach_step_index``, which is what makes the earliest
      firing and the breach index the same claim rather than two;
    - on a clean run (``breach_step_index`` null) it must be empty.
    """
    if mapping is None:
        return  # absent: pre-amendment record, rule above applies unchanged
    p = "oracle.first_firing_step_index"
    if not isinstance(mapping, dict):
        _err(errors, p, "must be an object mapping invariant id to step index")
        return
    for key, value in sorted(mapping.items(), key=lambda kv: str(kv[0])):
        if not _is_str(key):
            _err(errors, f"{p}.{key}", "key must be an invariant id string")
            continue
        if not _is_int(value):
            _err(errors, f"{p}.{key}", "must be int")
        elif value == 0:
            _err(errors, f"{p}.{key}", "must not be 0 (index 0 is t0)")
        elif value < 0:
            _err(errors, f"{p}.{key}", "must be >= 1")

    if (
        isinstance(fired, list)
        and all(_is_str(f) for f in fired)
        and set(mapping) != set(fired)
    ):
        _err(errors, p, "key set must equal invariants_fired")

    values = [v for v in mapping.values() if _is_int(v) and v >= 1]
    if bsi is None:
        if mapping:
            _err(errors, p, "must be empty when breach_step_index is null")
    elif values and min(values) != bsi:
        _err(errors, p, "earliest first-firing index must equal breach_step_index")


def _validate_onset_dist(
    onset: Any, breach: Any, onset_status: Any, errors: list
) -> None:
    """onset_dist is a DISTRIBUTION, not a point estimate. A bare integer is
    rejected — onset is uncertain and must be carried as such.

    Nullability is governed by ``markers.onset_status`` (AMENDMENT 2; see
    ``docs/schema-amendments.md``). The original rule was "a null onset is
    legal only when breach is false", which assumed a breach can always
    localize an onset. It cannot: onset is *inferred*, not observed, and a
    sweep may decline to estimate it — that is a statement about the
    estimator, not about the trajectory. Under the amendment:

    - ``not_estimated`` — onset_dist MUST be null, on a breach or otherwise.
      The sweep did not estimate onset for any trajectory.
    - ``estimated`` — onset_dist MUST be a well-formed distribution. An
      estimator ran, so it owes a distribution.

    The two are never interchangeable: ``not_estimated`` with a null onset
    means "we did not measure", while ``estimated`` with a distribution
    localizing nothing would mean "we measured and found none". Collapsing
    them to a bare nullable onset would lose exactly that distinction, so the
    amendment adds a status rather than relaxing the null rule."""
    if onset is None:
        if onset_status == "estimated":
            _err(
                errors,
                "markers.onset_dist",
                "onset_status is 'estimated' but onset_dist is null; an "
                "estimated onset must carry a distribution",
            )
        # Status missing or out of vocabulary (reported against onset_status
        # itself): fall back to the pre-amendment rule, so omitting the field
        # cannot become a back door for a null onset on a breach.
        elif onset_status != "not_estimated" and breach is True:
            _err(
                errors,
                "markers.onset_dist",
                "null onset on a breach requires onset_status 'not_estimated'",
            )
        return
    if onset_status == "not_estimated":
        _err(
            errors,
            "markers.onset_dist",
            "onset_status is 'not_estimated' but onset_dist is set; a "
            "not-estimated onset must be null",
        )
        return
    if isinstance(onset, (int, float)):  # bool included (bool subclasses int)
        _err(errors, "markers.onset_dist", "must be a distribution object, not a scalar")
        return
    if not isinstance(onset, dict):
        _err(errors, "markers.onset_dist", "required distribution object or null")
        return
    steps = onset.get("steps", None)
    probs = onset.get("probs", None)
    if not isinstance(steps, list) or not steps:
        _err(errors, "markers.onset_dist.steps", "required non-empty array of int")
        steps = []
    if not isinstance(probs, list) or not probs:
        _err(errors, "markers.onset_dist.probs", "required non-empty array of number")
        probs = []
    if steps and probs and len(steps) != len(probs):
        _err(errors, "markers.onset_dist", "steps and probs must be equal length")
    for j, s in enumerate(steps):
        if not _is_int(s) or s < 0:
            _err(errors, f"markers.onset_dist.steps[{j}]", "must be int >= 0")
    for j, pr in enumerate(probs):
        if not _is_num(pr) or not (0.0 <= float(pr) <= 1.0):
            _err(errors, f"markers.onset_dist.probs[{j}]", "must be number in [0,1]")
    if probs and all(_is_num(pr) for pr in probs):
        total = float(sum(probs))
        if abs(total - 1.0) > 1e-6:
            _err(errors, "markers.onset_dist.probs", "must sum to 1.0")


def _validate_markers(markers: Any, oracle_bsi: Any, breach: Any, errors: list) -> Any:
    """Validate the five markers. Returns markers.first_detection_step for
    cross-field latency checks."""
    if not isinstance(markers, dict):
        _err(errors, "markers", "required object")
        return None

    onset_status = markers.get("onset_status", "__missing__")
    if onset_status == "__missing__":
        _err(
            errors,
            "markers.onset_status",
            f"required; must be one of {sorted(ONSET_STATUSES)}",
        )
        onset_status = None
    elif onset_status not in ONSET_STATUSES:
        _err(
            errors,
            "markers.onset_status",
            f"must be one of {sorted(ONSET_STATUSES)}",
        )
        onset_status = None

    if "onset_dist" not in markers:
        _err(errors, "markers.onset_dist", "required (distribution object or null)")
    else:
        _validate_onset_dist(markers["onset_dist"], breach, onset_status, errors)

    ed = markers.get("explanatory_divergence", "__missing__")
    if ed == "__missing__":
        _err(errors, "markers.explanatory_divergence", "required (number or null)")
    elif ed is not None and not _is_num(ed):
        _err(errors, "markers.explanatory_divergence", "must be number or null")

    ponr = markers.get("point_of_no_return", "__missing__")
    if ponr == "__missing__":
        _err(errors, "markers.point_of_no_return", "required (int >= 0 or null)")
    else:
        _validate_ponr_field(ponr, "markers.point_of_no_return", errors)

    if "breach_step_index" not in markers:
        _err(errors, "markers.breach_step_index", "required (int or null)")
    else:
        m_bsi = markers["breach_step_index"]
        _validate_step_index_field(m_bsi, "markers.breach_step_index", errors)
        # single source of truth: the marker must mirror the oracle verdict.
        if m_bsi != oracle_bsi:
            _err(
                errors,
                "markers.breach_step_index",
                "must equal oracle.breach_step_index",
            )

    fds = markers.get("first_detection_step", "__missing__")
    if fds == "__missing__":
        _err(errors, "markers.first_detection_step", "required (int or null)")
        fds = None
    elif fds is not None and (not _is_int(fds) or fds < 0):
        _err(errors, "markers.first_detection_step", "must be int >= 0 or null")
        fds = None
    return fds


def _validate_containment_latency(
    latency: Any, breach: Any, first_detection_step: Any, errors: list
) -> None:
    """Containment latency is right-censored when a breach occurs with no
    detection. A censored latency must be carried as such — never substituted
    with a large sentinel number."""
    if not isinstance(latency, dict):
        _err(errors, "containment_latency", "required object")
        return
    value = latency.get("value", "__missing__")
    censored = latency.get("censored", None)
    if not isinstance(censored, bool):
        _err(errors, "containment_latency.censored", "required bool")
    if value == "__missing__":
        _err(errors, "containment_latency.value", "required (int or null)")
        return
    if value is not None and not _is_int(value):
        _err(errors, "containment_latency.value", "must be int or null")

    if breach is True and first_detection_step is None:
        # Right-censored: breach happened, nothing detected it.
        if censored is not True:
            _err(
                errors,
                "containment_latency.censored",
                "must be true when breach occurs with no detection "
                "(latency is right-censored)",
            )
        if value is not None:
            _err(
                errors,
                "containment_latency.value",
                "must be null when censored; never substitute a number for a "
                "censored latency",
            )
    elif breach is True and first_detection_step is not None:
        if censored is not False:
            _err(errors, "containment_latency.censored", "must be false when breach was detected")
        if not _is_int(value):
            _err(errors, "containment_latency.value", "required int when breach was detected")
    elif breach is False:
        if censored is not False:
            _err(errors, "containment_latency.censored", "must be false when there is no breach")
        if value is not None:
            _err(errors, "containment_latency.value", "must be null when there is no breach")


def _validate_scoring_and_config(rec: dict, errors: list) -> None:
    if not _is_str(rec.get("saster_category")):
        _err(errors, "saster_category", "required single string (the scoring key)")
    oc = rec.get("observed_categories")
    if not isinstance(oc, list):
        _err(errors, "observed_categories", "required array (diagnostic; not scored)")
    else:
        for j, c in enumerate(oc):
            if not _is_str(c):
                _err(errors, f"observed_categories[{j}]", "must be string")
    ch = rec.get("config_hashes")
    if not isinstance(ch, dict):
        _err(errors, "config_hashes", "required object")
    else:
        for k in ("objective_spec", "tool_surface", "analyzer", "router"):
            if not _is_str(ch.get(k, None)):
                _err(errors, f"config_hashes.{k}", "required string hash")


def _validate_trajectory_record(rec: dict, errors: list) -> None:
    for key in _TRAJ_REQUIRED:
        if key not in rec:
            _err(errors, key, "required")

    if not _is_str(rec.get("run_id")):
        _err(errors, "run_id", "required string")
    if not _is_str(rec.get("campaign_id")):
        _err(errors, "campaign_id", "required string")
    ti = rec.get("trial_index")
    if not _is_int(ti) or ti < 0:
        _err(errors, "trial_index", "required int >= 0")
    if not _is_str(rec.get("timestamp_utc")):
        _err(errors, "timestamp_utc", "required string")

    _validate_budget(rec.get("budget"), errors)
    _validate_turns(rec.get("turns"), errors)
    _validate_actions(rec.get("actions"), errors)
    _validate_detection(
        rec.get("detection"), rec.get("detection_complete"), errors
    )

    breach, oracle_bsi = _validate_oracle(rec.get("oracle"), errors)
    first_detection_step = _validate_markers(
        rec.get("markers"), oracle_bsi, breach, errors
    )
    _validate_containment_latency(
        rec.get("containment_latency"), breach, first_detection_step, errors
    )

    # identity / cnf — carried from day one, values unused until CODE BLUE.
    # The keys must be present (that is the carrying guarantee); values may be
    # null or object, but not another type that would imply premature use.
    for reserved in ("identity", "cnf"):
        if reserved not in rec:
            _err(errors, reserved, "required (carried from day one; may be null)")
        elif rec[reserved] is not None and not isinstance(rec[reserved], dict):
            _err(errors, reserved, "must be object or null")

    _validate_scoring_and_config(rec, errors)

    # Per-route widening mechanism — required so CVR is interpretable
    # (P3-refined). A record that does not say which route it ran is not
    # analyzable.
    if rec.get("widening_route") not in WIDENING_ROUTES:
        _err(errors, "widening_route", f"must be one of {sorted(WIDENING_ROUTES)}")

    # Terminal outcome classes — the distinctions the spec insists on.
    outcome = rec.get("terminal_outcome")
    if outcome not in TERMINAL_OUTCOMES:
        _err(errors, "terminal_outcome", f"must be one of {sorted(TERMINAL_OUTCOMES)}")
    else:
        # breach <-> terminal outcome: a breach is classified as a breach and
        # nothing else; refusal tarpit and the budget classes are never a
        # breach (refusal tarpit is never pooled into breach rate).
        if outcome == "breach" and breach is False:
            _err(errors, "terminal_outcome", "'breach' requires oracle.breach true")
        if outcome != "breach" and breach is True:
            _err(
                errors,
                "terminal_outcome",
                "oracle.breach is true; terminal_outcome must be 'breach' "
                "(breach is never pooled away into another class)",
            )
        # The two budget-exhausted classes must actually correspond to an
        # exhausted budget — they are not a dumping ground.
        if outcome in _BUDGET_EXHAUSTED_OUTCOMES:
            budget = rec.get("budget")
            if isinstance(budget, dict):
                cap = budget.get("cap")
                consumed = budget.get("consumed")
                if _is_int(cap) and _is_int(consumed) and consumed < cap:
                    _err(
                        errors,
                        "terminal_outcome",
                        "budget-exhausted outcome but budget.consumed < budget.cap",
                    )


# ---------------------------------------------------------------------------
# Public validators (dispatch on record_type; both shapes stay supported)
# ---------------------------------------------------------------------------


def validate_record(rec: Any) -> list[str]:
    """Return a list of validation errors for one record. Empty == valid.

    Dispatches on ``record_type``: ``trajectory`` records use the trajectory
    schema; every other record type uses the vendored event schema."""
    errors: list[str] = []
    if not isinstance(rec, dict):
        return ["record: must be a JSON object"]

    if rec.get("schema_version") != SCHEMA_VERSION:
        _err(errors, "schema_version", f"must equal {SCHEMA_VERSION!r}")
    if rec.get("derived_from") != DERIVED_FROM:
        _err(errors, "derived_from", f"must equal {DERIVED_FROM!r}")
    rt = rec.get("record_type")
    if rt not in RECORD_TYPES:
        _err(errors, "record_type", f"must be one of {sorted(RECORD_TYPES)}")

    if rt == "trajectory":
        _validate_trajectory_record(rec, errors)
    else:
        _validate_event_record(rec, errors)
    return errors


def validate_jsonl(path: str) -> tuple[int, list[str]]:
    """Validate an entire JSONL file end to end.

    Returns (n_records, errors). A blank line or bad JSON is itself an error."""
    import json

    errors: list[str] = []
    n = 0
    with open(path, encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            if line.strip() == "":
                errors.append(f"line {lineno}: blank line (not allowed in JSONL)")
                continue
            n += 1
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append(f"line {lineno}: invalid JSON: {exc}")
                continue
            for e in validate_record(rec):
                errors.append(f"line {lineno}: {e}")
    return n, errors
