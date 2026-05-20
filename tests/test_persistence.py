"""Tests for the v0.3 PersistenceStore — disk-backed harness state.

Covers:

- Centroid round-trip (save → load → matching centroid)
- Structural baseline round-trip (SASTER-33 state)
- Calibration receipt write/read
- Drift event append-only log filters non-drift events
- Tolerant load: missing files do not raise, corrupt files log + skip
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from saster_harness.baseline import EmbeddingBaseline
from saster_harness.detectors.saster_33 import ContextStrippingDetector
from saster_harness.event import DetectionEvent
from saster_harness.persistence import PersistenceStore
from saster_harness.refusal_sampler import CalibrationReceipt


def _fake_embedder(text: str) -> np.ndarray:
    rng = np.random.default_rng(abs(hash(text)) % (2**32))
    return rng.standard_normal(8).astype(np.float32)


def test_centroids_save_then_load_round_trip(tmp_path: Path) -> None:
    store = PersistenceStore(state_dir=tmp_path, agent_name="agent-a")

    bl_a = EmbeddingBaseline(baseline_turns=2, embedder=_fake_embedder)
    bl_a.observe("session1", "one")
    bl_a.observe("session1", "two")
    bl_a.observe("session2", "alpha")
    bl_a.observe("session2", "beta")

    store.save_centroids(bl_a)
    assert store.centroids_path.exists()

    bl_b = EmbeddingBaseline(baseline_turns=2, embedder=_fake_embedder)
    n = store.load_centroids(bl_b)
    assert n == 2
    assert bl_b.is_established("session1")
    assert bl_b.is_established("session2")
    # Centroids match
    np.testing.assert_allclose(
        bl_a.centroid_for("session1"),
        bl_b.centroid_for("session1"),
        atol=1e-6,
    )


def test_centroids_load_returns_zero_when_file_missing(tmp_path: Path) -> None:
    store = PersistenceStore(state_dir=tmp_path, agent_name="agent-a")
    bl = EmbeddingBaseline(baseline_turns=2, embedder=_fake_embedder)
    assert store.load_centroids(bl) == 0


def test_structural_baseline_round_trip(tmp_path: Path) -> None:
    store = PersistenceStore(state_dir=tmp_path, agent_name="agent-a")
    detector_a = ContextStrippingDetector(min_turns=3)

    # Drive the detector through a few turns to lock in expects_system.
    from saster_harness.event import TurnData

    def _turn(session: str, has_system: bool) -> TurnData:
        return TurnData(
            session_id=session,
            turn_idx=0,
            has_system_message=has_system,
        )

    for _ in range(4):
        detector_a.evaluate(_turn("s1", True))

    snapshot = detector_a.export_state()
    assert "s1" in snapshot
    assert snapshot["s1"]["expects_system"] is True

    store.save_structural([detector_a])
    assert store.structural_path.exists()

    detector_b = ContextStrippingDetector(min_turns=3)
    store.load_structural([detector_b])
    restored = detector_b.export_state()
    assert restored["s1"]["expects_system"] is True


def test_calibration_receipt_write_and_read(tmp_path: Path) -> None:
    store = PersistenceStore(state_dir=tmp_path, agent_name="agent-a")
    receipt = CalibrationReceipt(
        sampled_at=12345.0,
        agent_endpoint="http://test/",
        n_attempted=10,
        n_probes=8,
        centroid_dim=384,
        embedding_model="all-MiniLM-L6-v2",
        corpus_sha="deadbeef",
        source="sampled",
        failures=["probe 3: timeout"],
    )
    store.write_calibration_receipt(receipt)
    assert store.receipt_path.exists()
    payload = store.read_calibration_receipt()
    assert payload is not None
    assert payload["source"] == "sampled"
    assert payload["n_probes"] == 8
    assert payload["centroid_dim"] == 384


def test_drift_log_appends_only_drift_events(tmp_path: Path) -> None:
    store = PersistenceStore(state_dir=tmp_path, agent_name="agent-a")
    drift_event = DetectionEvent(
        saster_id="SASTER-DRIFT-COMPOSITE",
        pattern_name="Boundary Drift Composite",
        tier=4, agent_name="t", session_id="s1", turn_idx=0,
        evidence={"signal": "x", "detail": "y", "drift_score": 5.2},
    )
    non_drift_event = DetectionEvent(
        saster_id="SASTER-18",
        pattern_name="Semantic Recasting",
        tier=3, agent_name="t", session_id="s1", turn_idx=0,
        evidence={"signal": "x", "detail": "y"},
    )

    store.append_drift_event(drift_event)
    store.append_drift_event(non_drift_event)  # filtered out

    assert store.drift_log_path.exists()
    lines = store.drift_log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["saster_id"] == "SASTER-DRIFT-COMPOSITE"


def test_snapshot_combines_centroids_and_structural(tmp_path: Path) -> None:
    store = PersistenceStore(state_dir=tmp_path, agent_name="agent-a")
    bl = EmbeddingBaseline(baseline_turns=2, embedder=_fake_embedder)
    bl.observe("s1", "one")
    bl.observe("s1", "two")
    det = ContextStrippingDetector(min_turns=3)
    from saster_harness.event import TurnData

    for _ in range(4):
        det.evaluate(TurnData(session_id="s1", turn_idx=0, has_system_message=True))

    store.snapshot(bl, [det])
    assert store.centroids_path.exists()
    assert store.structural_path.exists()


def test_load_tolerates_corrupt_centroid_file(tmp_path: Path) -> None:
    store = PersistenceStore(state_dir=tmp_path, agent_name="agent-a")
    store.centroids_path.write_bytes(b"this is not a valid .npz file")
    bl = EmbeddingBaseline(baseline_turns=2, embedder=_fake_embedder)
    # Should NOT raise — corrupt file is logged and skipped.
    n = store.load_centroids(bl)
    assert n == 0
