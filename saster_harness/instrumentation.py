"""Configurable instrumentation — observation planes and profiles.

saster-harness observes an agent through up to three **planes**:

- ``tool``    — wire MITM of the agent's tool/network calls. This is the
  v0.4.0 behaviour and the only plane the ``standard`` profile activates.
- ``model``   — the inference-API proxy: the model's own inputs/outputs,
  where the reasoning signal lives. Cheap relative to process hooks.
- ``process`` — in-agent hooks. This phase ships the *interface* plus one
  reference adapter (:class:`CallbackProcessPlaneAdapter`); concrete
  production adapters are downstream work.

Detectors declare which planes they need via ``requires_planes``. When a
required plane is not active under the current profile the detector is
reported **unavailable** — explicitly distinct from **clean**: an inactive
plane means "not observed", never "observed and fine".

A **profile** is a named, runtime-switchable set of active planes.
``standard`` (the default) activates ``tool`` only and reproduces v0.4.0
exactly. Switching profiles (manually or via escalation) activates
additional planes for subsequent turns; every transition is recorded so a
trajectory shows which planes were live when.

This is a **research instrument**, not a production control plane — see
``docs/instrumentation.md``.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import TypeVar

_D = TypeVar("_D")


class ObservationPlane(str, Enum):
    """A source of agent observations."""

    TOOL = "tool"
    MODEL = "model"
    PROCESS = "process"


# Built-in profiles: name -> the planes it activates. ``standard`` is the
# default and MUST stay tool-only so it reproduces v0.4.0 exactly.
_BUILTIN_PROFILES: dict[str, frozenset[ObservationPlane]] = {
    "standard": frozenset({ObservationPlane.TOOL}),
    "model": frozenset({ObservationPlane.TOOL, ObservationPlane.MODEL}),
    "full": frozenset(
        {ObservationPlane.TOOL, ObservationPlane.MODEL, ObservationPlane.PROCESS}
    ),
}

DEFAULT_PROFILE = "standard"


@dataclass(frozen=True)
class InstrumentationProfile:
    """A named set of active observation planes."""

    name: str
    planes: frozenset[ObservationPlane]


def _coerce_planes(planes: Iterable[str | ObservationPlane]) -> frozenset[ObservationPlane]:
    out: set[ObservationPlane] = set()
    for p in planes:
        out.add(p if isinstance(p, ObservationPlane) else ObservationPlane(p))
    if not out:
        raise ValueError("a profile must activate at least one plane")
    return frozenset(out)


def resolve_profile(
    name: str,
    custom_profiles: Mapping[str, Sequence[str]] | None = None,
) -> InstrumentationProfile:
    """Resolve a profile name to its plane set.

    Custom profiles (operator-defined) shadow built-ins of the same name.
    Raises :class:`KeyError` for an unknown name and :class:`ValueError`
    for an invalid plane.
    """
    custom_profiles = custom_profiles or {}
    if name in custom_profiles:
        return InstrumentationProfile(name, _coerce_planes(custom_profiles[name]))
    if name in _BUILTIN_PROFILES:
        return InstrumentationProfile(name, _BUILTIN_PROFILES[name])
    raise KeyError(
        f"unknown instrumentation profile {name!r}; known: "
        f"{sorted(set(_BUILTIN_PROFILES) | set(custom_profiles))}"
    )


def detector_required_planes(detector: object) -> frozenset[ObservationPlane]:
    """The planes a detector needs. Defaults to ``{tool}`` — every v0.4.0
    detector requires only the wire plane, so it stays available under
    ``standard`` with no per-detector change."""
    req = getattr(detector, "requires_planes", (ObservationPlane.TOOL,))
    return _coerce_planes(req)


@dataclass
class ProfileTransition:
    """A recorded change of active profile within a trajectory."""

    from_profile: str
    to_profile: str
    reason: str
    overhead_seconds: float
    session_id: str | None = None
    turn_idx: int | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "from_profile": self.from_profile,
            "to_profile": self.to_profile,
            "reason": self.reason,
            "overhead_seconds": round(self.overhead_seconds, 6),
            "session_id": self.session_id,
            "turn_idx": self.turn_idx,
        }


# ---------------------------------------------------------------------------
# Process plane — interface + one reference adapter (this phase)
# ---------------------------------------------------------------------------


class ProcessPlaneAdapter(ABC):
    """Interface for an in-agent (process-plane) observation source.

    A concrete adapter bridges in-agent hooks (callbacks, spans, a sidecar
    socket) into the harness. This phase ships the interface plus one
    reference adapter; production adapters are downstream work.
    """

    plane = ObservationPlane.PROCESS

    @abstractmethod
    def start(self) -> None:
        """Begin receiving in-agent events."""

    @abstractmethod
    def stop(self) -> None:
        """Stop receiving in-agent events."""


class CallbackProcessPlaneAdapter(ProcessPlaneAdapter):
    """Reference process-plane adapter: the agent pushes hook events in via
    :meth:`emit`, which forwards them to a sink. Deliberately minimal — it
    demonstrates the interface without binding to any agent framework."""

    def __init__(
        self, sink: Callable[[Mapping[str, object]], None] | None = None
    ) -> None:
        self._sink = sink
        self._running = False
        self.received: list[Mapping[str, object]] = []

    def start(self) -> None:
        self._running = True

    def stop(self) -> None:
        self._running = False

    def emit(self, hook_event: Mapping[str, object]) -> None:
        """Called by the instrumented agent for each in-process hook."""
        if not self._running:
            return
        self.received.append(hook_event)
        if self._sink is not None:
            self._sink(hook_event)


# ---------------------------------------------------------------------------
# Instrumentation state — active profile, transitions, availability
# ---------------------------------------------------------------------------


class InstrumentationState:
    """Tracks the active profile and records every transition.

    Owns the answer to two questions the trajectory must record: *which
    planes are live right now* and *how did we get here*.
    """

    def __init__(
        self,
        profile: InstrumentationProfile,
        custom_profiles: Mapping[str, Sequence[str]] | None = None,
    ) -> None:
        self._active = profile
        self._custom = dict(custom_profiles or {})
        self._transitions: list[ProfileTransition] = []

    @property
    def active_profile(self) -> str:
        return self._active.name

    @property
    def active_planes(self) -> frozenset[ObservationPlane]:
        return self._active.planes

    def transitions(self) -> list[ProfileTransition]:
        return list(self._transitions)

    def switch(
        self,
        profile_name: str,
        reason: str,
        *,
        session_id: str | None = None,
        turn_idx: int | None = None,
        on_activate: Callable[[frozenset[ObservationPlane]], None] | None = None,
    ) -> ProfileTransition | None:
        """Switch to ``profile_name``. Records and returns the transition,
        or ``None`` if it is already active (a no-op switch). ``on_activate``
        is invoked with the newly-added planes and its wall-clock time is
        recorded as the measured overhead."""
        target = resolve_profile(profile_name, self._custom)
        if target.name == self._active.name and target.planes == self._active.planes:
            return None
        added = target.planes - self._active.planes
        start = time.perf_counter()
        if on_activate is not None and added:
            on_activate(added)
        overhead = time.perf_counter() - start
        transition = ProfileTransition(
            from_profile=self._active.name,
            to_profile=target.name,
            reason=reason,
            overhead_seconds=overhead,
            session_id=session_id,
            turn_idx=turn_idx,
        )
        self._active = target
        self._transitions.append(transition)
        return transition

    def is_available(self, detector: object) -> bool:
        """A detector is available iff all its required planes are active."""
        return detector_required_planes(detector) <= self._active.planes

    def partition(
        self, detectors: Iterable[_D]
    ) -> tuple[list[_D], list[_D]]:
        """Split detectors into (available, unavailable) under the active
        profile. Unavailable detectors must be reported unavailable, never
        run-and-clean."""
        available: list[_D] = []
        unavailable: list[_D] = []
        for d in detectors:
            (available if self.is_available(d) else unavailable).append(d)
        return available, unavailable

    def availability_map(self, detectors: Iterable[object]) -> dict[str, str]:
        """Per-detector ``"available"`` / ``"unavailable"`` under the active
        profile, keyed by saster_id."""
        return {
            getattr(d, "saster_id", repr(d)): (
                "available" if self.is_available(d) else "unavailable"
            )
            for d in detectors
        }

    def to_dict(self, detectors: Iterable[object] | None = None) -> dict[str, object]:
        """Trajectory-embeddable snapshot of instrumentation state."""
        out: dict[str, object] = {
            "active_profile": self.active_profile,
            "active_planes": sorted(p.value for p in self.active_planes),
            "transitions": [t.to_dict() for t in self._transitions],
        }
        if detectors is not None:
            out["detector_availability"] = self.availability_map(detectors)
        return out
