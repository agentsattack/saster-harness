"""Coverage meta-test for the instrument registry.

Every wrapper, metric and marker the harness ships must be registered, and
every registered entry must have the coverage it claims. This file is
committed RED at the start of Stage 1 and is green only when every class has
landed — the failure list below is the work list, in the open.
"""
from __future__ import annotations

import ast
import inspect
import re
from pathlib import Path

import pytest

import saster_defense.l1_classifier
import saster_defense.l2_policy
import saster_defense.l3_trace
import saster_defense.l4_auditor
import saster_defense.l5_approval
from saster_instrument import (
    DEFENSE_CONFIGS,
    DEGENERATE_ROWS,
    MARKERS,
    METRICS,
    VICTIM_FAMILIES,
    WRAPPERS,
)

REPO = Path(__file__).resolve().parents[1]
TESTS = REPO / "tests"

#: The method names that make a class a wrapper: it turns an external
#: backend's answer (or a model's text) into a verdict.
_WRAPPER_METHODS = {"classify", "evaluate", "check", "gate", "audit"}
_UNITS = {"action_index", "snapshot_index", "turn_index"}


def _defined_test_names() -> set[str]:
    names: set[str] = set()
    for path in TESTS.glob("test_*.py"):
        names.update(re.findall(r"^def (test_\w+)", path.read_text(), flags=re.M))
    return names


def _wrapper_classes() -> set[str]:
    found: set[str] = set()
    for mod in (
        saster_defense.l1_classifier, saster_defense.l2_policy,
        saster_defense.l3_trace, saster_defense.l4_auditor,
        saster_defense.l5_approval,
    ):
        for _name, cls in inspect.getmembers(mod, inspect.isclass):
            if cls.__module__ != mod.__name__:
                continue
            if _WRAPPER_METHODS & {m for m, _ in inspect.getmembers(cls, inspect.isfunction)}:
                found.add(f"{mod.__name__}:{cls.__name__}")
    return found


# -- completeness: nothing shipped is unregistered ---------------------------


def test_every_wrapper_class_is_registered():
    registered = {w.target.rsplit(".", 1)[0] for w in WRAPPERS.values()}
    missing = sorted(_wrapper_classes() - registered)
    assert not missing, f"wrapper classes with no registry entry: {missing}"


def test_the_bare_clients_are_registered():
    targets = {w.target for w in WRAPPERS.values()}
    assert "saster_defense.opa_backend:evaluate_opa" in targets
    assert "saster_defense.l3_trace:breach_entailed_z3" in targets
    assert "saster_harness.canary:classify_turn" in targets


def test_every_record_metric_is_registered():
    from carl_ops_trajectory.schema import ENVELOPE_FIELDS

    expected = set(ENVELOPE_FIELDS) | {"surprisal", "refusal_prob", "containment_latency"}
    assert expected <= set(METRICS), sorted(expected - set(METRICS))


def test_every_report_metric_is_registered():
    assert {"cvr", "breach_rate", "records_distinct_ratio"} <= set(METRICS)


def test_every_emitted_marker_is_registered():
    from carl_ops_markers import marker_block

    src = inspect.getsource(marker_block)
    emitted = set(re.findall(r'^\s+"(\w+)":', src, flags=re.M))
    emitted -= {"index_space", "onset_status", "explanatory_divergence_status",
                "units", "breach_step_index_snapshot"}
    # the second dict literal in marker_block is the snapshot-space copy
    assert emitted <= set(MARKERS), sorted(emitted - set(MARKERS))
    assert set(MARKERS) <= emitted | {"onset_dist"}, sorted(set(MARKERS) - emitted)


