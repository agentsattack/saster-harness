"""Containment latency as a tagged, censoring-aware type (Class 9).

A right-censored latency is not a number and must not enter a mean. This
module gives it a type that refuses arithmetic, an aggregator that raises
when a censored value is present, and a step-average that excludes nulls
rather than coercing them to zero.
"""

from __future__ import annotations

import statistics
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any


class CensoredInAggregate(TypeError):
    """An aggregate over latencies met a right-censored value. Report the
    censored count beside a survival-style summary; never impute."""


class Censored:
    """A right-censored latency: the breach happened and nothing detected it.
    Every arithmetic and ordering operation raises, so ``statistics.mean``
    and friends fail on a collection containing one."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "Censored()"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Censored)

    def __hash__(self) -> int:
        return hash("Censored")

    def _refuse(self, *_a: Any) -> Any:
        raise CensoredInAggregate(
            "a right-censored latency has no value; report the censored count, "
            "never impute one"
        )

    __float__ = __int__ = __add__ = __radd__ = __sub__ = __rsub__ = _refuse
    __mul__ = __rmul__ = __truediv__ = __rtruediv__ = __lt__ = __le__ = _refuse
    __gt__ = __ge__ = __neg__ = __abs__ = _refuse


CENSORED = Censored()


@dataclass(frozen=True)
class LatencyObservation:
    """One breaching record's latency: an int, or :data:`CENSORED`."""

    record_id: str
    value: int | Censored


def latency_of(record: dict[str, Any]) -> int | Censored | None:
    """The record's containment latency as a typed value.

    ``None`` when there was no breach (there is no latency to report),
    :data:`CENSORED` when the breach went undetected, else the int."""
    oracle = record.get("oracle") or {}
    if not oracle.get("breach"):
        return None
    cl = record.get("containment_latency") or {}
    if cl.get("censored"):
        return CENSORED
    value = cl.get("value")
    if value is None:
        raise ValueError("breach detected but containment_latency.value is null")
    return int(value)


def latencies(records: Iterable[dict[str, Any]]) -> list[LatencyObservation]:
    out: list[LatencyObservation] = []
    for r in records:
        lat = latency_of(r)
        if lat is None:
            continue
        rid = f"{r.get('campaign_id')}/{r.get('trial_index')}"
        out.append(LatencyObservation(rid, lat))
    return out


def mean_latency(obs: Sequence[LatencyObservation | int | Censored]) -> float:
    """Mean over UNCENSORED observations only — and it raises, rather than
    silently dropping, if any observation is censored. Use
    :func:`summarize_latency` for a collection that may contain censoring."""
    values = [o.value if isinstance(o, LatencyObservation) else o for o in obs]
    if any(isinstance(v, Censored) for v in values):
        raise CensoredInAggregate(
            "mean() over a collection containing a right-censored latency; use "
            "summarize_latency() and report the censored count"
        )
    if not values:
        raise ValueError("mean of no latencies")
    return statistics.fmean(float(v) for v in values)  # type: ignore[arg-type]


def summarize_latency(obs: Sequence[LatencyObservation]) -> dict[str, Any]:
    """The honest aggregate: censored count beside the uncensored summary."""
    censored = [o for o in obs if isinstance(o.value, Censored)]
    uncensored = sorted(int(o.value) for o in obs if not isinstance(o.value, Censored))
    return {
        "n_breached": len(obs),
        "n_censored": len(censored),
        "n_uncensored": len(uncensored),
        "censored_proportion": (len(censored) / len(obs)) if obs else None,
        "uncensored_median": statistics.median(uncensored) if uncensored else None,
        "uncensored_min": uncensored[0] if uncensored else None,
        "uncensored_max": uncensored[-1] if uncensored else None,
        "imputed": False,
    }


def step_average(values: Iterable[int | None]) -> float | None:
    """Average of step indices, excluding nulls. A null is not 0; if every
    value is null there is no average, and the answer is None, not 0.0."""
    present = [int(v) for v in values if v is not None]
    return statistics.fmean(present) if present else None


__all__ = [
    "CENSORED",
    "Censored",
    "CensoredInAggregate",
    "LatencyObservation",
    "latencies",
    "latency_of",
    "mean_latency",
    "step_average",
    "summarize_latency",
]
