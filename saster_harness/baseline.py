"""Per-session embedding baseline plus the composite baseline shell.

This module hosts two classes:

- :class:`EmbeddingBaseline` — per-session embedding centroid.
  Observes the first ``baseline_turns`` in-band turns of a session
  and from then on scores every turn as
  ``1 - cosine_similarity(turn, centroid)`` clipped to ``[0, 1]``.
  The result is the ``boundary_proximity`` field on
  :class:`~saster_harness.event.TurnData`. v0.3 adds optional
  clock-time gating: when ``baseline_hours > 0``, the baseline locks
  in only after BOTH the turn count AND the wall-clock duration
  conditions are met.

- :class:`SessionBaseline` — composite baseline holding all three
  passive sources from the slide-11 boundary calculation:
  ``declared`` (operator-supplied ``authorized_tools``), ``trained``
  (refusal-distribution centroid from the boot-time refusal sampler),
  and ``observed`` (an :class:`EmbeddingBaseline` plus the rolling
  ``tool_call_mix`` window). Populated in
  :meth:`saster_harness.harness.MonitoringHarness.start`. Consumed by
  :class:`saster_harness.drift.DriftAccumulator` to compute the four
  per-turn drift signals.

The class previously called ``SessionBaseline`` in v0.2 has been
renamed to :class:`EmbeddingBaseline`; the v0.2 name is re-exported
as an alias so external code keeps working.

The embedding-only baseline is intentionally simple. It does not
learn a manifold, it does not run SVM, it does not estimate density.
The premise is that for most agents the distribution of "normal" turn
embeddings sits in a tight neighborhood of the session centroid, and
a turn whose embedding has drifted is — at minimum — worth a detector
reading the turn body more carefully.

The baseline is *necessary but not sufficient* for detection: it
raises ``boundary_proximity``, but only a SASTER detector decides
whether a pattern has fired. This separation is deliberate. Drift on
its own is too noisy to alert on; combined with a pattern-specific
detector it becomes actionable.
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from collections import Counter, deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class _SessionState:
    embeddings: list[np.ndarray] = field(default_factory=list)
    centroid: np.ndarray | None = None
    established: bool = False
    started_at: float = field(default_factory=time.time)


class EmbeddingBaseline:
    """Thread-safe per-session embedding baseline.

    Parameters
    ----------
    model_name
        sentence-transformers model identifier. Default
        ``"all-MiniLM-L6-v2"`` (~90 MB, 384-dim embeddings).
    baseline_turns
        Number of turns observed before the baseline is considered
        established. Until established, :meth:`observe` returns ``None``.
    baseline_hours
        Optional wall-clock duration the session must accumulate before
        the baseline locks in. Default ``0.0`` (no clock-time gate; the
        baseline locks as soon as ``baseline_turns`` is reached, matching
        v0.2 behavior). When ``> 0.0``, ``is_established`` returns
        ``True`` only when BOTH the turn count AND the wall-clock
        duration conditions are met.
    embedder
        Optional shared embedder callable ``str -> np.ndarray``. When
        supplied, the baseline routes all embeddings through it.

    Notes
    -----
    The embedding model is loaded lazily on first use. Loading is blocking
    (~5–15 s for the default model on cold cache) — for low-latency proxies,
    pre-warm by calling :meth:`warm` during startup.
    """

    def __init__(
        self,
        model_name: str = "all-MiniLM-L6-v2",
        baseline_turns: int = 10,
        baseline_hours: float = 0.0,
        embedder: Callable[[str], np.ndarray] | None = None,
    ) -> None:
        self._model_name = model_name
        self._baseline_turns = baseline_turns
        self._baseline_hours = baseline_hours
        self._embedder = embedder
        self._model: object | None = None
        self._model_lock = threading.Lock()
        self._sessions: dict[str, _SessionState] = {}
        self._sessions_lock = threading.Lock()

    # ----------------------------------------------------------------
    # Model lifecycle
    # ----------------------------------------------------------------

    def warm(self) -> None:
        """Force-load the embedding model. Safe to call multiple times.
        No-op when a shared embedder was supplied — the shared embedder
        handles its own lazy-load."""
        if self._embedder is not None:
            try:
                self._embedder("warmup")
            except Exception:  # pragma: no cover — defensive
                logger.exception("Shared embedder warmup failed")
            return
        self._ensure_model()

    def _ensure_model(self) -> object:
        if self._model is not None:
            return self._model
        with self._model_lock:
            if self._model is not None:
                return self._model
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise RuntimeError(
                    "sentence-transformers is required for the session baseline. "
                    "Install it via `pip install saster-harness[dev]` or "
                    "`pip install sentence-transformers`."
                ) from exc
            logger.info("Loading embedding model %s …", self._model_name)
            self._model = SentenceTransformer(self._model_name)
            logger.info("Embedding model ready.")
            return self._model

    # ----------------------------------------------------------------
    # Public API
    # ----------------------------------------------------------------

    def observe(self, session_id: str, text: str) -> float | None:
        """Add a turn to ``session_id``'s baseline and return its boundary
        proximity once the baseline is established.

        Returns
        -------
        float in [0, 1]
            Boundary proximity for this turn, computed against the centroid
            of the prior in-baseline turns. ``0.0`` = identical, ``1.0`` =
            orthogonal.
        None
            Returned during the baseline-establishment phase. The turn IS
            added to the running centroid.
        """
        if not text or not text.strip():
            return None
        embedding = self._embed(text)
        with self._sessions_lock:
            state = self._sessions.setdefault(session_id, _SessionState())
            if not state.established:
                state.embeddings.append(embedding)
                if self._meets_lock_criteria(state):
                    state.centroid = _normalize(
                        np.mean(np.stack(state.embeddings), axis=0)
                    )
                    state.established = True
                    logger.debug(
                        "Baseline established for session %s after %d turns "
                        "and %.1f s",
                        session_id,
                        len(state.embeddings),
                        time.time() - state.started_at,
                    )
                return None
            assert state.centroid is not None
            sim = float(np.dot(_normalize(embedding), state.centroid))
            return max(0.0, min(1.0, 1.0 - sim))

    def _meets_lock_criteria(self, state: _SessionState) -> bool:
        """Both the turn count and the clock-time conditions must hold."""
        if len(state.embeddings) < self._baseline_turns:
            return False
        if self._baseline_hours > 0.0:
            elapsed_s = time.time() - state.started_at
            if elapsed_s < self._baseline_hours * 3600.0:
                return False
        return True

    def reset(self, session_id: str | None = None) -> None:
        with self._sessions_lock:
            if session_id is None:
                self._sessions.clear()
            else:
                self._sessions.pop(session_id, None)

    def is_established(self, session_id: str) -> bool:
        with self._sessions_lock:
            state = self._sessions.get(session_id)
            return state is not None and state.established

    def centroid_for(self, session_id: str) -> np.ndarray | None:
        """Return the per-session centroid once established, else None.

        Used by persistence to snapshot the locked centroid to disk."""
        with self._sessions_lock:
            state = self._sessions.get(session_id)
            if state is None or not state.established:
                return None
            return state.centroid

    def export_state(self) -> dict[str, dict[str, Any]]:
        """Return a JSON-friendly snapshot of every established session
        baseline. Used by the persistence layer."""
        out: dict[str, dict[str, Any]] = {}
        with self._sessions_lock:
            for session_id, state in self._sessions.items():
                if state.established and state.centroid is not None:
                    out[session_id] = {
                        "centroid": state.centroid.tolist(),
                        "turns_observed": len(state.embeddings),
                        "started_at": state.started_at,
                    }
        return out

    def import_state(self, snapshot: dict[str, dict[str, Any]]) -> None:
        """Restore session centroids from a previous :meth:`export_state`
        snapshot. Skips sessions whose centroid dimensionality does not
        match the configured embedder; logs at WARNING."""
        with self._sessions_lock:
            for session_id, payload in snapshot.items():
                centroid_list = payload.get("centroid") or []
                if not centroid_list:
                    continue
                centroid = np.asarray(centroid_list, dtype=np.float32)
                state = _SessionState()
                state.centroid = centroid
                state.established = True
                state.started_at = float(payload.get("started_at", time.time()))
                state.embeddings = []  # centroid is canonical; raw embeddings are not persisted
                self._sessions[session_id] = state

    # ----------------------------------------------------------------
    # Internals
    # ----------------------------------------------------------------

    def _embed(self, text: str) -> np.ndarray:
        if self._embedder is not None:
            return self._embedder(text)
        model = self._ensure_model()
        vec = model.encode([text], show_progress_bar=False)[0]  # type: ignore[attr-defined]
        return np.asarray(vec, dtype=np.float32)


@dataclass
class TrainedRefusalBaseline:
    """The TRAINED source — the agent's refusal-distribution signature.

    Populated at boot by :class:`saster_harness.refusal_sampler.RefusalSampler`
    when ``MonitoringConfig.sample_refusal_baseline`` is ``True``. Falls
    back to the bundled 50-phrase refusal corpus centroid when the agent
    endpoint is unreachable or sampling is disabled.

    Attributes
    ----------
    centroid
        L2-normalized 1-D numpy array — the mean embedding of N
        refusal responses sampled from the target. ``None`` when the
        sampler has not run and no fallback was supplied.
    n_probes
        Number of refusal-eliciting prompts the centroid was averaged
        over. Zero when the centroid was loaded from the bundled
        corpus only.
    sampled_at
        Unix epoch when the sampling completed. ``0.0`` for the
        corpus-only fallback.
    source
        ``"sampled"`` when probed from the agent, ``"corpus"`` when
        derived from the bundled ``refusals.txt`` file, ``"unset"``
        when neither is available.
    """

    centroid: np.ndarray | None = None
    n_probes: int = 0
    sampled_at: float = 0.0
    source: str = "unset"

    def is_available(self) -> bool:
        return self.centroid is not None


class ObservedToolCallMix:
    """Rolling tool-call-mix counter with a clock-time window.

    Tracks the distribution of tool/host calls observed on the wire over
    the last ``window_hours`` hours. Used by
    :class:`saster_harness.drift.DriftAccumulator` as the OBSERVED
    behavioral baseline against which sudden mix shifts register as
    behavioral anomalies.

    The window is enforced lazily on each observation — entries older
    than ``window_hours`` are dropped before the new entry is added.
    For the typical agent the deque stays small (handful of distinct
    tools per session); no time-based reaper thread is required.
    """

    def __init__(self, window_hours: float = 24.0) -> None:
        self._window_seconds = window_hours * 3600.0
        # Deque of (timestamp, tool_id) — append-right, drop-from-left.
        self._entries: deque[tuple[float, str]] = deque()
        self._lock = threading.Lock()

    def observe(self, tool_id: str, timestamp: float | None = None) -> None:
        """Record one tool/host call. ``tool_id`` is the canonical
        identifier (URL host, tool name, etc.)."""
        ts = timestamp if timestamp is not None else time.time()
        with self._lock:
            self._evict_locked(ts)
            self._entries.append((ts, tool_id))

    def distribution(self, now: float | None = None) -> dict[str, float]:
        """Return tool_id → frequency over the current window."""
        cutoff_now = now if now is not None else time.time()
        with self._lock:
            self._evict_locked(cutoff_now)
            if not self._entries:
                return {}
            counts = Counter(tool_id for _, tool_id in self._entries)
            total = sum(counts.values())
            return {tool_id: c / total for tool_id, c in counts.items()}

    def n_observations(self, now: float | None = None) -> int:
        cutoff_now = now if now is not None else time.time()
        with self._lock:
            self._evict_locked(cutoff_now)
            return len(self._entries)

    def _evict_locked(self, now: float) -> None:
        cutoff = now - self._window_seconds
        while self._entries and self._entries[0][0] < cutoff:
            self._entries.popleft()


class SessionBaseline:
    """Composite baseline holding the three passive sources.

    Constructed by :class:`saster_harness.harness.MonitoringHarness` at
    start. The named fields match the slide-11 pseudocode exactly:

    - ``declared`` — the operator's
      :attr:`~saster_harness.config.MonitoringConfig.authorized_tools`,
      stored as an immutable tuple.
    - ``trained`` — a :class:`TrainedRefusalBaseline` populated by
      :class:`~saster_harness.refusal_sampler.RefusalSampler` at boot,
      or left empty when ``sample_refusal_baseline=False``.
    - ``observed`` — the :class:`EmbeddingBaseline` instance plus an
      :class:`ObservedToolCallMix` over a configurable clock window.

    The composite is read-only after construction; the contained
    ``EmbeddingBaseline`` and ``ObservedToolCallMix`` continue to
    mutate as turns arrive on the wire. The
    :class:`saster_harness.drift.DriftAccumulator` consumes this
    composite to compute the per-turn signal functions named in the
    slide pseudocode.
    """

    def __init__(
        self,
        declared: tuple[str, ...],
        trained: TrainedRefusalBaseline,
        observed: EmbeddingBaseline,
        tool_call_mix: ObservedToolCallMix | None = None,
    ) -> None:
        self.declared: tuple[str, ...] = tuple(declared)
        self.trained: TrainedRefusalBaseline = trained
        self.observed: EmbeddingBaseline = observed
        self.tool_call_mix: ObservedToolCallMix = (
            tool_call_mix if tool_call_mix is not None else ObservedToolCallMix()
        )

    def declared_fingerprint(self) -> str:
        """Stable hash of the declared allow-list. Used in calibration
        receipts to record exactly which allow-list a baseline was
        built against."""
        payload = "\n".join(sorted(self.declared)).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()[:16]


def _normalize(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    if n == 0.0:
        return v
    return v / n
