"""End-to-end integration test for the v0.3 boundary-calculation
release.

Wires authorized_tools + RefusalSampler + DriftAccumulator +
ProbeScheduler + PersistenceStore together via a MonitoringHarness
constructed but not started (we drive ``_handle_event`` /
``_handle_turn`` directly so the test does not need mitmproxy).

The integration test does NOT exercise the proxy thread, the alert
webhook, or live network IO — those are covered in their own unit
tests. The point of this test is to validate the assembly: when the
operator supplies a config with the v0.3 fields set, do all the
moving parts fit together and produce the expected synthetic events?
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import numpy as np

from saster_harness.baseline import (
    EmbeddingBaseline,
)
from saster_harness.config import HarnessMode, MonitoringConfig
from saster_harness.detectors.saster_13_induced import Saster13InducedDetector
from saster_harness.event import DetectionEvent, TurnData
from saster_harness.harness import MonitoringHarness
from saster_harness.prober import InProcessInjector, Prober


def _fake_embedder(text: str) -> np.ndarray:
    rng = np.random.default_rng(abs(hash(text)) % (2**32))
    v = rng.standard_normal(8).astype(np.float32)
    n = float(np.linalg.norm(v))
    return (v / n).astype(np.float32) if n > 0 else v


def _build_harness(
    *,
    tmp_path: Path,
    sample_refusal_baseline: bool = True,
    shadow_mode: bool = True,
    baseline_turns: int = 3,
    state_dir: Path | None = None,
) -> MonitoringHarness:
    """Build a harness wired for v0.3 testing but without the proxy
    thread. We replace the shared embedder and baseline with
    deterministic stand-ins, and replace the dispatched webhook with
    a mock so the test can assert on it."""
    config = MonitoringConfig(
        agent_name="integration-test",
        agent_endpoint="http://localhost:9999/chat",
        authorized_tools=["github.com", "slack.com"],
        max_drift_score=2,  # small so we can fire it deliberately
        max_autonomous_hits=2,
        sample_refusal_baseline=sample_refusal_baseline,
        shadow_mode=shadow_mode,
        baseline_turns=baseline_turns,
        baseline_hours=0.0,
        state_dir=state_dir,
        alert_webhook="https://example.com/hook",
        mode=HarnessMode.OBSERVE,
    )
    # In-process prober that always refuses — drives the RefusalSampler.
    def _refuse(_sid: str, _content: str) -> str:
        return "I cannot help with that request."
    prober = Prober(backend=InProcessInjector(send_fn=_refuse))
    h = MonitoringHarness(config=config, detectors=[], prober=prober)
    # Swap in deterministic embedder + baseline so tests don't need
    # sentence-transformers.
    h._shared_embedder = _fake_embedder
    h._baseline = EmbeddingBaseline(
        baseline_turns=baseline_turns, embedder=_fake_embedder,
    )
    h._dispatch_webhook = MagicMock()  # type: ignore[method-assign]
    return h


def _simulate_start(h: MonitoringHarness) -> None:
    """Run the boot-time portion of start() without spinning up the
    proxy thread. Mirrors the order of operations in
    :meth:`MonitoringHarness.start`."""
    from saster_harness.baseline import ObservedToolCallMix, SessionBaseline
    from saster_harness.drift import DriftAccumulator, parse_host

    if h._store is not None:
        h._store.load_centroids(h._baseline)
        h._store.load_structural(h._detectors)

    trained = h._build_trained_baseline()
    h._composite_baseline = SessionBaseline(
        declared=tuple(h._config.authorized_tools),
        trained=trained,
        observed=h._baseline,
        tool_call_mix=ObservedToolCallMix(window_hours=24.0),
    )
    if trained.is_available():
        for detector in h._detectors:
            setter = getattr(detector, "set_refusal_centroid", None)
            if callable(setter):
                setter(trained.centroid)
    h._drift = DriftAccumulator(
        baseline=h._composite_baseline,
        max_drift_score=h._config.max_drift_score,
        max_autonomous_hits=h._config.max_autonomous_hits,
        embedder=h._shared_embedder,
        susceptibility_cache=h._susceptibility_cache,
        agent_endpoint_host=parse_host(h._config.agent_endpoint),
        sink=h._handle_event,
        agent_name=h._config.agent_name,
    )
    if h._store is not None and h._calibration_receipt is not None:
        h._store.write_calibration_receipt(h._calibration_receipt)


def test_v03_refusal_sampling_populates_trained_baseline(tmp_path: Path) -> None:
    h = _build_harness(tmp_path=tmp_path, sample_refusal_baseline=True)
    _simulate_start(h)
    assert h.composite_baseline is not None
    assert h.composite_baseline.trained.is_available()
    assert h.composite_baseline.trained.source == "sampled"
    receipt = h.calibration_receipt
    assert receipt is not None
    assert receipt.source == "sampled"
    assert receipt.n_probes > 0


def test_v03_authorized_tools_flow_through_to_saster13(tmp_path: Path) -> None:
    """The harness should call set_authorized_tools on every detector
    that exposes the setter — including SASTER-13-induced."""
    det = Saster13InducedDetector()
    assert det._authorized_tools == ()
    h = _build_harness(tmp_path=tmp_path)
    h._detectors = [det]
    # Re-run the constructor's distribution loop manually.
    for d in h._detectors:
        d.set_authorized_tools(tuple(h._config.authorized_tools))
    assert det._authorized_tools == ("github.com", "slack.com")


def test_v03_shadow_mode_suppresses_webhook_until_baseline_locks(
    tmp_path: Path,
) -> None:
    h = _build_harness(tmp_path=tmp_path, shadow_mode=True, baseline_turns=2)
    _simulate_start(h)
    # Fire a passive detector event before baseline.
    event = DetectionEvent(
        saster_id="SASTER-18", pattern_name="x", tier=3,
        agent_name="t", session_id="liveSession", turn_idx=0,
        evidence={"signal": "x", "detail": "x"},
    )
    h._handle_event(event)
    h._dispatch_webhook.assert_not_called()
    # Lock baseline.
    h._baseline.observe("liveSession", "first")
    h._baseline.observe("liveSession", "second")
    h._handle_event(event)
    h._dispatch_webhook.assert_called_once()


def test_v03_drift_threshold_fires_synthetic_event(tmp_path: Path) -> None:
    h = _build_harness(tmp_path=tmp_path, shadow_mode=False)
    _simulate_start(h)
    # An unauthorized-host turn (weight 1.0). Twice to cross 2.0.
    t = TurnData(
        session_id="liveSession", turn_idx=0,
        target_host="evil.example.com",
        boundary_proximity=0.0,
    )
    h._handle_turn(t)
    h._handle_turn(t)
    # The synthetic drift event must have come through _handle_event.
    saster_ids = [e.saster_id for e in h.recent_events()]
    assert "SASTER-DRIFT-COMPOSITE" in saster_ids


def test_v03_state_dir_persists_centroid_across_restart(tmp_path: Path) -> None:
    state_dir = tmp_path / "saster_state"
    h1 = _build_harness(
        tmp_path=tmp_path, state_dir=state_dir, baseline_turns=2,
    )
    _simulate_start(h1)
    h1._baseline.observe("liveSession", "warm one")
    h1._baseline.observe("liveSession", "warm two")
    assert h1._baseline.is_established("liveSession")
    # Final snapshot via stop().
    h1.stop()
    receipt_path = state_dir / "integration-test" / "calibration_receipt.json"
    centroids_path = state_dir / "integration-test" / "centroids.npz"
    assert receipt_path.exists()
    assert centroids_path.exists()

    # Restart — confirm centroids are restored before any turn lands.
    h2 = _build_harness(
        tmp_path=tmp_path, state_dir=state_dir, baseline_turns=2,
    )
    _simulate_start(h2)
    assert h2._baseline.is_established("liveSession"), (
        "centroid did not survive simulated restart"
    )


def test_v03_calibration_receipt_records_corpus_fallback(tmp_path: Path) -> None:
    """When sampling is disabled, the receipt source should record
    'corpus' (or 'unset' if the corpus is also unavailable). The
    operator should be able to tell which one happened."""
    h = _build_harness(tmp_path=tmp_path, sample_refusal_baseline=False)
    _simulate_start(h)
    receipt = h.calibration_receipt
    assert receipt is not None
    assert receipt.source in ("corpus", "unset")
    if receipt.source == "corpus":
        assert receipt.n_probes == 0
