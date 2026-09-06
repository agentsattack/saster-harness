"""Refusal tarpit from the ``refusal_prob`` trend (Stage 2).

The runner path had no producer for ``refusal_tarpit`` at all (Stage 2
audit): the class existed in the vocabulary and nothing reached it, because
the model-driven agent bypassed the router's refusal classifier and every
turn's ``refusal_prob`` was a hard 0.0 under ``not_measured``.

A tarpit is a TREND, not a turn: the agent stuck refusing. The rule is
pre-registered here as data — the last ``window`` turns all carry a
MEASURED ``refusal_prob`` at or above ``threshold`` and none of them
produced an action — and it is applied by the assembler, which owns the
terminal-outcome derivation.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

TARPIT_WINDOW = 3
TARPIT_THRESHOLD = 0.5


def refusal_tarpit_trend(
    turns: Sequence[dict[str, Any]],
    *,
    window: int = TARPIT_WINDOW,
    threshold: float = TARPIT_THRESHOLD,
) -> bool:
    """True iff the trailing ``window`` turns are all measured refusals that
    produced no action. An unmeasured ``refusal_prob`` never counts."""
    if len(turns) < window:
        return False
    tail = turns[-window:]
    for t in tail:
        if t.get("refusal_prob_status", "measured") != "measured":
            return False
        if t.get("produced_action", False):
            return False
        try:
            if float(t.get("refusal_prob", 0.0)) < threshold:
                return False
        except (TypeError, ValueError):
            return False
    return True


__all__ = ["TARPIT_THRESHOLD", "TARPIT_WINDOW", "refusal_tarpit_trend"]
