"""Marker index units, and the joiner that refuses to subtract across them.

Catalogue C6 (schema Amendment 6): the oracle grades snapshots and the
defense stack indexes actions; ``containment_latency`` subtracted one from
the other and produced a plausible integer every time. Amendment 6 fixed the
block-wide space; this makes the unit explicit PER marker
(``markers.units``, schema Amendment 11) and gives the assembler a tagged
value type whose subtraction raises on a unit mismatch instead of computing.
"""

from __future__ import annotations

from dataclasses import dataclass

ACTION_INDEX = "action_index"
SNAPSHOT_INDEX = "snapshot_index"
TURN_INDEX = "turn_index"

#: The closed unit vocabulary.
UNITS: frozenset[str] = frozenset({ACTION_INDEX, SNAPSHOT_INDEX, TURN_INDEX})

#: The unit each marker in the schema ``markers`` block is expressed in.
#: All action space, matching ``index_space: "action"`` (Amendment 6): the
#: one space every marker can be expressed in, and the one the transcript
#: is read in. ``onset_dist`` is a distribution over action indices.
MARKER_UNITS: dict[str, str] = {
    "onset_dist": ACTION_INDEX,
    "explanatory_divergence": ACTION_INDEX,
    "point_of_no_return": ACTION_INDEX,
    "breach_step_index": ACTION_INDEX,
    "first_detection_step": ACTION_INDEX,
}

#: The unit of every value in ``index_map.snapshot_space_markers``.
SNAPSHOT_SPACE_UNIT = SNAPSHOT_INDEX


class UnitMismatch(TypeError):
    """Arithmetic was attempted between two markers in different units."""


@dataclass(frozen=True)
class MarkerIndex:
    """A marker value tagged with its unit. ``value`` may be None (a marker
    that did not localize anything); subtraction then yields None rather
    than a number, so a null never becomes a 0."""

    value: int | None
    unit: str

    def __post_init__(self) -> None:
        if self.unit not in UNITS:
            raise ValueError(f"unknown marker unit {self.unit!r}; must be one of {sorted(UNITS)}")
        if self.value is not None and (isinstance(self.value, bool) or not isinstance(self.value, int)):
            raise TypeError(f"marker value must be int or None, got {self.value!r}")

    def __sub__(self, other: MarkerIndex) -> int | None:
        if not isinstance(other, MarkerIndex):
            raise UnitMismatch(
                f"cannot subtract a bare {type(other).__name__} from a {self.unit} marker; "
                f"tag it with its unit first"
            )
        if self.unit != other.unit:
            raise UnitMismatch(
                f"cannot subtract {other.unit} from {self.unit}: the two markers are in "
                f"different index spaces (this is the W9 latency defect)"
            )
        if self.value is None or other.value is None:
            return None
        return self.value - other.value


def subtract(a: MarkerIndex, b: MarkerIndex) -> int | None:
    """``a - b`` with the unit check; the assembler's only subtraction."""
    return a - b


__all__ = [
    "ACTION_INDEX",
    "MARKER_UNITS",
    "SNAPSHOT_INDEX",
    "SNAPSHOT_SPACE_UNIT",
    "TURN_INDEX",
    "UNITS",
    "MarkerIndex",
    "UnitMismatch",
    "subtract",
]
