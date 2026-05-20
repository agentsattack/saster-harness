"""Persistence layer — disk-backed state for the v0.3 harness.

When :attr:`~saster_harness.config.MonitoringConfig.state_dir` is set,
the harness reads and writes four artifacts under
``<state_dir>/<agent_name>/``:

- ``centroids.npz`` — per-session embedding centroids exported by
  :meth:`EmbeddingBaseline.export_state`. Restored at start; refreshed
  at every periodic snapshot and at shutdown.
- ``structural_baselines.json`` — per-session SASTER-33 structural
  baseline state. Restored / snapshotted alongside centroids.
- ``drift.jsonl`` — append-only log of ``SASTER-DRIFT-COMPOSITE`` and
  ``SASTER-AUTONOMOUS-ESCALATION`` synthetic events. Never read at
  startup; this is an audit artifact, not a hot-path cache.
- ``calibration_receipt.json`` — the
  :class:`~saster_harness.refusal_sampler.CalibrationReceipt` from
  boot-time refusal sampling. Overwritten on each ``start()``.

The default config has ``state_dir=None`` so v0.2 behavior is
preserved — the harness writes nothing unless the operator opts in.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import numpy as np

from .baseline import EmbeddingBaseline
from .event import DetectionEvent
from .refusal_sampler import CalibrationReceipt

logger = logging.getLogger(__name__)


_DRIFT_EVENT_IDS = ("SASTER-DRIFT-COMPOSITE", "SASTER-AUTONOMOUS-ESCALATION")


class PersistenceStore:
    """File-backed persistence for harness state.

    The store is intentionally tolerant: missing files are treated as
    empty state (first-run on a fresh ``state_dir``), and corrupt
    files are logged at WARNING and skipped rather than crashing the
    harness. The harness must keep running even when the disk is
    misbehaving.
    """

    def __init__(self, state_dir: Path, agent_name: str) -> None:
        self._agent_dir = Path(state_dir) / agent_name
        self._agent_dir.mkdir(parents=True, exist_ok=True)
        self._write_lock = threading.Lock()

    # ----------------------------------------------------------------
    # Paths
    # ----------------------------------------------------------------

    @property
    def centroids_path(self) -> Path:
        return self._agent_dir / "centroids.npz"

    @property
    def structural_path(self) -> Path:
        return self._agent_dir / "structural_baselines.json"

    @property
    def drift_log_path(self) -> Path:
        return self._agent_dir / "drift.jsonl"

    @property
    def receipt_path(self) -> Path:
        return self._agent_dir / "calibration_receipt.json"

    # ----------------------------------------------------------------
    # Centroids (EmbeddingBaseline)
    # ----------------------------------------------------------------

    def save_centroids(self, baseline: EmbeddingBaseline) -> None:
        snapshot = baseline.export_state()
        if not snapshot:
            return
        # Serialize each session's centroid as its own array key in a
        # single .npz file plus a sidecar JSON with metadata. We use
        # np.savez_compressed for the vectors and stash the metadata
        # inline as a 0-d array of object dtype for portability.
        sess_ids = sorted(snapshot.keys())
        with self._write_lock:
            try:
                arrays: dict[str, np.ndarray] = {}
                metadata: dict[str, dict[str, Any]] = {}
                for sid in sess_ids:
                    payload = snapshot[sid]
                    centroid = np.asarray(payload["centroid"], dtype=np.float32)
                    arrays[f"centroid::{sid}"] = centroid
                    metadata[sid] = {
                        "turns_observed": payload.get("turns_observed", 0),
                        "started_at": payload.get("started_at", 0.0),
                    }
                arrays["__metadata__"] = np.asarray(
                    json.dumps(metadata), dtype=object,
                )
                # np.savez_compressed auto-appends .npz if missing; use a
                # temp name that already ends in .npz so the in-place
                # rename target matches what numpy actually wrote.
                tmp = self._agent_dir / "centroids.tmp.npz"
                with tmp.open("wb") as fh:
                    np.savez_compressed(fh, **arrays)
                os.replace(tmp, self.centroids_path)
            except Exception:  # pragma: no cover — defensive
                logger.exception(
                    "Failed to save centroids to %s", self.centroids_path,
                )

    def load_centroids(self, baseline: EmbeddingBaseline) -> int:
        """Restore session centroids. Returns the number of sessions
        loaded."""
        if not self.centroids_path.exists():
            return 0
        try:
            with np.load(self.centroids_path, allow_pickle=True) as fh:
                meta_raw = fh.get("__metadata__")
                metadata: dict[str, dict[str, Any]] = {}
                if meta_raw is not None:
                    try:
                        metadata = json.loads(str(meta_raw))
                    except Exception:
                        metadata = {}
                snapshot: dict[str, dict[str, Any]] = {}
                for key in fh.files:
                    if not key.startswith("centroid::"):
                        continue
                    session_id = key[len("centroid::"):]
                    centroid_arr = fh[key]
                    snapshot[session_id] = {
                        "centroid": centroid_arr.tolist(),
                        "turns_observed": metadata.get(
                            session_id, {},
                        ).get("turns_observed", 0),
                        "started_at": metadata.get(
                            session_id, {},
                        ).get("started_at", 0.0),
                    }
        except Exception:  # pragma: no cover — defensive
            logger.exception(
                "Failed to load centroids from %s; starting fresh.",
                self.centroids_path,
            )
            return 0
        baseline.import_state(snapshot)
        logger.info("Loaded %d session centroid(s) from %s.",
                    len(snapshot), self.centroids_path)
        return len(snapshot)

    # ----------------------------------------------------------------
    # Structural baselines (SASTER-33)
    # ----------------------------------------------------------------

    def save_structural(self, detectors: Iterable[Any]) -> None:
        """Iterate ``detectors`` looking for ones that expose
        ``export_state`` for structural baselines (SASTER-33). Writes
        a single combined JSON keyed by ``saster_id``."""
        out: dict[str, dict[str, Any]] = {}
        for detector in detectors:
            export = getattr(detector, "export_state", None)
            saster_id = getattr(detector, "saster_id", None)
            if callable(export) and saster_id == "SASTER-33":
                try:
                    out[saster_id] = export()
                except Exception:  # pragma: no cover — defensive
                    logger.exception("export_state() raised for %s", saster_id)
        if not out:
            return
        with self._write_lock:
            try:
                tmp = self.structural_path.with_suffix(".json.tmp")
                tmp.write_text(json.dumps(out, indent=2), encoding="utf-8")
                os.replace(tmp, self.structural_path)
            except Exception:  # pragma: no cover — defensive
                logger.exception(
                    "Failed to save structural baselines to %s",
                    self.structural_path,
                )

    def load_structural(self, detectors: Iterable[Any]) -> None:
        if not self.structural_path.exists():
            return
        try:
            payload = json.loads(
                self.structural_path.read_text(encoding="utf-8"),
            )
        except Exception:  # pragma: no cover — defensive
            logger.exception(
                "Failed to load structural baselines from %s; starting fresh.",
                self.structural_path,
            )
            return
        for detector in detectors:
            saster_id = getattr(detector, "saster_id", None)
            import_state = getattr(detector, "import_state", None)
            if not (saster_id and callable(import_state)):
                continue
            if saster_id in payload:
                try:
                    import_state(payload[saster_id])
                except Exception:  # pragma: no cover — defensive
                    logger.exception(
                        "import_state() failed for %s", saster_id,
                    )

    # ----------------------------------------------------------------
    # Calibration receipt
    # ----------------------------------------------------------------

    def write_calibration_receipt(self, receipt: CalibrationReceipt | None) -> None:
        if receipt is None:
            return
        with self._write_lock:
            try:
                tmp = self.receipt_path.with_suffix(".json.tmp")
                tmp.write_text(
                    json.dumps(receipt.to_dict(), indent=2),
                    encoding="utf-8",
                )
                os.replace(tmp, self.receipt_path)
            except Exception:  # pragma: no cover — defensive
                logger.exception(
                    "Failed to write calibration receipt to %s",
                    self.receipt_path,
                )

    def read_calibration_receipt(self) -> dict[str, Any] | None:
        if not self.receipt_path.exists():
            return None
        try:
            return json.loads(self.receipt_path.read_text(encoding="utf-8"))
        except Exception:  # pragma: no cover — defensive
            logger.exception(
                "Failed to read calibration receipt from %s",
                self.receipt_path,
            )
            return None

    # ----------------------------------------------------------------
    # Drift log (append-only)
    # ----------------------------------------------------------------

    def append_drift_event(self, event: DetectionEvent) -> None:
        """Append one drift / escalation event to the JSONL log. Other
        detector event types are filtered out at the call site."""
        if event.saster_id not in _DRIFT_EVENT_IDS:
            return
        with self._write_lock:
            try:
                with self.drift_log_path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(event.to_dict()) + "\n")
            except Exception:  # pragma: no cover — defensive
                logger.exception(
                    "Failed to append drift event to %s",
                    self.drift_log_path,
                )

    # ----------------------------------------------------------------
    # Composite snapshot
    # ----------------------------------------------------------------

    def snapshot(
        self,
        embedding_baseline: EmbeddingBaseline,
        detectors: Iterable[Any],
    ) -> None:
        """Best-effort full snapshot of in-memory state to disk."""
        self.save_centroids(embedding_baseline)
        self.save_structural(detectors)
