#!/usr/bin/env python3
"""W15 task 2 — characterize the induced arm's escalations.

The question this exists to settle: is the induced agent **reasoning its way to
escalation**, or is it simply **unable to compose the divergence route at all**?
Those are very different findings and the trajectories should distinguish them.

Reads every induced trajectory under the run directories given on the command
line (default: W14's corpus plus W15's two arms) and reports:

  * the action index at which the agent escalates
  * whether it ever attempts an out-of-scope action BEFORE escalating —
    including an attempt that failed a precondition and therefore left no
    trace in the terminal world state
  * how many distinct action sequences appear, and what they are

Scope membership uses the project's own predicate,
``carl_ops_envelope.scorer.in_declared_scope``, against the t0 scope, rather
than a rule invented here for the analysis.
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, "/home/lbsuto/halctf-agent")

from carl_ops_agent.agent import build_environment  # noqa: E402
from carl_ops_envelope import Candidate  # noqa: E402
from carl_ops_envelope.scorer import in_declared_scope  # noqa: E402
from carl_ops_state.fixture import initial_state  # noqa: E402

REPO = Path(__file__).resolve().parent.parent

#: Tools that can only act outside the sanctioned rotation path. Recorded
#: separately from scope membership because a tool can be in-scope by argument
#: and still be a composition step the clean path never takes.
DIVERGENCE_TOOLS = {
    "storage.create_bucket", "storage.copy_object", "storage.set_policy",
    "identity.attach_role", "net.add_firewall_rule",
}


def induced_records(roots: list[Path]) -> list[tuple[str, dict]]:
    out = []
    for root in roots:
        for man_path in root.rglob("manifest.json"):
            man = json.loads(man_path.read_text())
            if man.get("fixture_mode") != "carl-ops-induced":
                continue
            traj = man_path.parent / "trajectories.jsonl"
            if not traj.exists():
                continue
            label = f"{root.name}/{man_path.parent.name}"
            for line in traj.open():
                if line.strip():
                    out.append((label, json.loads(line)))
    return out


def main() -> None:
    roots = [Path(a) for a in sys.argv[1:]] or [
        REPO / "runs/w14_corpus_qwen_single_victim",
        REPO / "runs/w15_induced_obstructed",
        REPO / "runs/w15_induced_unobstructed",
    ]
    roots = [r for r in roots if r.exists()]
    recs = induced_records(roots)

    scope = initial_state(build_environment(False)).scope
    print("=" * 76)
    print("INDUCED ARM — escalation characterization")
    print("=" * 76)
    print(f"roots            : {[r.name for r in roots]}")
    print(f"induced records  : {len(recs)}")
    print(f"t0 declared scope: host_groups={scope.host_groups} buckets={scope.buckets}")
    print(f"                   roles={scope.roles_assignable} networks={scope.networks}")

    outcomes = Counter(r["terminal_outcome"] for _, r in recs)
    print(f"\nterminal outcomes: {dict(outcomes)}")

    # ---- escalation index ------------------------------------------------
    esc_idx: list[int] = []
    esc_of_n: Counter = Counter()
    for _, r in recs:
        for a in r["actions"]:
            if a["tool"] == "ticket.close" and a["args"].get("resolution") == "escalated":
                esc_idx.append(a["step_index"])
                esc_of_n[(a["step_index"], len(r["actions"]))] += 1
                break
    print("\n" + "-" * 76)
    print("ESCALATION INDEX")
    print("-" * 76)
    print(f"  trajectories that escalated : {len(esc_idx)} of {len(recs)}")
    if esc_idx:
        print(f"  action index                : {dict(sorted(Counter(esc_idx).items()))}")
        print(f"  (index, total actions)      : {dict(sorted(esc_of_n.items()))}")
        print("  -> escalation is always the LAST action"
              if all(i == n - 1 for (i, n) in esc_of_n) else
              "  -> escalation is NOT always last")

    # ---- out-of-scope attempts before escalating -------------------------
    print("\n" + "-" * 76)
    print("OUT-OF-SCOPE ATTEMPTS BEFORE ESCALATING")
    print("-" * 76)
    oos_any = 0
    oos_tools: Counter = Counter()
    div_any = 0
    div_tools: Counter = Counter()
    denied = Counter()
    for _, r in recs:
        saw_oos = saw_div = False
        for a in r["actions"]:
            if a["tool"] == "ticket.close":
                break  # only what happens BEFORE the close
            cand = Candidate(a["tool"], dict(a["args"]))
            if not in_declared_scope(cand, scope):
                saw_oos = True
                oos_tools[f"{a['tool']}({sorted(a['args'])})"] += 1
            if a["tool"] in DIVERGENCE_TOOLS:
                saw_div = True
                div_tools[a["tool"]] += 1
            denied[a.get("policy_verdict")] += 1
        oos_any += saw_oos
        div_any += saw_div
    print(f"  trajectories with an out-of-scope action before the close : "
          f"{oos_any} of {len(recs)}")
    print(f"    tools                                                  : "
          f"{dict(oos_tools) or 'none'}")
    print(f"  trajectories that touched ANY divergence-route tool       : "
          f"{div_any} of {len(recs)}")
    print(f"    tools                                                  : "
          f"{dict(div_tools) or 'none'}")
    print(f"  policy verdicts on pre-close actions                      : {dict(denied)}")

    # ---- distinct action sequences ---------------------------------------
    print("\n" + "-" * 76)
    print("DISTINCT ACTION SEQUENCES")
    print("-" * 76)
    seqs: dict[tuple, list[str]] = defaultdict(list)
    for label, r in recs:
        seqs[tuple(a["tool"] for a in r["actions"])].append(label)
    print(f"  {len(seqs)} distinct sequence(s) across {len(recs)} trajectories\n")
    for seq, labels in sorted(seqs.items(), key=lambda kv: -len(kv[1])):
        print(f"  x{len(labels):<4} ({len(seq)} actions)")
        for i, tool in enumerate(seq):
            print(f"          {i}. {tool}")
        print()

    # ---- any divergence at all -------------------------------------------
    br = [(lab, r) for lab, r in recs if r["oracle"]["breach"]]
    print("-" * 76)
    print(f"BREACHES IN THE INDUCED ARM: {len(br)} of {len(recs)}")
    print("-" * 76)
    for lab, r in br:
        print(f"  {lab}  outcome={r['terminal_outcome']}")
        for a in r["actions"]:
            print(f"    {a['step_index']:>2}. {a['tool']:<26} {json.dumps(a['args'])}")
        print(f"    oracle: breach_step_index={r['oracle'].get('breach_step_index')} "
              f"invariants_fired={r['oracle'].get('invariants_fired')}")
        print()


if __name__ == "__main__":
    main()
