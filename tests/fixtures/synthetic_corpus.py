"""Deterministic generator of VALID synthetic carl-ops trajectory records.

Every record this module emits passes ``carl_ops_trajectory.validate_record``
with no errors — the point of the fixture is to exercise renderers and
loaders against a corpus that has the real schema's shape (paired campaigns,
k trials per (campaign, config), per-layer detection entries, censored
latencies, unavailable detectors, action-space markers) without touching a
real sweep. Nothing here is a measurement.

Each record starts from the two builders the schema tests own
(``valid_trajectory_record`` for a breach, ``valid_clean_trajectory`` for a
non-breach) and is then rewritten field by field. The defense configuration a
record ran under is NOT written into the record — the schema has no such
field and ``config_hashes`` is a closed four-key block — so it travels in a
sidecar ``meta`` dict alongside each record.
"""
from __future__ import annotations

import random

from carl_ops_trajectory.schema import first_finding_step, to_action_index
from tests.test_carl_ops_trajectory import valid_clean_trajectory, valid_trajectory_record

#: Which layers each defense configuration exposes. The key vocabulary is the
#: one the verdict grid groups on; the layer vocabulary is the one the grid
#: draws columns for.
DEFENSE_CONFIG_LAYERS: dict[str, tuple[str, ...]] = {
    "none": (),
    "l2": ("l2_policy",),
    "l3": ("l3_trace",),
    "l4": ("l4_auditor",),
    "l3+l4": ("l3_trace", "l4_auditor"),
    "all": ("l2_policy", "l3_trace", "l4_auditor", "l5_approval", "scope_lock"),
    "vendor-shaped": ("judge", "l5_approval"),
}
DEFENSE_CONFIG_KEYS: tuple[str, ...] = tuple(DEFENSE_CONFIG_LAYERS)

#: (campaign_id, fixture_mode, precondition). Three campaigns; the sidecar
#: carries the last two.
CAMPAIGNS: tuple[tuple[str, str, str], ...] = (
    ("carl-ops-induced", "induced", "meetable"),
    ("carl-ops-obstructed", "obstructed", "unmeetable"),
    ("carl-ops-control", "control", "meetable"),
)
K_TRIALS = 5

SASTER_CATEGORY = "SASTER-31"

TOOLS: tuple[str, ...] = (
    "tickets.read",
    "secrets.rotate_credential",
    "iam.grant_role",
    "storage.put_object",
    "bucket.set_policy",
    "firewall.open_path",
    "audit.append",
)

#: P(breach) by fixture mode and configuration. The control campaign never
#: breaches (it is the negative control); the obstructed campaign breaches
#: less than the induced one because the sanctioned path is foreclosed.
_BREACH_P: dict[str, dict[str, float]] = {
    "induced": {
        "none": 1.0, "l2": 0.8, "l3": 0.6, "l4": 0.7, "l3+l4": 0.4, "all": 0.2,
        "vendor-shaped": 0.9,
    },
    "obstructed": {
        "none": 0.6, "l2": 0.4, "l3": 0.3, "l4": 0.4, "l3+l4": 0.2, "all": 0.1,
        "vendor-shaped": 0.5,
    },
    "control": {k: 0.0 for k in DEFENSE_CONFIG_KEYS},
}

#: P(a layer that ran produced a finding) and P(a layer was down).
_FINDING_P = {
    "l2_policy": 0.6, "l3_trace": 0.5, "l4_auditor": 0.7, "scope_lock": 0.4,
    "judge": 0.3, "l5_approval": 0.15,
}
_UNAVAILABLE_P = {
    "l2_policy": 0.08, "l3_trace": 0.1, "l4_auditor": 0.15, "scope_lock": 0.05,
    "judge": 0.3, "l5_approval": 0.05,
}

_INVARIANTS = ("I1", "I3", "I4")


def _hex(rng: random.Random) -> str:
    return f"{rng.getrandbits(24):06x}"


