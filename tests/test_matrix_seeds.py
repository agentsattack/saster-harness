"""Seed design for the matrix driver — PAIRED (W17).

W14 shipped with every one of its 27 cells running ``base_seed=20260830``. Its
135 records stood on 5 distinct seeds, a 13.5x inflation, and it is why the
induced arm read 0/60 when the honest bound was 0/5.

W16 fixed that by giving every cell a disjoint seed block. That over-corrected:
marginal layer contribution is a **paired** comparison, and giving each defense
config its own seeds puts sampling noise exactly where the ablation reads its
signal.

W17 is the design these tests pin. A seed depends on the STRATUM —
``(precondition, fixture_mode)`` — and the trial index, never on the defense
config. So:

  * two cells differing ONLY in defense config share seeds  (paired ablation)
  * two cells differing in precondition or fixture mode do NOT (independent
    strata)
"""

from __future__ import annotations

import importlib.util
from collections import Counter, defaultdict
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

#: Seeds already spent in published corpora. A re-run must not silently
#: reproduce those trajectories and present them as new observations.
W14_SEEDS = set(range(20260830, 20260835))
W15_SEEDS = set(range(20260901, 20260941)) | set(range(20261001, 20261041))


def _driver():
    spec = importlib.util.spec_from_file_location(
        "run_matrix_w14", REPO / "scripts/run_matrix_w14.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _by_id(plan):
    return {c["id"]: c for c in plan}


# -- the paired property (W17) ----------------------------------------------


def test_cells_differing_only_in_defense_config_share_seeds() -> None:
    """The ablation is a paired comparison. Same trajectory, six configs."""
    plan = _driver().cell_plan()
    groups = defaultdict(list)
    for c in plan:
        if c["arm"] != "matrix":
            continue
        groups[(c["axes"]["precondition"], c["axes"]["fixture_mode"])].append(c)
    assert groups, "no matrix cells found"
    for stratum, cells in groups.items():
        assert len({c["axes"]["defense_config"] for c in cells}) > 1, stratum
        seeds = {tuple(c["seeds"]) for c in cells}
        assert len(seeds) == 1, (
            f"{stratum}: cells differing only in defense config must share "
            f"seeds, got {len(seeds)} distinct seed lists"
        )


def test_cells_differing_in_precondition_do_not_share_seeds() -> None:
    plan = _by_id(_driver().cell_plan())
    for cfg in ("l2", "l3", "l4", "l3-l4", "all", "none"):
        for mode in ("compromised", "induced"):
            a = plan.get(f"matrix__{cfg}__obstructed__{mode}")
            b = plan.get(f"matrix__{cfg}__unobstructed__{mode}")
            if a and b:
                assert not (set(a["seeds"]) & set(b["seeds"])), (
                    f"{a['id']} and {b['id']} differ in precondition and must "
                    f"not share seeds"
                )


def test_cells_differing_in_fixture_mode_do_not_share_seeds() -> None:
    plan = _by_id(_driver().cell_plan())
    for cfg in ("l2", "l3", "l4", "l3-l4", "all", "none"):
        for pre in ("obstructed", "unobstructed"):
            a = plan.get(f"matrix__{cfg}__{pre}__compromised")
            b = plan.get(f"matrix__{cfg}__{pre}__induced")
            if a and b:
                assert not (set(a["seeds"]) & set(b["seeds"])), (
                    f"{a['id']} and {b['id']} differ in fixture mode and must "
                    f"not share seeds"
                )


def test_strata_seed_blocks_are_pairwise_disjoint() -> None:
    mod = _driver()
    plan = mod.cell_plan()
    blocks = {}
    for c in plan:
        blocks.setdefault(tuple(c["stratum"]), set()).update(c["seeds"])
    keys = sorted(blocks)
    assert len(keys) == len(mod.STRATA)
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            assert not (blocks[a] & blocks[b]), f"{a} and {b} overlap"


def test_distinct_seed_count_is_strata_times_k() -> None:
    """The corpus's true sample size, stated as an invariant rather than
    inferred from the record count."""
    mod = _driver()
    for k in (1, 5, 40):
        plan = mod.cell_plan(k=k)
        seeds = {s for c in plan for s in c["seeds"]}
        assert len(seeds) == len(mod.STRATA) * k


# -- kept from W16, still applicable ----------------------------------------


def test_each_cell_has_k_distinct_seeds() -> None:
    for c in _driver().cell_plan():
        assert len(set(c["seeds"])) == len(c["seeds"]) > 0, c["id"]


def test_k_beyond_the_stride_is_refused_not_silently_collided() -> None:
    mod = _driver()
    with pytest.raises(ValueError, match="SEED_STRIDE"):
        mod.cell_plan(k=mod.SEED_STRIDE + 1)


def test_cell_ids_are_unique() -> None:
    ids = [c["id"] for c in _driver().cell_plan()]
    assert len(ids) == len(set(ids)), [i for i, n in Counter(ids).items() if n > 1]


def test_spent_seeds_are_not_reused() -> None:
    """20260830-34 are in the W14 corpus; W15's two arms hold 20260901-40 and
    20261001-40. Re-running must not replay any of them."""
    seeds = {s for c in _driver().cell_plan() for s in c["seeds"]}
    assert not (seeds & W14_SEEDS), sorted(seeds & W14_SEEDS)
    assert not (seeds & W15_SEEDS), sorted(seeds & W15_SEEDS)


def test_every_cell_carries_its_stratum() -> None:
    """A record must be able to say which stratum it came from; effective n is
    computed per stratum, not per cell."""
    mod = _driver()
    for c in mod.cell_plan():
        assert tuple(c["stratum"]) in mod.STRATA, c["id"]
        assert c["seed_base"] == mod.SEED_BASE + c["stratum_ordinal"] * mod.SEED_STRIDE


def test_ladder_top_rung_duplicates_a_matrix_cell_exactly() -> None:
    """P12 rung 3 is L2 with all three rules, obstructed, compromised — which
    is byte-identical to ``matrix__l2__obstructed__compromised``. Under the
    paired design they also share seeds, so the two cells must produce
    identical trajectories.

    That duplication is intentional and useful: it is a free determinism check
    on the whole pipeline. If those two cells ever disagree, sampling is not
    reproducible from the seed and every paired comparison in the corpus is
    unsound. Pinned here so the duplicate is not "cleaned up" as redundant.
    """
    plan = _by_id(_driver().cell_plan())
    a = plan["matrix__l2__obstructed__compromised"]
    b = plan["p12__l2__rules3__obstructed__compromised"]
    assert a["env"] == b["env"], (a["env"], b["env"])
    assert a["seeds"] == b["seeds"]
