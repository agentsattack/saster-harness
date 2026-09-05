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

    @property
    def chat_template_kwargs(self) -> dict[str, Any]:
        return template_kwargs_for(self.model)


FAMILIES: dict[str, Family] = {
    "qwen3": Family("qwen3", "Qwen/Qwen3-8B", "hermes", "spark3 192.168.1.228:8000"),
    "mistral": Family(
        "mistral", "mistralai/Ministral-8B-Instruct-2410", "mistral", "spark6 192.168.1.208:8000"
    ),
}


def family_for_model(model: str) -> Family:
    for fam in FAMILIES.values():
        if fam.model == model:
            return fam
    raise KeyError(f"no victim family serves {model!r}; registered: {sorted(FAMILIES)}")


__all__ = ["FAMILIES", "Family", "family_for_model"]