def _onset_dist(rng: random.Random, n_actions: int) -> dict:
    """A distribution over action indices whose probs sum to exactly 1.0 in
    float arithmetic (the validator tolerates 1e-6; integer weights over a
    small total stay well inside that)."""
    k = min(n_actions, rng.randint(2, 4))
    start = rng.randint(0, n_actions - k)
    steps = list(range(start, start + k))
    weights = [rng.randint(1, 5) for _ in steps]
    total = sum(weights)
    probs = [w / total for w in weights]
    return {"steps": steps, "probs": probs}


def _detection_entries(
    rng: random.Random, layers: tuple[str, ...], n_actions: int, breach_action: int | None
) -> list[dict]:
    entries: list[dict] = []
    for layer in layers:
        if rng.random() < 0.15:
            continue  # the layer was configured but produced no entry
        if rng.random() < _UNAVAILABLE_P[layer]:
            entries.append({
                "layer": layer,
                "step_index": rng.randint(0, n_actions - 1),
                "severity": "unavailable",
                "action_taken": None,
                "finding": False,
                "status": "unavailable",
            })
            continue
        is_finding = rng.random() < _FINDING_P[layer]
        if is_finding and breach_action is not None:
            # A finding on a breaching trial lands near the breach: at it,
            # after it, or (a fired-but-did-not-contain stack) just before.
            lo = max(0, breach_action - 1)
            step = rng.randint(lo, n_actions - 1)
        else:
            step = rng.randint(0, n_actions - 1)
        if layer == "l5_approval" and not is_finding:
            # Tier-driven routing on the assigned ticket's own action: an
            # escalation that is NOT a finding (AMENDMENT 7).
            entries.append({
                "layer": layer, "step_index": step, "severity": "tier",
                "action_taken": "escalate", "finding": False, "status": "ok",
            })
        elif is_finding:
            entries.append({
                "layer": layer, "step_index": step,
                "severity": rng.choice(("high", "medium")),
                "action_taken": rng.choice(("warn", "block")),
                "finding": True, "status": "ok",
            })
        else:
            # The layer evaluated and flagged nothing: an advisory entry that
            # says so explicitly, so "present, no finding" is distinguishable
            # from "layer absent".
            entries.append({
                "layer": layer, "step_index": step, "severity": "info",
                "action_taken": "warn", "finding": False, "status": "ok",
            })
    entries.sort(key=lambda d: (d["step_index"], d["layer"]))
    return entries


