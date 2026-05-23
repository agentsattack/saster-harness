"""Tests for ``MonitoringConfig.shadow_mode`` — the v0.3 gate that
suppresses passive-detector alerts during baseline establishment.

When ``shadow_mode=True`` (the default), events fired by passive
detectors before the session baseline is locked in still enter the
in-memory event buffer but do NOT fire the alert webhook. Once the
baseline establishes, the full firing path resumes.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import numpy as np
import pytest

from saster_harness.baseline import EmbeddingBaseline
from saster_harness.config import HarnessMode, MonitoringConfig
from saster_harness.event import DetectionEvent
from saster_harness.harness import MonitoringHarness


def _fake_embedder(text: str) -> np.ndarray:
    rng = np.random.default_rng(abs(hash(text)) % (2**32))
    return rng.standard_normal(8).astype(np.float32)


def _make_harness(shadow_mode: bool, baseline_turns: int = 3) -> MonitoringHarness:
    config = MonitoringConfig(
        agent_name="test-agent",
        agent_endpoint="http://localhost:9999/chat",
        authorized_tools=[],
        baseline_turns=baseline_turns,
        shadow_mode=shadow_mode,
        alert_webhook="https://example.com/hook",
        mode=HarnessMode.OBSERVE,
    )
    h = MonitoringHarness(config=config, detectors=[])
    # Replace the baseline with one that uses our deterministic embedder
    # so the test does not need sentence-transformers installed.
    h._baseline = EmbeddingBaseline(
        baseline_turns=baseline_turns, embedder=_fake_embedder,
    )
    # Swallow the webhook call so the test can observe whether it
    # was attempted.
    h._dispatch_webhook = MagicMock()  # type: ignore[method-assign]
    return h


def _event(session_id: str, saster_id: str = "SASTER-18") -> DetectionEvent:
    return DetectionEvent(
        saster_id=saster_id,
        pattern_name="Semantic Recasting",
        tier=3,
        agent_name="test-agent",
        session_id=session_id,
        turn_idx=0,
        evidence={"signal": "test", "detail": "fixture event"},
    )


def test_shadow_suppresses_webhook_before_baseline_established() -> None:
    h = _make_harness(shadow_mode=True, baseline_turns=3)
    # Baseline not yet established for session "s1".
    h._handle_event(_event("s1"))
    h._dispatch_webhook.assert_not_called()
    # Event is still recorded in the buffer for analyst review.
    assert len(h.recent_events()) == 1


def test_shadow_fires_webhook_once_baseline_locks_in() -> None:
    h = _make_harness(shadow_mode=True, baseline_turns=2)
    # Lock the baseline for s1.
    h._baseline.observe("s1", "warmup one")
    h._baseline.observe("s1", "warmup two")
    assert h._baseline.is_established("s1")

    h._handle_event(_event("s1"))
    h._dispatch_webhook.assert_called_once()


def test_shadow_disabled_fires_immediately_for_v02_parity() -> None:
    h = _make_harness(shadow_mode=False)
    # Baseline NOT established but shadow disabled — webhook fires.
    h._handle_event(_event("s1"))
    h._dispatch_webhook.assert_called_once()


def test_shadow_does_not_gate_synthetic_drift_events() -> None:
    """Drift / autonomous-escalation / probe events emitted by the
    v0.3 subsystems aren't tied to a per-session embedding baseline
    and should bypass the shadow gate."""
    h = _make_harness(shadow_mode=True)
    h._handle_event(_event("s1", saster_id="SASTER-DRIFT-COMPOSITE"))
    h._dispatch_webhook.assert_called_once()


def test_shadow_skips_when_event_has_no_session() -> None:
    """Events without a session id can't have a baseline lookup — the
    gate should not raise."""
    h = _make_harness(shadow_mode=True)
    h._handle_event(_event("", saster_id="SASTER-18"))
    # No session → cannot look up baseline → fire normally
    h._dispatch_webhook.assert_called_once()


def test_webhook_dispatch_does_not_block_caller_thread() -> None:
    """v0.3 fix: _dispatch_webhook must return immediately. The actual
    HTTP POST runs on a bounded thread pool; a hung webhook endpoint
    can no longer stall the proxy thread."""
    import threading
    import time as time_module

    # Build a harness directly so _dispatch_webhook is NOT replaced
    # with a MagicMock (which is what _make_harness does for other tests).
    config = MonitoringConfig(
        agent_name="t",
        agent_endpoint="http://localhost:9999/chat",
        authorized_tools=[],
        shadow_mode=False,
        alert_webhook="https://example.com/hook",
        mode=HarnessMode.OBSERVE,
    )
    h = MonitoringHarness(config=config, detectors=[])
    h._baseline = EmbeddingBaseline(baseline_turns=2, embedder=_fake_embedder)

    # Replace _post_webhook with a slow stub so we can measure that
    # the caller thread does NOT wait for it.
    posted = threading.Event()
    started = threading.Event()

    def _slow_post(event):  # type: ignore[no-untyped-def]
        started.set()
        time_module.sleep(0.3)
        posted.set()

    h._post_webhook = _slow_post  # type: ignore[method-assign]

    t0 = time_module.perf_counter()
    h._dispatch_webhook(_event("s1"))
    elapsed = time_module.perf_counter() - t0
    # Dispatch should return in well under the slow-post sleep duration.
    assert elapsed < 0.1, (
        f"_dispatch_webhook took {elapsed:.3f}s — should be non-blocking"
    )
    # And the post should eventually fire on the executor thread.
    assert started.wait(timeout=1.0), "post never started"
    assert posted.wait(timeout=2.0), "post never completed"

    # Clean up the executor so it doesn't leak between tests.
    if h._webhook_executor is not None:
        h._webhook_executor.shutdown(wait=False)


def test_shadow_bypasses_probe_scheduler_sessions() -> None:
    """PROBE-scheduler synthetic session ids (``probe::SASTER-XX::<ts>``)
    never enter the per-session EmbeddingBaseline, so ``is_established``
    is structurally False for them. Without an explicit bypass, every
    induced-detector firing from the scheduler would silently shadow-
    gate in the default config — a real bug for PROBE-mode operators.

    This test pins the bypass at harness._is_in_shadow so a future
    refactor doesn't reintroduce the regression."""
    h = _make_harness(shadow_mode=True)
    event = _event(
        session_id="probe::SASTER-18-induced::1747700000",
        saster_id="SASTER-18-induced",
    )
    h._handle_event(event)
    # The event came from the scheduler — bypass shadow, fire normally.
    h._dispatch_webhook.assert_called_once()