def test_every_matrix_defense_config_is_registered():
    """The registry must name every cell the matrix driver sweeps, and build
    the same DefenseConfig the cell driver would."""
    from saster_defense import DefenseConfig

    driver = (REPO / "scripts" / "run_cell_w9.py").read_text()
    tree = ast.parse(driver)
    literal: dict[str, DefenseConfig] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "_DEFENSE_CONFIGS" for t in node.targets
        ):
            for k, v in zip(node.value.keys, node.value.values, strict=True):
                kwargs = {kw.arg: kw.value.value for kw in v.keywords}
                literal[k.value] = DefenseConfig(**kwargs)
    assert literal, "could not read _DEFENSE_CONFIGS from scripts/run_cell_w9.py"
    matrix_keys = {"l2", "l3", "l4", "l3+l4", "all", "none"}
    assert matrix_keys <= set(DEFENSE_CONFIGS), sorted(matrix_keys - set(DEFENSE_CONFIGS))
    for key, spec in DEFENSE_CONFIGS.items():
        if key in literal:
            assert spec.factory() == literal[key], key


def test_every_served_victim_family_is_registered():
    from saster_defense.manifest import TRAFFIC_PLANE
    from saster_harness.campaign import TEMPLATE_KWARGS_BY_MODEL

    served = set(TRAFFIC_PLANE["victim_backends"].values()) | set(TEMPLATE_KWARGS_BY_MODEL)
    registered = {f.model for f in VICTIM_FAMILIES.values()}
    assert served <= registered, sorted(served - registered)
    for fam in VICTIM_FAMILIES.values():
        assert fam.chat_template_kwargs == TEMPLATE_KWARGS_BY_MODEL.get(fam.model, {}), fam.key
    assert len(VICTIM_FAMILIES) >= 2, "the round-trip rider needs two families"


# -- coverage: everything registered has the tests it claims ------------------


@pytest.mark.parametrize("name", sorted(WRAPPERS))
def test_every_wrapper_has_degenerate_matrix(name):
    """Class 1. A wrapper either has an adapter for EVERY row of the
    degenerate-input matrix, or declares it has no parse surface and why."""
    spec = WRAPPERS[name]
    assert spec.has_matrix, f"{name}: no degenerate-input adapter and no no_parse_surface reason"
    if spec.degenerate is not None:
        from saster_instrument.degenerate import RowNotApplicable

        for row in DEGENERATE_ROWS:
            run, patches = spec.degenerate(row)
            if isinstance(run, RowNotApplicable):
                assert run.reason.strip(), f"{name}/{row}: not-applicable without a reason"
                continue
            assert callable(run), f"{name}/{row}: adapter returned no runner"
            assert isinstance(patches, list), f"{name}/{row}"


@pytest.mark.parametrize("name", sorted(METRICS))
def test_every_metric_has_degenerate_probes(name):
    """Class 2. Every scalar metric has at least one degenerate-input probe."""
    assert METRICS[name].probes, f"{name}: no degenerate-input probes"


@pytest.mark.parametrize("name", sorted(MARKERS))
def test_every_marker_declares_a_unit(name):
    """Class 4. Every marker carries a unit from the closed vocabulary."""
    assert MARKERS[name].unit in _UNITS, f"{name}: unit is {MARKERS[name].unit!r}"


def _claims() -> list[tuple[str, str]]:
    out = []
    for reg in (WRAPPERS, METRICS, MARKERS, DEFENSE_CONFIGS, VICTIM_FAMILIES):
        for key, spec in reg.items():
            for t in spec.covered_by:
                out.append((key, t))
    return out


def test_every_entry_claims_at_least_one_test():
    empty = [
        key for reg in (WRAPPERS, METRICS, MARKERS, DEFENSE_CONFIGS, VICTIM_FAMILIES)
        for key, spec in reg.items() if not spec.covered_by
    ]
    assert not empty, f"registry entries claiming no test coverage: {empty}"


def test_every_claimed_test_exists():
    defined = _defined_test_names()
    missing = sorted({t for _k, t in _claims() if t not in defined})
    assert not missing, f"registry entries claim tests that do not exist: {missing}"
