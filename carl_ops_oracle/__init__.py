"""carl-ops containment oracle.

Authored independently of the state store implementation, from two inputs
only: ``docs/state-store-handoff.md`` and the carl-ops objective spec
(oracle-author copy). See ``docs/independence-provenance.md`` for the
provenance claim this package must uphold.

Input surface: serialized world-state snapshots, post hoc. This package
never consumes the action stream, tool-plane events, or policy verdicts,
and it imports nothing from the fixture or tool layers. Its only imports
from ``carl_ops_state`` are the two public primitives named in the handoff
doc: ``WorldState`` (deserialization) and the graph backend.
"""

from .oracle import (
    ContainmentOracle,
    OracleVerdict,
    RiggedFixtureError,
    evaluate_snapshots,
)

__all__ = [
    "ContainmentOracle",
    "OracleVerdict",
    "RiggedFixtureError",
    "evaluate_snapshots",
]
