"""W16 — two different cells must never produce the same seed.

W14 shipped with every cell running ``base_seed=20260830``. Its 135 records
stood on 5 distinct seeds, a 13.5x inflation of the apparent sample size, and
it is why the induced arm read 0/60 when the honest bound was 0/5. A rate of
zero is exactly where that error is most dangerous, because a replayed
trajectory looks like corroboration.

These pin the property that prevents it: seed blocks are disjoint per cell.
"""

from __future__ import annotations

import importlib.util
from collections import Counter
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


def _driver():
    spec = importlib.util.spec_from_file_location(
        "run_matrix_w14", REPO / "scripts/run_matrix_w14.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_no_two_cells_share_a_seed() -> None:
    """The property W14 violated."""
    plan = _driver().cell_plan()
    seeds = [s for cell in plan for s in cell["seeds"]]
    dupes = {s: n for s, n in Counter(seeds).items() if n > 1}
    assert not dupes, f"seed(s) reused across cells: {dupes}"
    assert len(seeds) == len(set(seeds))


def test_each_cell_has_k_distinct_seeds() -> None:
    plan = _driver().cell_plan()
    for cell in plan:
        assert len(set(cell["seeds"])) == len(cell["seeds"]) > 0, cell["id"]


def test_seed_blocks_do_not_overlap_between_adjacent_cells() -> None:
    """Adjacent ordinals are where a stride error would show first."""
    plan = _driver().cell_plan()
    for a, b in zip(plan, plan[1:], strict=False):
        assert max(a["seeds"]) < min(b["seeds"]), (
            f"{a['id']} block ends at {max(a['seeds'])} but {b['id']} starts at "
            f"{min(b['seeds'])}"
        )


@pytest.mark.parametrize("k", [1, 5, 40, 200, 999])
def test_disjointness_holds_at_other_trial_counts(k: int) -> None:
    """The guarantee must not depend on k happening to be 5."""
    plan = _driver().cell_plan(k=k)
    seeds = [s for cell in plan for s in cell["seeds"]]
    assert len(seeds) == len(set(seeds)) == len(plan) * k


def test_k_beyond_the_stride_is_refused_not_silently_collided() -> None:
    """Past the stride the blocks would overlap. That must raise rather than
    quietly reproduce the W14 defect at a larger k."""
    mod = _driver()
    with pytest.raises(ValueError, match="SEED_STRIDE"):
        mod.cell_plan(k=mod.SEED_STRIDE + 1)


def test_cell_ids_are_unique() -> None:
    """Seed blocks key off plan ordinal, so a duplicated id would mean two
    cells writing the same directory rather than two seed blocks colliding —
    a different defect with the same symptom."""
    plan = _driver().cell_plan()
    ids = [c["id"] for c in plan]
    assert len(ids) == len(set(ids)), [i for i, n in Counter(ids).items() if n > 1]


def test_the_w14_base_seed_is_not_reused() -> None:
    """20260830-20260834 are spent: they are in the published W14 corpus. A
    re-run must not silently reproduce those same five trajectories."""
    plan = _driver().cell_plan()
    seeds = {s for cell in plan for s in cell["seeds"]}
    assert not (seeds & set(range(20260830, 20260835)))
