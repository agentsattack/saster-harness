"""Base classes for active-injection SASTER detectors.

Passive :class:`SasterDetector` subclasses fire on captured
:class:`TurnData` — they look at traffic that already happened and
decide whether a pattern was present. Induction-mode detectors take
the opposite stance: they actively send a probe into the agent's
session and decide what the response reveals.

v0.3 split — single-turn vs scenario shapes
--------------------------------------------
v0.2 had a single ``InductionDetector`` abstract base whose contract
(``baseline_prompt`` / ``induction_strategy`` / ``divergence_score``)
assumed every detector probed one baseline ask against N reframings.
Three v0.2 detectors (SASTER-13/15/24/26-induced) don't actually
work that way — they run multi-turn scenarios with their own
orchestration, and were forced to ship compat-shim placeholders for
the abstract methods. The signature was lying about what those
detectors actually did.

v0.3 splits the abstraction into three classes:

- :class:`InductionDetector` — abstract polymorphic parent. Only
  declares ``induce(prober, session_id) -> DetectionEvent | None`` as
  abstract, plus the inherited ``evaluate`` no-op. Use this when you
  want a polymorphic ``isinstance`` check that covers both shapes
  (this is what :class:`saster_harness.scheduler.ProbeScheduler` does).

- :class:`SingleTurnInductionDetector` — for detectors that score one
  baseline ask against N reframings. Carries the abstract contract
  ``baseline_prompt`` / ``induction_strategy`` / ``divergence_score``
  / ``divergence_threshold`` and a concrete ``induce()`` that drives
  the loop. SASTER-18-induced and SASTER-13-induced inherit from
  this.

- :class:`ScenarioInductionDetector` — for detectors that run
  multi-turn scenarios with custom orchestration. Declares
  ``scenarios()`` abstract (for introspection by the harness and
  tests) and leaves ``induce()`` for the subclass to implement.
  SASTER-15-induced, SASTER-24-induced, and SASTER-26-induced
  inherit from this. No abstract method exists for ``divergence``
  because the per-scenario scoring signatures differ between
  detectors (see :meth:`Saster26InducedDetector.divergence_for_scenario`
  which accepts an additional ``recon_responses`` parameter).

Breaking change vs v0.2
-----------------------
Any subclass of v0.2's ``InductionDetector`` that implemented the
three abstract methods and relied on the inherited ``induce()``
must now inherit from :class:`SingleTurnInductionDetector` instead.
The polymorphic ``InductionDetector`` no longer ships a concrete
``induce()``. No detectors outside this repository are known to
subclass the v0.2 base; if any did, the migration is a single-line
import-and-rename.
"""

from __future__ import annotations

import logging
from abc import abstractmethod
from collections.abc import Sequence
from typing import Any

from ..detector import SasterDetector
from ..event import DetectionEvent, TurnData
from ..prober import Prober, ProbeRecord

logger = logging.getLogger(__name__)


class InductionDetector(SasterDetector):
    """Abstract polymorphic parent for any detector that runs
    active-injection probes against a live agent.

    Concrete induction detectors should inherit from
    :class:`SingleTurnInductionDetector` or
    :class:`ScenarioInductionDetector` rather than this class
    directly — those siblings expose the abstract methods that match
    the two real shapes. ``InductionDetector`` itself exists so that
    callers (the harness, the probe scheduler, tests) can use a
    single ``isinstance`` check to identify any induction-mode
    detector regardless of shape.
    """

    _is_intermediate = True  # skip the __init_subclass__ metadata check

    def evaluate(self, turn: TurnData) -> DetectionEvent | None:  # noqa: D401
        """Induction detectors do not fire on passively-captured turns.
        Use :meth:`induce` to run the active probe cycle."""
        return None

    @abstractmethod
    def induce(
        self, prober: Prober, session_id: str,
    ) -> DetectionEvent | None:
        """Run one active probe cycle against ``session_id``. Return
        a :class:`DetectionEvent` if the cycle uncovered susceptibility,
        otherwise ``None``."""

    # ----------------------------------------------------------------
    # Internals shared by both shapes
    # ----------------------------------------------------------------

    def _build_induction_event(
        self,
        baseline: ProbeRecord,
        induced: ProbeRecord,
        score: float,
    ) -> DetectionEvent:
        """Construct the DetectionEvent for a successful induction.

        The synthetic TurnData carries the induced response (which is
        what diverged) so downstream consumers see the actual content
        that fired the pattern. Used by
        :class:`SingleTurnInductionDetector`; scenario detectors
        typically build richer events via their own helpers."""
        turn = TurnData(
            session_id=induced.session_id,
            turn_idx=0,
            user_message=induced.content,
            assistant_response=induced.response,
            raw_request=induced.content.encode("utf-8"),
            raw_response=induced.response.encode("utf-8"),
            timestamp=induced.timestamp,
        )
        return self._build_event(
            turn,
            evidence={
                "signal": "induction_divergence",
                "detail": (
                    f"Induced response diverged from baseline refusal "
                    f"(score {score:.3f} >= threshold "
                    f"{self.divergence_threshold():.3f})."
                    if hasattr(self, "divergence_threshold")
                    else f"Induced response diverged from baseline (score "
                    f"{score:.3f})."
                ),
                "divergence_score": round(score, 3),
                "divergence_threshold": (
                    self.divergence_threshold()
                    if hasattr(self, "divergence_threshold")
                    else None
                ),
                "baseline_prompt": baseline.content,
                "baseline_response": baseline.response[:240],
                "induced_prompt": induced.content,
                "induced_response": induced.response[:240],
            },
        )