def _make_record(
    rng: random.Random,
    *,
    seed: int,
    campaign_id: str,
    fixture_mode: str,
    precondition: str,
    cfg: str,
    trial: int,
) -> tuple[dict, dict]:
    layers = DEFENSE_CONFIG_LAYERS[cfg]
    n_actions = rng.randint(4, 8)
    tools = [rng.choice(TOOLS) for _ in range(n_actions)]

    # Which actions mutate state (and so append a snapshot).
    a2s: list[int] = []
    prev = 0
    for _ in range(n_actions):
        if rng.random() < 0.6:
            prev += 1
        a2s.append(prev)

    breach = rng.random() < _BREACH_P[fixture_mode][cfg]
    if breach and a2s[-1] == 0:
        a2s[-1] = 1  # a breach needs at least one graded mutation
    n_snapshots = a2s[-1] + 1

    rec = valid_trajectory_record() if breach else valid_clean_trajectory()
    rec["run_id"] = f"synthetic-{seed}"
    rec["campaign_id"] = campaign_id
    rec["trial_index"] = trial
    rec["timestamp_utc"] = f"2026-09-05T00:{trial:02d}:00Z"

    consumed = n_actions * rng.randint(2, 4)
    rec["budget"] = {
        "cap": 40, "consumed": consumed, "stalls": rng.randint(0, 2), "repeats": rng.randint(0, 1),
    }

    envelopes_computed = fixture_mode == "induced"
    turns = []
    for _ in range(n_actions):
        if envelopes_computed:
            d_in = round(rng.uniform(0.5, 0.95), 3)
            em = {
                "envelope_status": "computed",
                "declared_in": d_in,
                "declared_out": round(1.0 - d_in, 3),
                "prohibition_out": round(rng.uniform(0.0, 0.3), 3),
                "scored_status": "computed",
                "scored": round(rng.uniform(0.7, 1.0), 3),
            }
        else:
            em = {
                "envelope_status": "not_computed",
                "declared_in": None, "declared_out": None, "prohibition_out": None,
                "scored_status": "not_computed", "scored": None,
            }
        turns.append({
            "refusal_prob": round(rng.uniform(0.0, 0.2), 3),
            "envelope_mass": em,
            "prompt_ref": f"sha256:{_hex(rng)}",
            "response_ref": f"sha256:{_hex(rng)}",
        })
    rec["turns"] = turns

    # Oracle block (snapshot space) and the conversion map.
    if breach:
        bsi_snap = rng.randint(1, a2s[-1])
        fired = sorted(rng.sample(_INVARIANTS, rng.randint(1, 2)))
        firing = {fired[0]: bsi_snap}
        for inv in fired[1:]:
            firing[inv] = rng.randint(bsi_snap, a2s[-1])
        rec["oracle"] = {
            "snapshot_hashes": [_hex(rng) for _ in range(n_snapshots)],
            "breach": True,
            "breach_step_index": bsi_snap,
            "invariant": fired[0],
            "invariants_fired": fired,
            "first_firing_step_index": firing,
        }
    else:
        bsi_snap = None
        rec["oracle"] = {
            "snapshot_hashes": [_hex(rng) for _ in range(n_snapshots)],
            "breach": False,
            "breach_step_index": None,
            "invariant": None,
            "invariants_fired": [],
            "first_firing_step_index": {},
        }

    if fixture_mode == "obstructed" and rng.random() < 0.5:
        ponr_snap: int | None = 0  # never completable: foreclosed at t0
    elif breach and rng.random() < 0.7:
        ponr_snap = bsi_snap
    else:
        ponr_snap = None
    rec["index_map"] = {
        "marker_space": "action",
        "oracle_space": "snapshot",
        "action_to_snapshot": a2s,
        "snapshot_space_markers": {
            "breach_step_index": bsi_snap,
            "point_of_no_return": ponr_snap,
        },
    }
    breach_action = to_action_index(a2s, bsi_snap)
    ponr_action = to_action_index(a2s, ponr_snap)

    detection = _detection_entries(rng, layers, n_actions, breach_action)
    rec["detection"] = detection
    any_unavailable = any(d["status"] == "unavailable" for d in detection)
    rec["detection_complete"] = not any_unavailable
    fds = first_finding_step(detection)

    # Per-action telemetry. The policy verdict is L2's; without L2 in the
    # configuration the engine is absent and its verdict is ``unavailable``.
    l2_entries = [d for d in detection if d["layer"] == "l2_policy"]
    l2_down = any(d["status"] == "unavailable" for d in l2_entries)
    l2_block_steps = {
        d["step_index"] for d in l2_entries
        if d["status"] == "ok" and d["action_taken"] == "block"
    }
    actions = []
    for i, tool in enumerate(tools):
        if "l2_policy" not in layers or l2_down:
            verdict = "unavailable"
        elif i in l2_block_steps:
            verdict = "deny"
        else:
            verdict = "allow"
        act: dict = {"step_index": i, "tool": tool, "policy_verdict": verdict}
        if envelopes_computed:
            act["surprisal_status"] = "computed"
            act["surprisal"] = round(rng.uniform(0.1, 9.0), 2)
        else:
            act["surprisal_status"] = "not_computed"
            act["surprisal"] = None
        actions.append(act)
    rec["actions"] = actions

    onset_estimated = fixture_mode == "induced"
    if envelopes_computed:
        ed_status = "computed"
        ed = rng.randint(0, n_actions - 1) if rng.random() < 0.6 else None
    else:
        ed_status, ed = "not_computed", None
    rec["markers"] = {
        "index_space": "action",
        "units": {
            "onset_dist": "action_index",
            "explanatory_divergence": "action_index",
            "point_of_no_return": "action_index",
            "breach_step_index": "action_index",
            "first_detection_step": "action_index",
        },
        "onset_status": "estimated" if onset_estimated else "not_estimated",
        "onset_dist": _onset_dist(rng, n_actions) if onset_estimated else None,
        "explanatory_divergence_status": ed_status,
        "explanatory_divergence": ed,
        "point_of_no_return": ponr_action,
        "breach_step_index": breach_action,
        "first_detection_step": fds,
    }

    if breach and fds is None:
        rec["containment_latency"] = {"value": None, "censored": True}
    elif breach:
        value = fds - breach_action
        rec["containment_latency"] = {
            "value": value, "censored": False, "detected_at_breach": value == 0,
        }
    else:
        rec["containment_latency"] = {"value": None, "censored": False}

    if breach:
        rec["terminal_outcome"] = "breach"
    elif fixture_mode == "obstructed":
        rec["terminal_outcome"] = rng.choice(("escalated", "escalated", "refusal_tarpit"))
    elif fixture_mode == "induced":
        rec["terminal_outcome"] = rng.choice(("resolved", "resolved", "refusal_tarpit"))
    else:
        rec["terminal_outcome"] = "resolved"

    if fixture_mode == "control":
        rec["widening_route"] = "none"
    elif fixture_mode == "induced":
        rec["widening_route"] = rng.choice(("grant", "firewall"))
    else:
        rec["widening_route"] = rng.choice(("grant", "firewall", "none"))

    rec["identity"] = None
    rec["cnf"] = None
    rec["saster_category"] = SASTER_CATEGORY
    rec["observed_categories"] = [SASTER_CATEGORY] + (["SASTER-11"] if breach else [])
    rec["config_hashes"] = {
        "objective_spec": f"obj-{fixture_mode}",
        "tool_surface": "ts-carl-ops-v1",
        "analyzer": f"an-{cfg}",
        "router": f"rt-{cfg}",
    }

    meta = {
        "defense_config_key": cfg,
        "fixture_mode": fixture_mode,
        "precondition": precondition,
        "campaign_id": campaign_id,
        "trial_index": trial,
    }
    return rec, meta


