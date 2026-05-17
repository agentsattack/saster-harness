"""SasterDetector — base class for all SASTER pattern detectors.

Every detector lives in :mod:`saster_harness.detectors` and inherits from
:class:`SasterDetector`. Subclasses declare their metadata as class
attributes, implement :meth:`evaluate`, and (optionally) override
:meth:`needs_baseline` to opt in to baseline-suppression behavior.

Authoring a new detector is a four-step exercise:

1. Cite the canonical SASTER.md definition in the module docstring.
2. Declare ``saster_id``, ``pattern_name``, ``tier``, ``co_fires_with``.
3. Implement ``evaluate(turn) -> DetectionEvent | None``.
4. Document the false-positive cases in the module docstring.

See :mod:`saster_harness.detectors.saster_26` for the reference
implementation; :doc:`pattern-authoring` (in the project docs) walks through
the full process with SASTER-31 / Carl 2b as a worked example.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from .event import DetectionEvent, TurnData


class SasterDetector(ABC):
    """Base class for SASTER pattern detectors.

    Class attributes
    ----------------
    saster_id
        Canonical pattern identifier, e.g. ``"SASTER-31"``. Required.
    pattern_name
        Canonical human-readable name. Required.
    tier
        SASTER tier (1–4). Required.
    co_fires_with
        Other SASTER pattern IDs that canonically co-occur with this one.
        Used to populate :attr:`DetectionEvent.co_fires_with` so consumers
        can correlate without having to know the taxonomy.

    Methods
    -------
    evaluate
        Decide whether the pattern fires on the given turn. Return a
        :class:`DetectionEvent` or ``None``.
    needs_baseline
        Override to return ``True`` if the detector should be suppressed
        until the session baseline is established. Default ``False``.
    """

    saster_id: ClassVar[str]
    pattern_name: ClassVar[str]
    tier: ClassVar[int]
    co_fires_with: ClassVar[tuple[str, ...]] = ()

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        # Skip the check for intermediate base classes that declare
        # themselves abstract via _is_intermediate = True. Use __dict__
        # rather than getattr so the attribute does NOT propagate down
        # the MRO — concrete subclasses of an intermediate base still
        # need to declare their own saster_id / pattern_name / tier.
        if cls.__dict__.get("_is_intermediate", False):
            return
        for required in ("saster_id", "pattern_name", "tier"):
            if not hasattr(cls, required) or getattr(cls, required) in (None, ""):
                raise TypeError(
                    f"{cls.__name__} must define a non-empty {required!r} class attribute"
                )
        if cls.tier not in (1, 2, 3, 4):
            raise ValueError(f"{cls.__name__}.tier must be in 1..4 (got {cls.tier!r})")

    def needs_baseline(self) -> bool:  # noqa: D401 — declarative override hook
        """Whether this detector should be suppressed until the session
        baseline is established. Default ``False`` (detector runs from
        turn 0)."""
        return False

    @abstractmethod
    def evaluate(self, turn: TurnData) -> DetectionEvent | None:
        """Decide whether the pattern fires on ``turn``.

        Implementations should return a :class:`DetectionEvent` populated
        with at minimum the ``evidence`` dict (containing a ``"signal"``
        code and a ``"detail"`` human-readable string), or ``None`` to
        indicate no firing.
        """

    # ----------------------------------------------------------------
    # Helpers for subclasses
    # ----------------------------------------------------------------

    def _build_event(
        self,
        turn: TurnData,
        evidence: dict[str, object],
        agent_name: str = "",
    ) -> DetectionEvent:
        """Construct a populated DetectionEvent from a turn + evidence.

        Subclasses call this from :meth:`evaluate` rather than instantiating
        :class:`DetectionEvent` directly so the canonical metadata and
        ``co_fires_with`` stay consistent with the class attributes.

        ``agent_name`` defaults to empty; the harness backfills it on every
        event the addon emits using :attr:`MonitoringConfig.agent_name`.
        Pass it explicitly only when invoking detectors outside the harness
        (tests, scenario runners) where there is no backfill step."""
        return DetectionEvent(
            saster_id=self.saster_id,
            pattern_name=self.pattern_name,
            tier=self.tier,
            agent_name=agent_name,
            session_id=turn.session_id,
            turn_idx=turn.turn_idx,
            evidence=evidence,
            co_fires_with=list(self.co_fires_with),
            raw_request=turn.raw_request,
            raw_response=turn.raw_response,
            timestamp=turn.timestamp,
        )
