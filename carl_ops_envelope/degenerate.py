"""The uniform-exact detector — a distribution that cannot be a measurement.

Stage 1 defect D7. ``envelopes()`` accepted any ``probs`` and returned three
numbers. An exactly uniform softmax is what a chat template that silently
drops the tool call produces (every candidate renders to the same tokens),
and it validated as ``declared_in = 11/13`` at every step of W7b. The chat
scorer's slicing guard catches that one cause; this catches the shape,
whatever produced it, at the one point every surface's distribution passes
through.
"""

from __future__ import annotations

from collections.abc import Sequence


class DegenerateDistribution(ValueError):
    """A candidate distribution that cannot carry a measurement: empty, a
    single candidate (softmax is 1.0 by construction), or exactly uniform."""


#: Two probabilities within 10^-6 of 1/N are "exactly" uniform.
UNIFORM_DECIMALS = 6


def is_uniform_exact(probs: Sequence[float], decimals: int = UNIFORM_DECIMALS) -> bool:
    n = len(probs)
    if n == 0:
        return False
    tol = 10.0 ** (-decimals)
    return all(abs(float(p) - 1.0 / n) < tol for p in probs)


def assert_not_degenerate_distribution(probs: Sequence[float]) -> None:
    """Raise :class:`DegenerateDistribution` rather than let a number out."""
    n = len(probs)
    if n == 0:
        raise DegenerateDistribution("empty candidate set: nothing to distribute mass over")
    if n == 1:
        raise DegenerateDistribution(
            "single candidate: a softmax over one entry is 1.0 by construction"
        )
    if is_uniform_exact(probs):
        raise DegenerateDistribution(
            f"exactly uniform over {n} candidates to {UNIFORM_DECIMALS} decimals: the "
            f"distribution carries no information about the model"
        )


__all__ = [
    "UNIFORM_DECIMALS",
    "DegenerateDistribution",
    "assert_not_degenerate_distribution",
    "is_uniform_exact",
]