def test_shadow_default_is_true() -> None:
    """The default value is the safe one — passive events suppressed
    during baseline. Documented contract in the slide deck."""
    config = MonitoringConfig(
        agent_name="test", agent_endpoint="http://localhost/", authorized_tools=[],
    )
    assert config.shadow_mode is True


def test_alert_webhook_required_for_shadow_to_make_observable_difference() -> None:
    """When alert_webhook is None, shadow_mode is a no-op for the
    webhook path. The event still enters the buffer."""
    config = MonitoringConfig(
        agent_name="test-agent",
        agent_endpoint="http://localhost:9999/chat",
        authorized_tools=[],
        shadow_mode=True,
        alert_webhook=None,
    )
    h = MonitoringHarness(config=config, detectors=[])
    h._baseline = EmbeddingBaseline(baseline_turns=2, embedder=_fake_embedder)
    # No webhook to call regardless of shadow state.
    h._handle_event(_event("s1"))
    assert len(h.recent_events()) == 1


def test_log_shadow_events_surfaces_shadow_line_at_info(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """With ``log_shadow_events=True``, the SHADOW line is emitted at
    INFO instead of DEBUG so live-demo terminals show shadow-suppressed
    events without dropping to ``-vv`` verbosity. Webhook MUST still
    be suppressed — only the log level changes."""
    config = MonitoringConfig(
        agent_name="test-agent",
        agent_endpoint="http://localhost:9999/chat",
        authorized_tools=[],
        baseline_turns=3,
        shadow_mode=True,
        log_shadow_events=True,
        alert_webhook="https://example.com/hook",
        mode=HarnessMode.OBSERVE,
    )
    h = MonitoringHarness(config=config, detectors=[])
    h._baseline = EmbeddingBaseline(baseline_turns=3, embedder=_fake_embedder)
    h._dispatch_webhook = MagicMock()  # type: ignore[method-assign]

    with caplog.at_level(logging.INFO, logger="saster_harness.harness"):
        h._handle_event(_event("s1"))

    # The shadow line is prefixed with the origin tag — "SHADOW[WIRE]"
    # for organic events, "SHADOW[PROBE]" for induce-path events
    # (Concern 2c). For this test we fire an organic SASTER-18 so the
    # expected prefix is [WIRE].
    shadow_records = [
        r for r in caplog.records if r.message.startswith("SHADOW[")
    ]
    assert len(shadow_records) == 1, "expected exactly one SHADOW log record"
    assert shadow_records[0].levelno == logging.INFO
    assert shadow_records[0].message.startswith("SHADOW[WIRE] ")
    h._dispatch_webhook.assert_not_called()