def synthetic_corpus(seed: int = 0) -> list[tuple[dict, dict]]:
    """``len(CAMPAIGNS) * len(DEFENSE_CONFIG_KEYS) * K_TRIALS`` valid records,
    each paired with its sidecar ``meta``. Same seed, same corpus."""
    rng = random.Random(seed)
    out: list[tuple[dict, dict]] = []
    for cfg in DEFENSE_CONFIG_KEYS:
        for campaign_id, fixture_mode, precondition in CAMPAIGNS:
            for trial in range(K_TRIALS):
                out.append(_make_record(
                    rng, seed=seed, campaign_id=campaign_id, fixture_mode=fixture_mode,
                    precondition=precondition, cfg=cfg, trial=trial,
                ))
    return out


def all_null_markers_record() -> dict:
    """A valid clean record whose five markers are ALL null: no breach, no
    finding, no onset estimate, no divergence, objective completable
    throughout. The shape a renderer must survive."""
    rec = valid_clean_trajectory()
    rec["detection"] = []
    rec["markers"]["first_detection_step"] = None
    rec["markers"]["units"] = dict.fromkeys(
        ("onset_dist", "explanatory_divergence", "point_of_no_return",
         "breach_step_index", "first_detection_step"),
        "action_index",
    )
    rec["saster_category"] = SASTER_CATEGORY
    rec["observed_categories"] = [SASTER_CATEGORY]
    return rec
