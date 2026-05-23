"""ProbeScheduler — the PROBE-mode side-loop.

Replaces the v0.2 ``_start_probe_scheduler`` logged-warning stub.

Runs a single daemon thread that wakes every
``probe_interval_hours * 3600`` seconds, walks the harness's induced
detectors, and invokes ``detector.induce(prober, session_id)`` on each.
The returned :class:`~saster_harness.event.DetectionEvent` (if any) is
routed through the same sink the proxy uses; the divergence score (or
``0.0`` when the detector held below threshold) is written to the
shared :class:`~saster_harness.drift.SusceptibilityCache` so the
:class:`~saster_harness.drift.DriftAccumulator` can read it as the
fourth signal in the boundary composition.

Three failure modes are handled:

1. The detector raises during ``induce`` — logged, susceptibility
   recorded as ``0.0`` (we don't penalize the agent for a buggy
   probe), the loop continues with the next detector.
2. The prober is unavailable — the entire cycle is skipped at the
   top of the loop. The scheduler keeps polling so the operator can
   restore connectivity without restarting the harness.
3. The harness is shutting down — the ``stop_event`` is polled on a
   1-second interval so shutdown latency stays small even when the
   probe interval is in hours.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Iterable

from .detector import SasterDetector
from .detectors.base_induction import InductionDetector
from .drift import SusceptibilityCache
from .event import DetectionEvent
from .prober import Prober

logger = logging.getLogger(__name__)


EventSink = Callable[[DetectionEvent], None]


class ProbeScheduler:
    """Daemon-thread scheduler for PROBE mode.

    The scheduler is not started at construction — call
    :meth:`start_thread` with a stop event after constructing it.
    The harness owns the thread lifecycle.

    Parameters
    ----------
    detectors
        Full detector list — the scheduler filters to the
        :class:`InductionDetector` subclasses internally.
    prober
        Active-injection backend. When ``None``, the scheduler logs
        a warning each cycle and otherwise no-ops; this is graceful
        degradation for sites where the agent endpoint isn't directly
        probeable.
    sink
        Callable that receives any :class:`DetectionEvent` returned
        by ``detector.induce``.
    susceptibility_cache
        Shared cache. The scheduler writes the latest divergence
        score per induced pattern; the drift accumulator reads it.
    interval_seconds
        Time between cycles. Constructed from
        ``probe_interval_hours * 3600`` by the harness.
    probe_on_start
        If ``True``, run one full cycle immediately on start before
        the first sleep. Useful for demos and CI.
    """

    _POLL_INTERVAL_SECONDS = 1.0

    def __init__(
        self,
        detectors: Iterable[SasterDetector],
        prober: Prober | None,
        sink: EventSink,
        susceptibility_cache: SusceptibilityCache,
        interval_seconds: float,
        probe_on_start: bool = False,
    ) -> None:
        self._all_detectors = list(detectors)
        self._induced: list[InductionDetector] = [
            d for d in self._all_detectors if isinstance(d, InductionDetector)
        ]
        self._prober = prober
        self._sink = sink
        self._sus_cache = susceptibility_cache
        self._interval_seconds = float(interval_seconds)
        self._probe_on_start = bool(probe_on_start)
        self._thread: threading.Thread | None = None
        self._cycle_lock = threading.Lock()
        self._cycle_count = 0
        self._last_cycle_completed_at: float = 0.0

    # ----------------------------------------------------------------
    # Public lifecycle API
    # ----------------------------------------------------------------

    def start_thread(self, stop_event: threading.Event) -> threading.Thread:
        """Start the daemon thread. Returns it for join/test purposes.
        Safe to call multiple times — subsequent calls return the
        existing thread without restarting it."""
        if self._thread is not None and self._thread.is_alive():
            return self._thread
        self._thread = threading.Thread(
            target=self._run,
            name="saster-harness-probe-scheduler",
            args=(stop_event,),
            daemon=True,
        )
        self._thread.start()
        return self._thread

    def run_one_cycle(self) -> dict[str, float]:
        """Run a single probe cycle synchronously. Returns the
        ``{saster_id: susceptibility}`` map updated this cycle. Useful
        for tests and the ``probe_on_start`` immediate-first-cycle
        path."""
        with self._cycle_lock:
            results = self._cycle_body()
            self._cycle_count += 1
            self._last_cycle_completed_at = time.time()
        return results

    @property
    def cycle_count(self) -> int:
        return self._cycle_count

    @property
    def last_cycle_completed_at(self) -> float:
        return self._last_cycle_completed_at

    # ----------------------------------------------------------------
    # Internals
    # ----------------------------------------------------------------

    def _run(self, stop_event: threading.Event) -> None:
        logger.info(
            "Probe scheduler running: %d induced detectors, interval %.1f h, "
            "probe_on_start=%s",
            len(self._induced),
            self._interval_seconds / 3600.0,
            self._probe_on_start,
        )
        # Surface the v0.3 demo footgun: PROBE mode + default config
        # (probe_on_start=False, probe_interval_hours=24) means the
        # operator sees zero probe activity for 24 hours unless they
        # opt into the immediate-start path. Warn explicitly so a
        # stage demo or CI run isn't silently idle.
        if (
            not self._probe_on_start
            and self._interval_seconds >= 3600.0
        ):
            logger.warning(
                "PROBE scheduler will not run a cycle for %.1f hours "
                "(probe_on_start=False, probe_interval_hours=%.1f). "
                "Set MonitoringConfig(probe_on_start=True) to run an "
                "immediate first cycle (intended for demos and CI).",
                self._interval_seconds / 3600.0,
                self._interval_seconds / 3600.0,
            )

        if self._probe_on_start:
            try:
                self.run_one_cycle()
            except Exception:  # pragma: no cover — defensive
                logger.exception("Initial probe cycle failed")

        next_cycle_at = time.time() + self._interval_seconds
        while not stop_event.is_set():
            sleep_for = min(self._POLL_INTERVAL_SECONDS, next_cycle_at - time.time())
            if sleep_for > 0:
                if stop_event.wait(timeout=sleep_for):
                    break
                continue
            try:
                self.run_one_cycle()
            except Exception:  # pragma: no cover — defensive
                logger.exception("Probe cycle failed")
            next_cycle_at = time.time() + self._interval_seconds
        logger.info("Probe scheduler stopped after %d cycles.", self._cycle_count)

    def _cycle_body(self) -> dict[str, float]:
        if self._prober is None:
            logger.warning(
                "Probe cycle skipped: no Prober available "
                "(no operator-supplied prober and no agent_endpoint reachable)."
            )
            return {}
        if not self._induced:
            logger.debug("Probe cycle no-op: zero induced detectors enabled.")
            return {}

        results: dict[str, float] = {}
        cycle_ts = int(time.time())
        for detector in self._induced:
            session_id = f"probe::{detector.saster_id}::{cycle_ts}"
            score, event = self._probe_one(detector, session_id)
            results[detector.saster_id] = score
            self._sus_cache.update(detector.saster_id, score)
            if event is not None:
                # Annotate the event so consumers know this came from
                # the PROBE scheduler and not from live wire traffic.
                event.evidence.setdefault("probe_cycle", self._cycle_count + 1)
                event.evidence.setdefault("probe_source", "scheduler")
                # Concern 2b: belt-and-suspenders. The induce() helpers
                # in base_induction.py / saster_*_induced.py already set
                # origin="probe"; this enforces the invariant for any
                # custom detector that builds events outside those
                # helpers and forgets to tag.
                event.origin = "probe"
                self._sink(event)

        logger.info(
            "Probe cycle %d complete: %s",
            self._cycle_count + 1,
            ", ".join(f"{k}={v:.2f}" for k, v in results.items()),
        )
        return results

    def _probe_one(
        self, detector: InductionDetector, session_id: str,
    ) -> tuple[float, DetectionEvent | None]:
        """Run one detector's induce cycle. Returns
        (susceptibility_score, event_or_None).

        When ``induce`` returns an event, the susceptibility is the
        event's ``divergence_score`` (or 1.0 if absent). When ``None``,
        the agent held below threshold — susceptibility is 0.0."""
        try:
            event = detector.induce(self._prober, session_id)
        except Exception:  # pragma: no cover — defensive
            logger.exception(
                "induce() raised for %s; recording susceptibility=0.0",
                detector.saster_id,
            )
            return 0.0, None
        if event is None:
            return 0.0, None
        # Pull the divergence score from event evidence when present;
        # fall back to 1.0 (a firing event without a score means the
        # detector decided susceptibility was maximal).
        score_obj = event.evidence.get("divergence_score")
        try:
            score = float(score_obj) if score_obj is not None else 1.0
        except (TypeError, ValueError):
            score = 1.0
        return max(0.0, min(1.0, score)), event
