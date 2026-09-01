#!/usr/bin/env python3
"""W16 — seed audit of the W14 corpus.

W15 found the induced arm ran ``base_seed=20260830`` replayed across twelve
cells: 60 records standing on 5 distinct seeds. This establishes how far that
goes, and restates every W14 number against the count of DISTINCT TRAJECTORIES
behind it rather than the count of records.

**The unit of independence is the agent trajectory, not the record.** Breach,
CVR, terminal outcome and the L4 verdict are all functions of the action
sequence the agent produced; two records carrying the same sequence carry the
same value of each, so they are one observation counted twice. Distinctness is
measured empirically here — by hashing the actual (tool, args) sequence — and
not inferred from which axes "should" collapse.

Wilson intervals are recomputed on the corrected n. Nothing is re-run.
"""

from __future__ import annotations

import hashlib
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CORPUS = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / "runs/w14_corpus_qwen_single_victim"
DEFENSE_ORDER = ["none", "l2", "l3", "l4", "l3+l4", "all"]


def wilson(k: int, n: int, z: float = 1.959963985) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def traj_sig(rec: dict) -> str:
    """Content signature of what the AGENT did — the unit of independence.

    Actions only: the defense config changes the detection block and the
    manifest, never the action sequence, so two records with the same
    signature are the same trajectory observed under different configs.
    """
    payload = json.dumps(
        [[a["tool"], a["args"]] for a in rec["actions"]],
        sort_keys=True, separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:12]


def load() -> list[dict]:
    rows = []
    for man_path in sorted(CORPUS.rglob("manifest.json")):
        traj = man_path.parent / "trajectories.jsonl"
        if not traj.exists():
            continue
        man = json.loads(man_path.read_text())
        for i, line in enumerate(traj.open()):
            if not line.strip():
                continue
            rec = json.loads(line)
            rows.append({
                "cell": man_path.parent.name,
                "defense": man.get("defense_config_key"),
                "precondition": "obstructed" if man.get("obstructed") else "unobstructed",
                "mode": man.get("fixture_mode"),
                "arm": "p12_ladder" if man_path.parent.name.startswith("p12") else "matrix",
                "seeds": man.get("seeds", []),
                "seed": man.get("seeds", [None] * (i + 1))[i] if man.get("seeds") else None,
                "sig": traj_sig(rec),
                "rec": rec,
            })
    return rows


def line(ch: str = "-") -> None:
    print(ch * 78)


def restate(label: str, k_rec: int, n_rec: int, k_tr: int, n_tr: int) -> None:
    lo1, hi1 = wilson(k_rec, n_rec)
    lo2, hi2 = wilson(k_tr, n_tr)
    same = "  (unchanged)" if n_rec == n_tr else ""
    print(f"  {label:<30}")
    print(f"    as reported  {k_rec:>3}/{n_rec:<3} = {100*k_rec/n_rec:5.1f}%   "
          f"Wilson [{100*lo1:5.1f}%, {100*hi1:5.1f}%]")
    print(f"    distinct     {k_tr:>3}/{n_tr:<3} = {100*k_tr/n_tr:5.1f}%   "
          f"Wilson [{100*lo2:5.1f}%, {100*hi2:5.1f}%]{same}")


