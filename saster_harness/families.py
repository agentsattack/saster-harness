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


@dataclass(frozen=True)
class JudgeFamily:
    """A judge-only registry entry (addendum §W-2): a family that judges but
    is never a victim, so the Arm A rider does not run over it. ``role`` is
    ``primary`` or ``fallback``; switching between them is a manifest field
    (``judge.registry.role``), never a silent swap."""
    key: str
    model: str
    lineage: str
    node: str
    role: str
    gate_report: str  # runs/w23_judge_gate_<model>_<prompt>.json, the §N result


JUDGE_ONLY_FAMILIES: dict[str, JudgeFamily] = {
    "llama33_70b": JudgeFamily("llama33_70b", "RedHatAI/Llama-3.3-70B-Instruct-FP8-dynamic", "meta-llama-3.3",
                               "spark9 [fd00:200::9]:8000", "primary",
                               "runs/w23_judge_gate_Llama-3.3-70B-Instruct-FP8-dynamic_scoped.json"),
    "llama31_8b": JudgeFamily("llama31_8b", "meta-llama/Llama-3.1-8B-Instruct", "meta-llama-3.1",
                              "spark8 [fd00:200::8]:8000 (served on demand)", "fallback",
                              "runs/w23_judge_gate_Llama-3.1-8B-Instruct_scoped.json"),
}


def judge_registry_for(model: str) -> dict[str, Any] | None:
    """The manifest's ``judge.registry`` block for a judge model: the victim
    family it belongs to, or the judge-only entry with its role and §N gate
    report, or None for an unregistered judge model."""
    for fam in FAMILIES.values():
        if fam.model == model:
            return {"key": fam.key, "kind": "victim_family", "role": "primary", "gate_report": None}
    for jf in JUDGE_ONLY_FAMILIES.values():
        if jf.model == model:
            return {"key": jf.key, "kind": "judge_only", "lineage": jf.lineage, "role": jf.role,
                    "gate_report": jf.gate_report, "node": jf.node}
    return None


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
    """Every registered victim family other than the victim's, in registry
    order — the Arm C judge panel for that victim (addendum §W). The first
    entry is what :func:`judge_family_for` returns, so the two cannot
    disagree. Judge-only families (§W-2) are appended by
    :func:`judge_panel_for`."""
    victim = family_for_model(victim_model)
    return [f for f in FAMILIES.values() if f.key != victim.key]


def judge_panel_for(victim_model: str) -> list[str]:
    """Model ids of the Arm C panel for a victim: the other victim families,
    then the judge-only families whose role is ``primary``. No trajectory is
    judged by its own family."""
    return ([f.model for f in judge_families_for(victim_model)]
            + [jf.model for jf in JUDGE_ONLY_FAMILIES.values() if jf.role == "primary"])


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


__all__ = ["FAMILIES", "Family", "JUDGE_ONLY_FAMILIES", "JudgeFamily", "family_for_model", "family_key_for_model",
           "judge_families_for", "judge_family_for", "judge_panel_for", "judge_registry_for", "tool_choice_for"]
