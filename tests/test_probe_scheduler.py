"""Tests for the v0.3 ProbeScheduler.

Validates the load-bearing pieces:

- ``run_one_cycle`` invokes every induced detector exactly once and
  writes a susceptibility score for each.
- A detector that returns an event publishes the event through the
  sink with a ``probe_source`` annotation.
- A detector that returns None records susceptibility = 0.0.
- Missing prober → cycle is a logged no-op, not a crash.
- ``probe_on_start`` runs one cycle before the first sleep.
- Synthetic events bypass the scheduler's susceptibility cache when
  not produced by an induced detector (covered indirectly through
  the integration with ``DriftAccumulator``).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Sequence

from saster_harness.detectors.base_induction import InductionDetector
from saster_harness.drift import SusceptibilityCache
from saster_harness.event import DetectionEvent
from saster_harness.prober import InProcessInjector, Prober, ProbeRecord
from saster_harness.scheduler import ProbeScheduler


class _DummyInducedDetector(InductionDetector):
    """Minimal InductionDetector for scheduler tests.

    Override ``_force_event`` to return a synthetic DetectionEvent on
    ``induce``; otherwise ``induce`` returns None. Tracks how many
    times ``induce`` was called.
    """

    saster_id = "SASTER-TEST-INDUCED"
    pattern_name = "Test Induced"
    tier = 2

    def __init__(self, force_event: DetectionEvent | None = None) -> None:
        super().__init__()
        self._force_event = force_event
        self.induce_calls: list[str] = []

    def baseline_prompt(self) -> str:
        return "baseline?"

    def induction_strategy(self) -> Sequence[str]:
        return ("attempt 1",)

    def divergence_score(self, baseline: ProbeRecord, induced: ProbeRecord) -> float:
        return 0.0

    def induce(self, prober: Prober, session_id: str) -> DetectionEvent | None:
        self.induce_calls.append(session_id)
        return self._force_event


class _AnotherDummyDetector(_DummyInducedDetector):
    saster_id = "SASTER-OTHER-INDUCED"
    pattern_name = "Other Test"
    tier = 3


def _make_prober() -> Prober:
    def send(_sid: str, _content: str) -> str:
        return "ok"
    return Prober(backend=InProcessInjector(send_fn=send))


def test_run_one_cycle_invokes_each_induced_detector_once() -> None:
    a = _DummyInducedDetector()
    b = _AnotherDummyDetector()
    sink: list[DetectionEvent] = []
    cache = SusceptibilityCache()
    sched = ProbeScheduler(
        detectors=[a, b],
        prober=_make_prober(),
        sink=sink.append,
        susceptibility_cache=cache,
        interval_seconds=3600.0,
    )

    results = sched.run_one_cycle()

    assert len(a.induce_calls) == 1
    assert len(b.induce_calls) == 1
    assert a.saster_id in results
    assert b.saster_id in results


def test_event_returning_induce_publishes_and_caches_score() -> None:
    event = DetectionEvent(
        saster_id="SASTER-TEST-INDUCED",
        pattern_name="Test Induced",
        tier=2,
        agent_name="t",
        session_id="probe::SASTER-TEST-INDUCED::0",
        turn_idx=0,
        evidence={
            "signal": "x",
            "detail": "x",
            "divergence_score": 0.73,
        },
    )
    det = _DummyInducedDetector(force_event=event)
    sink: list[DetectionEvent] = []
    cache = SusceptibilityCache()
    sched = ProbeScheduler(
        detectors=[det],
        prober=_make_prober(),
        sink=sink.append,
        susceptibility_cache=cache,
        interval_seconds=3600.0,
    )

    sched.run_one_cycle()

    assert len(sink) == 1
    assert sink[0].evidence["probe_source"] == "scheduler"
    assert cache.snapshot()["SASTER-TEST-INDUCED"] == 0.73


def test_none_returning_induce_records_zero_susceptibility() -> None:
    det = _DummyInducedDetector(force_event=None)
    sink: list[DetectionEvent] = []
    cache = SusceptibilityCache()
    sched = ProbeScheduler(
        detectors=[det],
        prober=_make_prober(),
        sink=sink.append,
        susceptibility_cache=cache,
        interval_seconds=3600.0,
    )

    sched.run_one_cycle()

    assert sink == []
    assert cache.snapshot()["SASTER-TEST-INDUCED"] == 0.0


def test_missing_prober_is_logged_noop() -> None:
    det = _DummyInducedDetector()
    sink: list[DetectionEvent] = []
    cache = SusceptibilityCache()
    sched = ProbeScheduler(
        detectors=[det],
        prober=None,
        sink=sink.append,
        susceptibility_cache=cache,
        interval_seconds=3600.0,
    )

    results = sched.run_one_cycle()

    assert results == {}
    assert sink == []
    assert det.induce_calls == []


def test_probe_on_start_triggers_immediate_cycle() -> None:
    """When ``probe_on_start=True``, the scheduler runs one cycle
    before the first sleep. We verify by starting the thread, giving
    it a brief window, then stopping it."""
    det = _DummyInducedDetector()
    sink: list[DetectionEvent] = []
    cache = SusceptibilityCache()
    sched = ProbeScheduler(
        detectors=[det],
        prober=_make_prober(),
        sink=sink.append,
        susceptibility_cache=cache,
        interval_seconds=3600.0,  # huge interval; next cycle won't happen
        probe_on_start=True,
    )
    stop = threading.Event()
    thread = sched.start_thread(stop)
    # Wait briefly for the immediate cycle to complete.
    deadline = time.time() + 2.0
    while sched.cycle_count == 0 and time.time() < deadline:
        time.sleep(0.01)
    stop.set()
    thread.join(timeout=2.0)
    assert sched.cycle_count == 1
    assert len(det.induce_calls) == 1


def test_scheduler_warns_when_probe_on_start_false_and_long_interval(caplog) -> None:
    """v0.3 fix #4: PROBE-mode + default config (probe_on_start=False,
    probe_interval_hours=24) silently waits 24 hours for the first
    cycle. Operators must see a WARNING immediately so a stage demo
    or CI run isn't mistaken for a broken scheduler."""
    import logging

    det = _DummyInducedDetector()
    cache = SusceptibilityCache()
    sched = ProbeScheduler(
        detectors=[det],
        prober=_make_prober(),
        sink=lambda _e: None,
        susceptibility_cache=cache,
        interval_seconds=24 * 3600.0,
        probe_on_start=False,
    )
    stop = threading.Event()
    with caplog.at_level(logging.WARNING, logger="saster_harness.scheduler"):
        thread = sched.start_thread(stop)
        # The warning fires synchronously at the top of _run; brief wait
        # is enough for the thread to log + enter its poll loop.
        deadline = time.time() + 1.0
        while not any(
            "will not run a cycle" in r.message for r in caplog.records
        ) and time.time() < deadline:
            time.sleep(0.01)
        stop.set()
        thread.join(timeout=2.0)
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("will not run a cycle" in w.message for w in warnings)
    assert any("probe_on_start=True" in w.message for w in warnings)


