#!/usr/bin/env python3
"""Protocol A — instrument mutation score. For every mutant/<row> branch: a
worktree; the tests-baseline tree (the suite that was green before the
rejection suite existed) run against the mutant; then the current tree.
A mutant is KILLED by a suite when a test that passes on unmutated HEAD fails
on the mutant. Collection errors and tests already failing on HEAD are
excluded. Writes runs/unprompted/mutation_score.json.

Usage: mutation_score.py [row ...]   (default: every mutant/* branch)
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PY = REPO / ".venv/bin/python"
OUT = REPO / "runs/unprompted"
BASELINE_TAG = "tests-baseline"


def sh(cmd, cwd=REPO, **kw):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, **kw)


def failed_ids(worktree: Path, tests_dir: Path, rootdir: Path) -> tuple[set[str], set[str], float]:
    """(failed test ids, collection-error files, wall seconds) for one suite run."""
    env = dict(os.environ, PYTHONPATH=str(worktree))
    t0 = time.monotonic()
    p = subprocess.run([str(PY), "-m", "pytest", "-q", "-p", "no:cacheprovider", "--rootdir", str(rootdir), str(tests_dir),
                        "--continue-on-collection-errors", "-rfE", "--tb=no", "-x" if False else "-q"],
                       cwd=worktree, env=env, capture_output=True, text=True)
    wall = time.monotonic() - t0
    failed = {m.group(1) for m in re.finditer(r"^FAILED (\S+?)(?: - .*)?$", p.stdout, flags=re.M)}
    errors = {m.group(1) for m in re.finditer(r"^ERROR (\S+?)(?: - .*)?$", p.stdout, flags=re.M)}
    norm = lambda s: re.sub(r"^.*?/tests/", "tests/", s)  # noqa: E731
    return {norm(f) for f in failed}, {norm(e) for e in errors}, round(wall, 1)


def baseline_tree(tmp: Path) -> Path:
    b = tmp / "baseline"
    b.mkdir()
    tar = subprocess.run(["git", "archive", BASELINE_TAG, "tests", "pyproject.toml"], cwd=REPO, capture_output=True, check=True)
    subprocess.run(["tar", "-x", "-C", str(b)], input=tar.stdout, check=True)
    return b


def worktree(ref: str, tmp: Path, name: str) -> Path:
    w = tmp / name
    sh(["git", "worktree", "add", "--detach", str(w), ref], check=True)
    tools = REPO / ".tools"
    if tools.exists():
        os.symlink(tools.resolve(), w / ".tools")
    return w


def main() -> None:
    rows = sys.argv[1:] or sorted(b.strip().removeprefix("mutant/") for b in sh(["git", "branch", "--list", "mutant/*"]).stdout.splitlines())
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="mutscore-") as td:
        tmp = Path(td)
        base_tests = baseline_tree(tmp) / "tests"
        head = worktree("evidence/unprompted", tmp, "head")
        ctrl_base_f, ctrl_base_e, _ = failed_ids(head, base_tests, base_tests.parent)
        ctrl_cur_f, ctrl_cur_e, _ = failed_ids(head, head / "tests", head)
        print(f"control on HEAD: baseline suite pre-failing {len(ctrl_base_f)} (+{len(ctrl_base_e)} collection errors); current suite pre-failing {len(ctrl_cur_f)}")
        results = {"baseline_tag": sh(["git", "rev-parse", BASELINE_TAG]).stdout.strip(), "head": sh(["git", "rev-parse", "evidence/unprompted"]).stdout.strip(),
                   "control": {"baseline_prefailing": sorted(ctrl_base_f), "baseline_collection_errors": sorted(ctrl_base_e), "current_prefailing": sorted(ctrl_cur_f)}, "mutants": {}}
        for row in rows:
            ref = f"mutant/{row}"
            w = worktree(ref, tmp, f"m_{row}")
            bf, be, bw = failed_ids(w, base_tests, base_tests.parent)
            cf, ce, cw = failed_ids(w, w / "tests", w)
            base_kills = sorted(bf - ctrl_base_f)
            cur_kills = sorted(cf - ctrl_cur_f)
            readme = (w / "MUTANT_README.md").read_text() if (w / "MUTANT_README.md").exists() else ""
            results["mutants"][row] = {"commit": sh(["git", "rev-parse", ref]).stdout.strip(), "baseline": {"killed": bool(base_kills), "killing_tests": base_kills, "wall_s": bw, "collection_errors": sorted(be - ctrl_base_e)},
                                       "current": {"killed": bool(cur_kills), "killing_tests": cur_kills, "wall_s": cw, "collection_errors": sorted(ce - ctrl_cur_e)}, "readme": readme}
            print(f"{row:<4} baseline {'KILLED' if base_kills else 'survived':<8} ({len(base_kills)} tests, {bw}s) | current {'KILLED' if cur_kills else 'survived':<8} ({len(cur_kills)} tests, {cw}s) {cur_kills[:2]}")
            sh(["git", "worktree", "remove", "--force", str(w)])
        sh(["git", "worktree", "remove", "--force", str(head)])
    (OUT / "mutation_score.json").write_text(json.dumps(results, indent=1))
    print("wrote", OUT / "mutation_score.json")


if __name__ == "__main__":
    main()
