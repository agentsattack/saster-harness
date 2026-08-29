"""carl-ops per-trial trajectory-record assembly (W6).

Joins the three inputs named in ``docs/trajectory-assembly.md`` — the victim
deployment's event records, the containment oracle's verdict, and the marker
layer — into one validated ``saster.trajectory.v1`` trajectory record per
trial.

Kept out of :mod:`carl_ops_trajectory` on purpose: that package is the frozen
contract and its validator is stdlib-only and dependency-free. The assembler
is a *consumer* of the contract and imports the oracle, the marker layer, the
envelope scorer's output, and the agent's widening derivation, so it lives
beside them rather than inside the schema package.
"""

from __future__ import annotations

from carl_ops_markers import ONSET_DIST_NOT_ESTIMATED

from .assembler import (
    RecordInvalid,
    TrajectoryAssemblyError,
    assemble_trajectory_record,
    derive_terminal_outcome,
    oracle_block,
)

__all__ = [
    "assemble_trajectory_record",
    "derive_terminal_outcome",
    "oracle_block",
    "TrajectoryAssemblyError",
    "RecordInvalid",
    "ONSET_DIST_NOT_ESTIMATED",
]
