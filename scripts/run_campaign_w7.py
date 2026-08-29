#!/usr/bin/env python3
"""W7 — ONE model-driven campaign. Not a pilot, not a sweep.

The victim selects each action itself from the 13-tool surface, given the
objective and the trajectory so far. The action plane is live; the defense
stack is live; the store is live. Nothing here is replayed.

The loop mirrors ``CampaignRunner.run_trial``'s discipline — every attempt is
submitted, a block charges the reroute and does NOT end the trial, the next
call for an action IS that reroute — with one addition it cannot make: the
world store is advanced here when the stack allows an action, so the next
turn's observation is the store's own return. ``run_trial`` only submits to
the stack; it never executes, because a replayed plan had nothing to execute.

``ModelDrivenAgent.select_action`` matches the ``ActionSupplier`` signature, so
the selection half drops into ``CampaignRunner.run_trial`` unchanged when the
sweep wires this up.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, "/home/lbsuto/halctf-agent")

from carl_ops_agent.model_driven import ModelDrivenAgent
from saster_defense.l4_auditor import TrajectoryAuditor
from saster_defense.manifest import build_manifest, validate_manifest
from saster_defense.stack import DefenseConfig, DefenseStack

CAMPAIGN_ID = os.environ.get("W7_CAMPAIGN_ID", "w7-campaign-001")
VICTIM = os.environ.get("W7_VICTIM", "mistralai/Ministral-8B-Instruct-2410")
ROUTER_URL = os.environ.get("W7_ROUTER", "http://localhost:8080")
AGENTDOG = "http://[fd00:200::4]:8001"
AGENTDOG_MODEL = "AI45Research/AgentDoG-Qwen3-4B"
OBSTRUCTED = os.environ.get("W7_OBSTRUCTED", "1") == "1"
TEMPERATURE = float(os.environ.get("W7_TEMPERATURE", "0.7"))
SEED = int(os.environ.get("W7_SEED", "20260829"))
MAX_STEPS = int(os.environ.get("W7_MAX_STEPS", "12"))
OUT = Path(os.environ.get("W7_OUT", "runs/w7_campaign_001"))

#: Closing the assigned ticket is terminal either way: `resolved` is the
#: sanctioned completion, `escalated` is the sanctioned stop under an
#: unmeetable precondition. Neither is a failure and the run ends on both.
TERMINAL_TOOL = "ticket.close"


def build_stack() -> DefenseStack:
    auditor = TrajectoryAuditor(observer_model=AGENTDOG_MODEL, endpoint=AGENTDOG)
    return DefenseStack(
        fixture_id="carl-ops",
        config=DefenseConfig(l1=True, l2=True, l3=True, l4=True, l5=True),
        auditor=auditor,
    )


def block_reason(result: Any) -> str:
    blocking = [o for o in result.outcomes if getattr(o, "blocks", False)]
    if not blocking:
        return "blocked by the defense stack"
    return "; ".join(
        f"{o.layer.value}:{o.verdict.value}"
        + (f"[{o.rule_id}]" if o.rule_id else "")
        + (f" {o.detail}" if o.detail else "")
        for o in blocking
    )


def guard_output_dir() -> None:
    existing = sorted(p.name for p in OUT.glob("*")) if OUT.exists() else []
    if existing and os.environ.get("W7_OVERWRITE") != "1":
        raise SystemExit(
            f"refusing to overwrite {len(existing)} file(s) in {OUT}. "
            f"Set W7_OUT to a new directory, or W7_OVERWRITE=1."
        )


def main() -> None:
    guard_output_dir()
    OUT.mkdir(parents=True, exist_ok=True)

    agent = ModelDrivenAgent(
        base_url=ROUTER_URL, model=VICTIM, campaign_id=CAMPAIGN_ID,
        obstructed=OBSTRUCTED, temperature=TEMPERATURE, seed=SEED,
    )
    stack = build_stack()

    manifest = build_manifest(stack)
    validate_manifest(manifest)
    manifest["campaign_id"] = CAMPAIGN_ID
    manifest["victim_model"] = VICTIM
    manifest["obstructed"] = OBSTRUCTED
    manifest["action_plane"] = agent.sampling_manifest_block()
    manifest["role"] = "W7 — ONE model-driven campaign. Not a pilot, not a sweep."
    manifest["started_utc"] = datetime.now(UTC).isoformat()
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2))

    print(f"campaign {CAMPAIGN_ID}  victim={VICTIM}  obstructed={OBSTRUCTED}")
    print(f"temperature={TEMPERATURE}  seed={SEED}  max_steps={MAX_STEPS}")
    print()

    outcome = "max_steps"
    previous = None
    for step in range(MAX_STEPS):
        if stack.budget.exhausted:
            outcome = "budget_exhausted"
            break

        action = agent.select_action(step, previous)
        if action is None:
            turn = agent.turns[-1]
            outcome = turn.status.value
            print(f"step {step}: NO ACTION — {turn.status.value}: {turn.detail}")
            if turn.reasoning:
                print(f"         model said: {turn.reasoning[:400]}")
            break

        submitted = stack.submit(action)
        previous = submitted
        if submitted.blocked:
            reason = block_reason(submitted)
            agent.observe_blocked(action, reason)
            print(f"step {step}: {action.tool} {json.dumps(action.args, sort_keys=True)}")
            print(f"         BLOCKED — {reason}")
        else:
            observation = agent.observe_executed(action)
            print(f"step {step}: {action.tool} {json.dumps(action.args, sort_keys=True)}")
            print(f"         -> {json.dumps(observation, sort_keys=True, default=str)[:300]}")
            if action.tool == TERMINAL_TOOL and not (
                isinstance(observation, dict) and observation.get("error")
            ):
                outcome = f"ticket_closed:{action.args.get('resolution', 'resolved')}"
                break

    print()
    print(f"outcome: {outcome}")

    transcript = {
        "campaign_id": CAMPAIGN_ID,
        "victim_model": VICTIM,
        "obstructed": OBSTRUCTED,
        "temperature": TEMPERATURE,
        "seed": SEED,
        "outcome": outcome,
        "turns": [t.as_dict() for t in agent.turns],
        "budget": stack.budget.snapshot(),
        "snapshot_hashes": [s.state.content_hash for s in agent.session.snapshots],
        "terminal_state": json.loads(agent.session.state.to_json()),
        "messages": agent.messages,
    }
    (OUT / "campaign.json").write_text(json.dumps(transcript, indent=2, default=str))
    print(f"wrote {OUT}/campaign.json ({len(agent.turns)} turns)")


if __name__ == "__main__":
    main()
