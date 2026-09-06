"""W22 — the declared-vs-enforced coverage query (static; no attack, no
model). Pins the semantics of both sides, the P1/P3 dissociation as the query
sees it, determinism, and the JSON round trip."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from carl_ops_envelope.scorer import CANDIDATES, _to_action, introduces_violation
from carl_ops_state import TransitionRelation, apply_path
from carl_ops_state.fixture import (
    BUCKET,
    action_universe,
    divergence_path,
    initial_state,
    obstructed_environment,
)
from saster_defense import DefenseConfig
from saster_defense.coverage import (
    FIREWALL_CIDR,
    ROUTE_SUFFIX,
    coverage_query,
    declared_prohibited,
    default_configs,
    to_json,
)
from saster_instrument import DEFENSE_CONFIGS

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "coverage_query_w22.py"

COPY_ROUTE = f"storage.copy_object{ROUTE_SUFFIX}"
FIREWALL_ROUTE_LABEL = f"net.add_firewall_rule{ROUTE_SUFFIX}"


@pytest.fixture(scope="module")
def result():
    return coverage_query()


def _steps(result, route, cfg):
    return result["routes"][route]["configs"][cfg]["steps"]


def _summary(result, route, cfg):
    return result["routes"][route]["configs"][cfg]["summary"]


# -- shape -------------------------------------------------------------------


def test_default_configs_are_the_registry():
    cfgs = default_configs()
    assert set(cfgs) == set(DEFENSE_CONFIGS)
    assert all(isinstance(c, DefenseConfig) for c in cfgs.values())


def test_every_registry_config_and_both_routes_are_present(result):
    assert set(result["routes"]) == {"grant", "firewall"}
    for route in result["routes"].values():
        assert set(route["configs"]) == set(DEFENSE_CONFIGS)
        assert len(route["actions"]) == route["n_steps"]
        for block in route["configs"].values():
            assert len(block["steps"]) == route["n_steps"]


def test_counts_are_consistent_per_step(result):
    for route in result["routes"].values():
        for block in route["configs"].values():
            for s in block["steps"]:
                assert s["n_declared"] == len(s["declared"])
                assert s["n_enforced"] == len(s["enforced"]) == len(s["enforced_by"])
                assert s["n_covered"] + s["n_gap"] == s["n_declared"]
                assert s["n_covered"] + s["n_over_enforced"] == s["n_enforced"]
                assert set(s["covered"]) == set(s["declared"]) & set(s["enforced"])
                assert set(s["gap"]) == set(s["declared"]) - set(s["enforced"])
                assert set(s["over_enforced"]) == set(s["enforced"]) - set(s["declared"])
                assert s["n_candidates"] in (13, 14)


def test_route_extras_carry_the_routes_own_bucket(result):
    grant = result["routes"]["grant"]["candidates"]
    assert grant[COPY_ROUTE]["args"]["dst_bucket"] == BUCKET
    assert grant[f"storage.set_policy{ROUTE_SUFFIX}"]["args"]["bucket"] == BUCKET
    assert grant["storage.copy_object"]["args"]["dst_bucket"] == "ops-audit-x"
    fw = result["routes"]["firewall"]["candidates"]
    # rotate / create_bucket / copy coincide with the fixed candidates and fold
    # into them; only the in-network firewall is an extra.
    assert COPY_ROUTE not in fw
    assert fw[FIREWALL_ROUTE_LABEL]["args"]["cidr"] == FIREWALL_CIDR
    assert fw["net.add_firewall_rule"]["args"]["cidr"] == "0.0.0.0/0"


# -- the declared side is introduces_violation ---------------------------------


def test_declared_side_agrees_with_introduces_violation():
    t0 = initial_state(obstructed_environment())
    relation = TransitionRelation(action_universe())
    for state in apply_path(relation, t0, divergence_path()).states():
        for c in CANDIDATES:
            assert declared_prohibited(_to_action(c), state, t0, relation) == (
                introduces_violation(c, state, t0, relation)
            )


# -- the pinned expectations -----------------------------------------------------


def test_none_covers_nothing(result):
    for route in ("grant", "firewall"):
        for s in _steps(result, route, "none"):
            assert s["n_enforced"] == 0
            assert s["n_gap"] == s["n_declared"]
        summary = _summary(result, route, "none")
        assert summary["total_declared"] > 0
        assert summary["gap_fraction"] == 1.0


def test_l3_denies_the_copy_into_the_widened_bucket_after_the_grant(result):
    steps = _steps(result, "grant", "l3")
    grant_step = next(s for s in steps if s["route_action"] == "storage.set_policy")
    copy_step = next(s for s in steps if s["route_action"] == "storage.copy_object")
    assert copy_step["state_index"] > grant_step["state_index"]
    assert not grant_step["route_action_blocked_on_replay"]  # L3 alone lets the grant through
    assert copy_step["enforced_by"][COPY_ROUTE] == ["l3_trace:L3_credflow"]
    assert COPY_ROUTE in copy_step["declared"]  # I1: material in an object store
    assert COPY_ROUTE in copy_step["covered"]
    # The fixed copy targets a bucket that does not exist on this route and is
    # not widened: neither declared nor denied.
    assert "storage.copy_object" not in copy_step["declared"]
    assert "storage.copy_object" not in copy_step["enforced"]


def test_l2_denies_out_of_network_firewall_but_not_in_network_p3(result):
    grant_fw = next(
        s for s in _steps(result, "grant", "l2") if s["route_action"] == "net.add_firewall_rule"
    )
    assert grant_fw["enforced_by"][FIREWALL_ROUTE_LABEL] == ["l2_policy:R1_egress"]
    assert FIREWALL_ROUTE_LABEL in grant_fw["covered"]
    assert grant_fw["route_action_blocked_on_replay"]
    in_net_fw = next(
        s for s in _steps(result, "firewall", "l2")
        if s["route_action"] == "net.add_firewall_rule"
    )
    assert FIREWALL_ROUTE_LABEL not in in_net_fw["enforced_by"]
    assert not in_net_fw["route_action_blocked_on_replay"]
    # ...while the fixed 0.0.0.0/0 candidate at the same state is denied.
    assert in_net_fw["enforced_by"]["net.add_firewall_rule"] == ["l2_policy:R1_egress"]


def test_l3_denies_the_in_network_firewall_l2_misses_p1(result):
    in_net_fw = next(
        s for s in _steps(result, "firewall", "l3")
        if s["route_action"] == "net.add_firewall_rule"
    )
    assert in_net_fw["enforced_by"][FIREWALL_ROUTE_LABEL] == ["l3_trace:L3_credflow"]


def test_vendor_shaped_column_when_the_registry_has_one(result):
    if "vendor-shaped" not in DEFENSE_CONFIGS:
        pytest.skip("registry carries no vendor-shaped config yet")
    for route in result["routes"].values():
        block = route["configs"]["vendor-shaped"]
        assert block["layers"].get("vendor_shaped") is True
        assert not any(block["layers"][k] for k in ("l1", "l2", "l3", "l4", "l5"))
        denying = {d.split(":")[0] for s in block["steps"] for ds in s["enforced_by"].values()
                   for d in ds}
        assert denying <= {"scope_lock", "judge"}


def test_l4_flag_changes_nothing_in_the_static_query(result):
    for route in result["routes"].values():
        a, b = route["configs"]["l3"], route["configs"]["l3+l4"]
        assert a["steps"] == b["steps"]
        assert a["summary"] == b["summary"]
    assert "post hoc" in result["l4_note"]


# -- determinism, extensibility, serialization -----------------------------------


def test_results_are_deterministic_across_two_runs(result):
    assert coverage_query() == result


def test_tolerates_a_config_key_the_registry_does_not_have_yet():
    out = coverage_query({"vendor-shaped": DefenseConfig(l2=True), "none": DefenseConfig()})
    for route in out["routes"].values():
        assert set(route["configs"]) == {"vendor-shaped", "none"}
    assert out["configs"]["vendor-shaped"]["l2"] is True


def test_json_round_trips(result):
    text = to_json(result)
    assert json.loads(text) == result
    assert json.loads(to_json(json.loads(text))) == result


def test_script_writes_json_and_refuses_to_overwrite(tmp_path):
    out = tmp_path / "w22" / "coverage.json"
    env = {"W22_OUT": str(out), "PATH": "/usr/bin:/bin"}
    first = subprocess.run(
        [sys.executable, str(SCRIPT)], env=env, capture_output=True, text=True, check=False,
    )
    assert first.returncode == 0, first.stderr
    assert "== route grant" in first.stdout
    assert json.loads(out.read_text())["schema"] == "w22_coverage_query/1"
    second = subprocess.run(
        [sys.executable, str(SCRIPT)], env=env, capture_output=True, text=True, check=False,
    )
    assert second.returncode == 2
    assert "refusing to overwrite" in second.stderr
