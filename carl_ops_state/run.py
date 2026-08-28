"""The run driver: apply a declared action sequence, snapshotting at t0 and
after every mutating action, while collecting the tool-plane event list.

Snapshots are content-addressable (each carries its state's hash). Read
actions contribute tool events but no snapshot; a single exec step
contributes one snapshot (its composite effect) and one exec tool event,
never the constituent operations.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .actions import Action, ToolEvent
from .model import WorldState
from .transition import TransitionRelation


@dataclass(frozen=True)
class Snapshot:
    index: int  # 0 == t0, then one per mutating action
    action: str | None  # the action that produced this snapshot (None at t0)
    state: WorldState

    @property
    def hash(self) -> str:
        return self.state.content_hash


@dataclass(frozen=True)
class RunResult:
    snapshots: tuple[Snapshot, ...]
    tool_events: tuple[ToolEvent, ...]

    @property
    def final_state(self) -> WorldState:
        return self.snapshots[-1].state

    @property
    def initial_state(self) -> WorldState:
        return self.snapshots[0].state

    def tool_names(self) -> list[str]:
        return [e.tool for e in self.tool_events]

    def states(self) -> list[WorldState]:
        return [s.state for s in self.snapshots]


def apply_path(
    relation: TransitionRelation,
    initial_state: WorldState,
    actions: Sequence[Action],
) -> RunResult:
    """Apply ``actions`` in order. Raises ``PreconditionError`` on the first
    action whose precondition fails — i.e. the path does not apply cleanly."""
    snapshots = [Snapshot(0, None, initial_state)]
    events: list[ToolEvent] = []
    state = initial_state
    index = 0
    for action in actions:
        events.extend(action.tool_events())
        state = relation.apply(state, action)  # checks precondition
        if action.mutating:
            index += 1
            snapshots.append(Snapshot(index, action.name, state))
    return RunResult(tuple(snapshots), tuple(events))


__all__ = ["RunResult", "Snapshot", "apply_path"]
