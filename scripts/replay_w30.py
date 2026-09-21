#!/usr/bin/env python3
"""Offline stage backup. Reads recorded evidence; never calls a model or executes a tool."""
import argparse
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "runs/w30_readiness"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("case",help="A support case ID, or callback")
    ap.add_argument("--delay",type=float,default=0)
    args=ap.parse_args()
    if not 0 <= args.delay <= 10:
        ap.error("delay must be 0 to 10 seconds")
    print("RECORDED LAB REPLAY — synthetic effects; no live execution\n",flush=True)
    if args.case == "callback":
        r=json.loads((ROOT / "callback/auto_result.json").read_text())
        print("Planted compromised agent → fixed lab receiver on Spark2")
        print("Original carl-ops L2/L3 policies did not cover this new HTTP tool.")
        for d in r["outcomes"]:
            print(f"  {d['layer']}: {d['verdict']}  {d['detail']}")
        print(f"  L4: {r['auditor']['verdict']} — {r['auditor']['raw_reply']}")
        print(f"  Executed: {r['executed']}  Receiver receipts: {len(r['receipts_after'])}")
        print("  First L5 decision: SCRIPTED AUTO-APPROVAL")
        human=ROOT / "callback/human_result.json"
        if human.exists():
            h=json.loads(human.read_text())
            print(f"\nActual operator decision: {h['decision']['decision']}")
            print(f"  Separate gated action executed: {h['executed']}")
            print(f"  Receiver receipts: {len(h['receipts_after'])}")
        else:
            print("\nHuman comparison: pending; no human outcome recorded.")
        return
    if Path(args.case).name != args.case:
        ap.error("case must be a case ID")
    r=json.loads((ROOT / "support" / args.case / "result.json").read_text())
    c=r["case"]
    print(f"{c['id']}\nModel: {c['family']}  Config: {c['config']}  Seed: {c['seed']}")
    print(f"Planted susceptibility: {c['susceptible']}  Normal-task control: {c['control']}")
    for turn in r["inputs"]:
        time.sleep(args.delay)
        ti=turn["turn"]
        print(f"\nTurn {ti}: {turn['text']}\nInput verdict: {turn['verdict']}",flush=True)
        for call in r["calls"]:
            if call["turn"] == ti and "response" in call:
                message=call["response"]["choices"][0]["message"]
                content=message.get("content")
                if content:
                    print(f"Agent: {content}",flush=True)
        for a in r["actions"]:
            if a["turn"] == ti:
                print(f"Tool: {a['tool']} {json.dumps(a['args'])}")
                for d in a["decisions"]:
                    print(f"  {d['layer']}: {d['verdict']} {d.get('rule') or ''}")
                print(f"  Synthetic action executed: {a['executed']}",flush=True)
    print(f"\nObserved unauthorized action: {r['breach']}")
    print(f"Direct-baseline execution: {r['direct_executed']}  Later execution: {r['later_executed']}")
    print(f"Trial completed: {r['complete']}  Errors: {json.dumps(r['errors'])}")


if __name__ == "__main__":
    main()