class SingleTurnInductionDetector(InductionDetector):
    """Abstract base for induction detectors with the canonical
    single-turn shape:

    1. Establish a baseline refusal to one canonical prompt.
    2. Iterate a sequence of reframings; for each one, inject a turn
       and score divergence against the baseline.
    3. Fire the first reframing whose divergence crosses threshold.

    Subclasses must implement :meth:`baseline_prompt`,
    :meth:`induction_strategy`, and :meth:`divergence_score`. The
    default :meth:`divergence_threshold` is ``0.5``. The concrete
    :meth:`induce` drives the standard loop.

    Subclasses MAY override :meth:`induce` if they need
    session-scoping per reframing (see SASTER-13-induced) — the
    abstract methods remain available for tests and analysts who
    want to score hand-crafted probes outside the standard loop.
    """

    _is_intermediate = True

    # ----------------------------------------------------------------
    # Required overrides
    # ----------------------------------------------------------------

    @abstractmethod
    def baseline_prompt(self) -> str:
        """Reference prompt to inject for baseline establishment.

        The agent's response to this prompt is expected to be a clear
        refusal; divergence scoring compares every subsequent reframed
        response against this refusal."""

    @abstractmethod
    def induction_strategy(self) -> Sequence[str]:
        """Return the sequence of induction prompts to send after the
        baseline. Each prompt is a separate reframing attempt."""

    @abstractmethod
    def divergence_score(
        self,
        baseline: ProbeRecord,
        induced: ProbeRecord,
    ) -> float:
        """Return a score in ``[0.0, 1.0]`` indicating how far ``induced``
        diverged from ``baseline``. Higher = more divergence = more
        suspicious."""

    # ----------------------------------------------------------------
    # Optional overrides
    # ----------------------------------------------------------------

    def divergence_threshold(self) -> float:
        """Score above which the pattern fires. Default ``0.5``."""
        return 0.5

    # ----------------------------------------------------------------
    # Concrete probe loop
    # ----------------------------------------------------------------

    def induce(self, prober: Prober, session_id: str) -> DetectionEvent | None:
        """Run the standard single-turn probe cycle against
        ``session_id``. Returns a :class:`DetectionEvent` for the
        first reframing that produces divergence ``>=``
        :meth:`divergence_threshold`, or ``None`` if every reframing
        was refused."""
        threshold = self.divergence_threshold()
        with prober.session_lock(session_id):
            baseline = prober.establish_baseline(session_id, self.baseline_prompt())
            logger.debug(
                "induction baseline for %s: %r",
                self.saster_id, baseline.response[:120],
            )

            for prompt in self.induction_strategy():
                induced = prober.inject_turn(session_id, prompt)
                score = self.divergence_score(baseline, induced)
                logger.debug(
                    "induction probe %s score=%.3f prompt=%r",
                    self.saster_id, score, prompt[:80],
                )
                if score >= threshold:
                    return self._build_induction_event(
                        baseline=baseline,
                        induced=induced,
                        score=score,
                    )
        return None


class ScenarioInductionDetector(InductionDetector):
    """Abstract base for induction detectors that run multi-turn
    scenarios with custom orchestration.

    Each scenario typically consists of a baseline ask, an arbitrary
    number of intermediate turns that shape the agent's context, and
    one or more target / follow-up turns whose response is what gets
    scored. The exact shape varies per detector:

    - SASTER-15-induced sends baseline → N erosion turns → target.
    - SASTER-24-induced sends baseline → redefinition → follow-up.
    - SASTER-26-induced sends a recon probe and a sibling neutral
      probe, both ending in the same question, and compares them.

    Because the per-scenario scoring signature differs (SASTER-26
    needs the recon-response list; the others don't), this base
    class does NOT declare a uniform ``divergence_for_scenario``
    abstract method. Subclasses implement their own scoring helpers
    and drive the scenario sequence inside :meth:`induce`.

    :meth:`scenarios` is required so the harness, the probe
    scheduler, and tests can introspect the configured scenario set
    without having to know each subclass's internal dataclass."""

    _is_intermediate = True

    @abstractmethod
    def scenarios(self) -> tuple[Any, ...]:
        """Return the configured scenario tuple. Detectors define
        their own ``@dataclass(frozen=True)`` scenario shape; callers
        treat the return value as opaque except for introspection
        (``len()``, iteration for display)."""

    @abstractmethod
    def induce(
        self, prober: Prober, session_id: str,
    ) -> DetectionEvent | None:
        """Drive every configured scenario against ``session_id``.
        Each scenario should run under its own scoped session id
        (typically ``f"{session_id}::{scenario.name}"``) so the
        scenarios don't contaminate each other's context. The first
        scenario whose composite score crosses the detector's
        threshold should fire and short-circuit the rest."""
