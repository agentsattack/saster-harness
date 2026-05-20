"""Tests for ``MonitoringConfig.shadow_mode`` — the v0.3 gate that
suppresses passive-detector alerts during baseline establishment.

When ``shadow_mode=True`` (the default), events fired by passive
detectors before the session baseline is locked in still enter the
in-memory event buffer but do NOT fire the alert webhook. Once the
baseline establishes, the full firing path resumes.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np

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
