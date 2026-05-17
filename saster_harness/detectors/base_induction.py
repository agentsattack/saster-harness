"""InductionDetector — base class for active-injection SASTER detectors.

The passive :class:`SasterDetector` subclasses fire on captured
:class:`TurnData` — they look at traffic that already happened and
decide whether a pattern was present. Induction-mode detectors take
the opposite stance: they actively send a probe into the agent's
session and decide what the response reveals.

A single induction cycle looks like::

    detector.induce(prober, session_id)
      ├─ prober.session_lock(session_id)               # block real traffic
      ├─ prober.establish_baseline(session_id, ...)    # capture the refusal
      ├─ for prompt in detector.induction_strategy():  # for each reframing
      │     induced = prober.inject_turn(...)          # send the reframing
      │     score = detector.divergence_score(...)     # compare to baseline
      │     if score >= threshold:
      │         return DetectionEvent
      └─ return None                                   # all reframings refused

Subclasses must override:

- :meth:`baseline_prompt` — the request that the agent should refuse
  in its un-reframed form.
- :meth:`induction_strategy` — the sequence of reframings to try.
- :meth:`divergence_score` — how far an induced response sits from
  the baseline refusal, in ``[0.0, 1.0]``.

Subclasses MAY override :meth:`divergence_threshold` (default 0.5).

The class inherits from :class:`SasterDetector` for type compatibility
with the harness detector registry. :meth:`evaluate` returns ``None``
on every captured turn — induction runs out-of-band via
:meth:`induce`.
"""

from __future__ import annotations

import logging
from abc import abstractmethod
from collections.abc import Sequence

from ..detector import SasterDetector
from ..event import DetectionEvent, TurnData
from ..prober import Prober, ProbeRecord

logger = logging.getLogger(__name__)


class InductionDetector(SasterDetector):
    """Base class for SASTER detectors that actively inject turns."""

    _is_intermediate = True  # skip the __init_subclass__ metadata check
    # Concrete subclasses MUST declare saster_id / pattern_name / tier;
    # the SasterDetector base enforces this via __init_subclass__.

    def evaluate(self, turn: TurnData) -> DetectionEvent | None:  # noqa: D401
        """Induction detectors do not fire on passively-captured turns.
        Use :meth:`induce` to run the active probe cycle."""
        return None

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
    # Public entry point
    # ----------------------------------------------------------------

    def induce(self, prober: Prober, session_id: str) -> DetectionEvent | None:
        """Run the full probe cycle against ``session_id``. Returns a
        :class:`DetectionEvent` for the first reframing that produces
        divergence ``>=`` :meth:`divergence_threshold`, or ``None`` if
        every reframing was refused.

        The first divergence above threshold short-circuits the loop —
        the detector fires once per cycle, not once per reframing."""
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

    # ----------------------------------------------------------------
    # Internals
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
        that fired the pattern."""
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
                ),
                "divergence_score": round(score, 3),
                "divergence_threshold": self.divergence_threshold(),
                "baseline_prompt": baseline.content,
                "baseline_response": baseline.response[:240],
                "induced_prompt": induced.content,
                "induced_response": induced.response[:240],
            },
        )
