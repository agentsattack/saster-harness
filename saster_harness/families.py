"""The victim family registry — one entry per chat-template family served.

Arm A of ``docs/multi-model-instrument-suite.md``: a real measurement varies
with the model; an instrument artifact does not. The round-trip rider
(``tests/test_instrument_arm_a_roundtrip.py``) runs over every family here,
because a scorer that works for one template and silently drops the tool
call for another is catalogue C4 with a family index.

``chat_template_kwargs`` is read from the one table the action plane reads
(:data:`saster_harness.campaign.TEMPLATE_KWARGS_BY_MODEL`), so the registry
cannot drift from what the agent samples under.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from saster_harness.campaign import template_kwargs_for


@dataclass(frozen=True)
class Family:
    key: str
    model: str
    tool_call_parser: str  # the vLLM parser the node serves with
    node: str
    #: Request-level tool-choice constraint the family runs under. Ministral
    #: echoes the tool result as prose on the turn after an observation and
    #: ends the trial; ``required`` turns that into a tool call (a flag, not
    #: a build — verified 2026-09-05 on the stored turn-1 prompt). Addendum
    #: §L states what that makes unobservable for the family.
    tool_choice: str | None = None

    @property
    def chat_template_kwargs(self) -> dict[str, Any]:
        return template_kwargs_for(self.model)


FAMILIES: dict[str, Family] = {
    "qwen3": Family("qwen3", "Qwen/Qwen3-8B", "hermes", "spark3 192.168.1.228:8000"),
    "mistral": Family(
        "mistral", "mistralai/Ministral-8B-Instruct-2410", "mistral", "spark6 192.168.1.208:8000",
        tool_choice="required",
    ),
    # Addendum §W (2026-09-12): victim family C and judge family 3. Served
    # TP=4 on spark1–spark4 by its own recipe (dsv41/), thinking off by the
    # server's default template kwargs and stated explicitly in
    # TEMPLATE_KWARGS_BY_MODEL. Registered, not measured, at entry.
    "deepseek": Family(
        "deepseek", "deepseek-v4.1-flash", "deepseek_v41", "spark1 127.0.0.1:8000 (TP=4 spark1-4)",
    ),
}


def tool_choice_for(model: str) -> str | None:
    try:
        return family_for_model(model).tool_choice
    except KeyError:
        return None


def judge_family_for(victim_model: str) -> Family:
    """The vendor-shaped judge is never the victim's own model: it is the
    OTHER registered family (Ministral judges Qwen, Qwen judges Ministral).
    Raises if the victim is unregistered or there is no other family."""
    victim = family_for_model(victim_model)
    others = [f for f in FAMILIES.values() if f.key != victim.key]
    if not others:
        raise KeyError(f"no second family to judge {victim_model!r}")
    return others[0]


def judge_families_for(victim_model: str) -> list[Family]:
    """Every registered family other than the victim's, in registry order —
    the Arm C judge panel for that victim (addendum §W). The first entry is
    what :func:`judge_family_for` returns, so the two cannot disagree."""
    victim = family_for_model(victim_model)
    return [f for f in FAMILIES.values() if f.key != victim.key]


def family_key_for_model(model: str) -> str | None:
    """The registry key serving ``model``, or None for an unregistered model —
    the manifest's ``family`` field for a judge or victim."""
    try:
        return family_for_model(model).key
    except KeyError:
        return None


def family_for_model(model: str) -> Family:
    for fam in FAMILIES.values():
        if fam.model == model:
            return fam
    raise KeyError(f"no victim family serves {model!r}; registered: {sorted(FAMILIES)}")


__all__ = ["FAMILIES", "Family", "family_for_model", "family_key_for_model", "judge_families_for",
           "judge_family_for", "tool_choice_for"]
