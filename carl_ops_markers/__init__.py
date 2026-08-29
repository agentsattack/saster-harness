"""carl-ops marker layer.

Computes the two trajectory markers that are derived rather than observed —
``point_of_no_return`` and ``explanatory_divergence`` — and assembles the
schema ``markers`` block. ``breach_step_index`` (oracle) and
``first_detection_step`` (defense stack) are passed through; ``onset_dist`` is
deliberately not estimated this sweep. See markers.py.
"""

from __future__ import annotations

from .markers import (
    ASSIGNED_TICKET,
    DECLARED_IN_ENVELOPE_FLOOR,
    ONSET_DIST_NOT_ESTIMATED,
    PROHIBITION_OUT_CEILING,
    explanatory_divergence,
    make_admissible,
    marker_block,
    objective_complete,
    point_of_no_return,
)

__all__ = [
    "ASSIGNED_TICKET",
    "DECLARED_IN_ENVELOPE_FLOOR",
    "PROHIBITION_OUT_CEILING",
    "ONSET_DIST_NOT_ESTIMATED",
    "objective_complete",
    "make_admissible",
    "point_of_no_return",
    "explanatory_divergence",
    "marker_block",
]
