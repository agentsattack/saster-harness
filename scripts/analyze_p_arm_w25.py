#!/usr/bin/env python3
"""Addendum §P readback: Qwen forced (w25p) beside Qwen unforced and Ministral
on the same 30 cells and paired seeds. Read-only."""
from __future__ import annotations

import collections
import hashlib
import json
import math
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from saster_instrument.metrics import distinct_trajectories  # noqa: E402

OUT = REPO / "runs/w25_stage5/p_arm_readback.json"


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(max(0.0, c - h), 3), round(min(1.0, c + h), 3))


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.open() if line.strip()]


def cells(roots: tuple[str, ...], tag: str) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for root in roots:
        sp = REPO / f"runs/{root}_sweep_{tag}/sweep_state.json"
        if not sp.exists():
            continue
        for cid, c in json.loads(sp.read_text())["cells"].items():
            d = REPO / c["dir"]
            if (d / "trajectories.jsonl").exists():
                out[cid] = read_jsonl(d / "trajectories.jsonl")
    return out


def action_hash(rec: dict) -> str:
    seq = [(a["tool"], a["args"]) for a in rec["actions"]]
    return hashlib.sha256(json.dumps(seq, sort_keys=True).encode()).hexdigest()


def breaches(recs: list[dict]) -> int:
    return sum(1 for r in recs if r["oracle"]["breach"])


def main() -> None:
    forced = cells(("w25p",), "qwen3")
    unforced = {k: v for k, v in cells(("w24b", "w24c"), "qwen3").items() if k in forced}
    ministral = {k: v for k, v in cells(("w24b", "w24c"), "ministral").items() if k in forced}
    first = next(iter(forced))
    man = json.loads((REPO / "runs/w25p_sweep_qwen3/cells" / first / "manifest.json").read_text())
    print(f"§P: {len(forced)} cells; manifest tool_choice={man['tool_choice']} forced={man['tool_choice_forced']} "
          f"arm={man.get('post_sweep_arm')} addendum={man['grrcon_addendum_sha256'][:8]}")
    rows = []
    tot: collections.Counter = collections.Counter()
    bycfg: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    identical = 0
    differing = []
    for cid in sorted(forced):
        parts = cid.split("__")
        cfg = parts[1] + ("/" + parts[2] if cid.startswith("p12") else "")
        bf, bq, bm = breaches(forced[cid]), breaches(unforced[cid]), breaches(ministral[cid])
        rows.append((cid, bf, bq, bm))
        for key, val in (("f", bf), ("q", bq), ("m", bm), ("n", len(forced[cid]))):
            tot[key] += val
            bycfg[cfg][key] += val
        for a, b in zip(forced[cid], unforced[cid], strict=True):
            if action_hash(a) == action_hash(b):
                identical += 1
            else:
                differing.append((cid, a["trial_index"], a["terminal_outcome"], b["terminal_outcome"]))
        print(f"  {cid:<58} forced {bf}/5  unforced {bq}/5  ministral {bm}/5")
    n = tot["n"]
    ci_q = wilson(tot["q"], n)
    print("\nper config (forced / unforced / ministral, of n):")
    for cfg, c in sorted(bycfg.items()):
        print(f"  {cfg:<20} {c['f']}/{c['n']}  {c['q']}/{c['n']}  {c['m']}/{c['n']}")
    pf, pq, pm = tot["f"] / n, tot["q"] / n, tot["m"] / n
    inside = ci_q[0] <= pf <= ci_q[1]
    toward = (pf - pq) * (pm - pq) > 0 and not inside
    print(f"\ntotal: forced {tot['f']}/{n} = {pf:.3f} {wilson(tot['f'], n)}; unforced {tot['q']}/{n} = {pq:.3f} {ci_q}; "
          f"ministral {tot['m']}/{n} = {pm:.3f} {wilson(tot['m'], n)}")
    verdict = "HELD" if inside else ("REFUTED — outside, toward Ministral" if toward else "outside, away from Ministral")
    print(f"§P prediction (forced inside the unforced interval): {verdict}")
    recs = [r for v in forced.values() for r in v]
    print(f"distinct: forced {distinct_trajectories(recs)}/{len(recs)}; "
          f"unforced {distinct_trajectories([r for v in unforced.values() for r in v])}; "
          f"ministral {distinct_trajectories([r for v in ministral.values() for r in v])}")
    outcomes = collections.Counter(r["terminal_outcome"] for r in recs)
    unforced_outcomes = collections.Counter(r["terminal_outcome"] for v in unforced.values() for r in v)
    print("forced outcomes:", dict(outcomes), "| unforced on the same cells:", dict(unforced_outcomes))
    prose = sum(1 for r in recs for t in r["turns"] if t.get("refusal_prob", 0) > 0)
    print(f"forced prose turns (refusal_prob>0): {prose} of {sum(len(r['turns']) for r in recs)}")
    print(f"action sequences identical forced vs unforced: {identical}/{n}; differing {len(differing)}: "
          f"{collections.Counter((a, b) for _, _, a, b in differing)}")
    OUT.write_text(json.dumps({
        "cells": rows, "by_config": {k: dict(v) for k, v in bycfg.items()}, "total": dict(tot),
        "unforced_ci": ci_q, "held": inside, "outcomes": dict(outcomes), "unforced_outcomes": dict(unforced_outcomes),
        "identical_sequences": identical, "differing": differing, "prose_turns": prose,
    }, indent=2))


if __name__ == "__main__":
    main()