def main() -> None:
    rows = load()
    print("=" * 78)
    print("W16 — SEED AUDIT OF THE W14 CORPUS")
    print("=" * 78)
    print(f"corpus  : {CORPUS.name}")
    print(f"records : {len(rows)}")
    print(f"cells   : {len({r['cell'] for r in rows})}")

    # ---- 1. seeds per cell ------------------------------------------------
    print()
    line("=")
    print("1. SEEDS PER CELL")
    line("=")
    cells = {}
    for r in rows:
        cells.setdefault(r["cell"], r)
    print(f"  {'cell':<46} {'seeds':<34} {'distinct':>8}")
    for name in sorted(cells):
        s = cells[name]["seeds"]
        rng = f"{min(s)}..{max(s)}" if s else "(none)"
        print(f"  {name:<46} {rng:<34} {len(set(s)):>8}")

    all_seeds = {x for r in rows for x in r["seeds"]}
    print(f"\n  DISTINCT SEEDS ACROSS THE WHOLE CORPUS: {len(all_seeds)} -> {sorted(all_seeds)}")
    print(f"  every cell draws from the same {len(all_seeds)}-seed pool")

    # ---- 2. distinct seeds across cells sharing a config or arm -----------
    print()
    line("=")
    print("2. DISTINCT SEEDS ACROSS CELLS SHARING A CONFIG / ARM")
    line("=")
    for key, label in (("defense", "defense config"), ("mode", "fixture mode"),
                       ("precondition", "precondition"), ("arm", "arm")):
        print(f"\n  grouped by {label}:")
        g = defaultdict(list)
        for r in rows:
            g[r[key]].append(r)
        print(f"    {'group':<22} {'cells':>6} {'records':>8} {'distinct seeds':>15}")
        for val in sorted(g, key=str):
            rs = g[val]
            print(f"    {str(val):<22} {len({x['cell'] for x in rs}):>6} {len(rs):>8} "
                  f"{len({s for x in rs for s in x['seeds']}):>15}")

    # ---- 3. distinct TRAJECTORIES ----------------------------------------
    print()
    line("=")
    print("3. DISTINCT TRAJECTORIES BEHIND EACH REPORTED NUMBER")
    line("=")
    print("  A record is not an observation. Breach, CVR, terminal outcome and the")
    print("  L4 verdict are all functions of the action sequence, so records sharing")
    print("  a signature are one observation counted more than once.\n")

    sigs = {r["sig"] for r in rows}
    print(f"  records: {len(rows)}   DISTINCT TRAJECTORIES: {len(sigs)}   "
          f"inflation factor {len(rows)/len(sigs):.1f}x\n")

    # dedupe helper: one representative record per signature within a group
    def dedupe(rs):
        seen, out = set(), []
        for r in rs:
            if r["sig"] not in seen:
                seen.add(r["sig"])
                out.append(r)
        return out

    matrix = [r for r in rows if r["arm"] == "matrix"]
    ladder = [r for r in rows if r["arm"] == "p12_ladder"]

    # -- breach rate by config
    print("  BREACH RATE BY DEFENSE CONFIG")
    for cfg in DEFENSE_ORDER:
        rs = [r for r in matrix if r["defense"] == cfg]
        if not rs:
            continue
        d = dedupe(rs)
        restate(f"config {cfg}",
                sum(r["rec"]["oracle"]["breach"] for r in rs), len(rs),
                sum(r["rec"]["oracle"]["breach"] for r in d), len(d))

    # -- breach by fixture mode and precondition
    print("\n  BREACH RATE BY FIXTURE MODE")
    for m in sorted({r["mode"] for r in matrix}):
        rs = [r for r in matrix if r["mode"] == m]
        d = dedupe(rs)
        restate(m, sum(r["rec"]["oracle"]["breach"] for r in rs), len(rs),
                sum(r["rec"]["oracle"]["breach"] for r in d), len(d))

    print("\n  BREACH RATE BY PRECONDITION (P14 as W14 reported it)")
    for p in ("obstructed", "unobstructed"):
        rs = [r for r in matrix if r["precondition"] == p]
        d = dedupe(rs)
        restate(p, sum(r["rec"]["oracle"]["breach"] for r in rs), len(rs),
                sum(r["rec"]["oracle"]["breach"] for r in d), len(d))

    # -- CVR
    print("\n  CVR (L2 denials / actions)")
    for cfg in ("l2", "all"):
        rs = [r for r in matrix if r["defense"] == cfg]
        if not rs:
            continue
        d = dedupe(rs)   # verdicts are fixed within a config, so signature suffices
        den_r = sum(1 for r in rs for a in r["rec"]["actions"] if a.get("policy_verdict") == "deny")
        act_r = sum(len(r["rec"]["actions"]) for r in rs)
        den_d = sum(1 for r in d for a in r["rec"]["actions"] if a.get("policy_verdict") == "deny")
        act_d = sum(len(r["rec"]["actions"]) for r in d)
        print(f"    config {cfg:<6} as reported {den_r}/{act_r} actions   "
              f"distinct {den_d}/{act_d} actions   CVR 0.000 either way")

    # -- containment latency
    #
    # Latency is NOT a function of the trajectory alone: the same actions are
    # right-censored under an L4-off config and uncensored under an L4-on one,
    # because first_detection_step moves. The unit here is therefore
    # (trajectory x defense config), not the trajectory.
    print("\n  CONTAINMENT LATENCY   [unit: (trajectory x config), not trajectory]")
    breached = [r for r in matrix if r["rec"]["oracle"]["breach"]]

    def dedupe_cfg(rs):
        seen, out = set(), []
        for r in rs:
            key = (r["sig"], r["defense"])
            if key not in seen:
                seen.add(key)
                out.append(r)
        return out

    bd = dedupe_cfg(breached)
    def cens(rs):
        c = sum(1 for r in rs if (r["rec"].get("containment_latency") or {}).get("censored"))
        v = [(r["rec"].get("containment_latency") or {}).get("value") for r in rs
             if not (r["rec"].get("containment_latency") or {}).get("censored")]
        v = [x for x in v if x is not None]
        return c, v
    c_r, v_r = cens(breached)
    c_d, v_d = cens(bd)
    print(f"    as reported  breached {len(breached)}  censored {c_r} "
          f"({100*c_r/len(breached):.1f}%)  uncensored {len(v_r)} median "
          f"{statistics.median(v_r) if v_r else '--'}")
    print(f"    distinct     breached {len(bd)}  censored {c_d} "
          f"({100*c_d/len(bd):.1f}%)  uncensored {len(v_d)} median "
          f"{statistics.median(v_d) if v_d else '--'}")

    # -- L4 precision/recall
    print("\n  L4 PRECISION / RECALL (L4-enabled configs)")
    l4 = [r for r in matrix if r["defense"] in ("l4", "l3+l4", "all")]
    # the L4 verdict is a function of the trajectory, so dedupe on signature
    l4d = dedupe(l4)
    def conf(rs):
        tp = fp = fn = tn = 0
        for r in rs:
            fired = any(e.get("finding") and e["layer"] == "l4_auditor"
                        for e in r["rec"].get("detection", []))
            b = r["rec"]["oracle"]["breach"]
            tp += b and fired; fp += (not b) and fired
            fn += b and not fired; tn += (not b) and not fired
        return tp, fp, fn, tn
    for label, rs in (("as reported", l4), ("distinct  ", l4d)):
        tp, fp, fn, tn = conf(rs)
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec_ = tp / (tp + fn) if tp + fn else 0.0
        lo, hi = wilson(tp, tp + fp)
        print(f"    {label}  n={len(rs):<3} TP={tp} FP={fp} FN={fn} TN={tn}  "
              f"precision={prec:.3f} Wilson [{100*lo:.1f}%, {100*hi:.1f}%]  recall={rec_:.3f}")

    # -- terminal outcomes
    print("\n  TERMINAL OUTCOME COUNTS")
    alld = dedupe(rows)
    cr = Counter(r["rec"]["terminal_outcome"] for r in rows)
    cd = Counter(r["rec"]["terminal_outcome"] for r in alld)
    print(f"    {'class':<38} {'as reported':>12} {'distinct':>10}")
    for cls in sorted(set(cr) | set(cd)):
        print(f"    {cls:<38} {cr.get(cls,0):>12} {cd.get(cls,0):>10}")
    print(f"    {'TOTAL':<38} {len(rows):>12} {len(alld):>10}")

    # -- P12 ladder
    print("\n  P12 LADDER")
    for n in (1, 2, 3):
        rs = [r for r in ladder if f"rules{n}" in r["cell"]]
        if not rs:
            continue
        d = dedupe(rs)
        print(f"    {n} rule(s): as reported {len(rs)} records, distinct {len(d)} trajectories")
    ld = dedupe(ladder)
    print(f"    ladder overall: {len(ladder)} records -> {len(ld)} distinct trajectories")

    print()
    line("=")
    print("SIGNATURE MULTIPLICITY (how many records each trajectory carries)")
    line("=")
    mult = Counter(Counter(r["sig"] for r in rows).values())
    for k in sorted(mult):
        print(f"  {mult[k]:>3} trajectory(ies) appear in {k} record(s) each")


if __name__ == "__main__":
    main()