def test_scheduler_does_not_warn_when_probe_on_start_true(caplog) -> None:
    """The warning is gated on probe_on_start=False — operators who
    explicitly enabled the immediate-cycle path don't need to be told."""
    import logging

    det = _DummyInducedDetector()
    cache = SusceptibilityCache()
    sched = ProbeScheduler(
        detectors=[det],
        prober=_make_prober(),
        sink=lambda _e: None,
        susceptibility_cache=cache,
        interval_seconds=24 * 3600.0,
        probe_on_start=True,
    )
    stop = threading.Event()
    with caplog.at_level(logging.WARNING, logger="saster_harness.scheduler"):
        thread = sched.start_thread(stop)
        # Give the immediate cycle a brief moment to run.
        deadline = time.time() + 1.0
        while sched.cycle_count == 0 and time.time() < deadline:
            time.sleep(0.01)
        stop.set()
        thread.join(timeout=2.0)
    assert not any(
        "will not run a cycle" in r.message for r in caplog.records
    )


def test_scheduler_does_not_treat_passive_detectors_as_induced() -> None:
    """Passive SasterDetector subclasses should be filtered out — the
    scheduler only calls ``induce`` on InductionDetector instances."""
    from saster_harness.detectors.saster_18 import SemanticRecastingDetector
    passive = SemanticRecastingDetector()
    induced = _DummyInducedDetector()
    cache = SusceptibilityCache()
    sched = ProbeScheduler(
        detectors=[passive, induced],
        prober=_make_prober(),
        sink=lambda _e: None,
        susceptibility_cache=cache,
        interval_seconds=3600.0,
    )

    results = sched.run_one_cycle()

    assert induced.saster_id in results
    assert "SASTER-18" not in results  # passive — not induced
