"""Per-session embedding baseline.

For each agent session, the baseline observes the first ``baseline_turns``
in-band turns, computes the centroid of their embeddings, and from then on
scores every turn as ``1 - cosine_similarity(turn, centroid)`` clipped to
``[0, 1]``. The result is the ``boundary_proximity`` field on
:class:`~saster_harness.event.TurnData`.

This is intentionally simple. It does not learn a manifold, it does not run
SVM, it does not estimate density. The premise is that for most agents the
distribution of "normal" turn embeddings sits in a tight neighborhood of the
session centroid, and a turn whose embedding has drifted is — at minimum —
worth a detector reading the turn body more carefully.

The baseline is *necessary but not sufficient* for detection: it raises
boundary_proximity, but only a SASTER detector decides whether a pattern has
fired. This separation is deliberate. Drift on its own is too noisy to alert
on; combined with a pattern-specific detector it becomes actionable.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class _SessionState:
    embeddings: list[np.ndarray] = field(default_factory=list)
    centroid: np.ndarray | None = None
    established: bool = False


class SessionBaseline:
    """Thread-safe per-session embedding baseline.

    Parameters
    ----------
    model_name
        sentence-transformers model identifier. Default
        ``"all-MiniLM-L6-v2"`` (~90 MB, 384-dim embeddings).
    baseline_turns
        Number of turns observed before the baseline is considered
        established. Until established, :meth:`observe` returns ``None``.

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
    ) -> None:
        self._model_name = model_name
        self._baseline_turns = baseline_turns
        self._model: object | None = None
        self._model_lock = threading.Lock()
        self._sessions: dict[str, _SessionState] = {}
        self._sessions_lock = threading.Lock()

    # ----------------------------------------------------------------
    # Model lifecycle
    # ----------------------------------------------------------------

    def warm(self) -> None:
        """Force-load the embedding model. Safe to call multiple times."""
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
            Returned during the baseline-establishment phase (the first
            ``baseline_turns`` turns of a session). The turn IS added to the
            running centroid.
        """
        if not text or not text.strip():
            return None
        embedding = self._embed(text)
        with self._sessions_lock:
            state = self._sessions.setdefault(session_id, _SessionState())
            if not state.established:
                state.embeddings.append(embedding)
                if len(state.embeddings) >= self._baseline_turns:
                    state.centroid = _normalize(
                        np.mean(np.stack(state.embeddings), axis=0)
                    )
                    state.established = True
                    logger.debug(
                        "Baseline established for session %s after %d turns",
                        session_id,
                        len(state.embeddings),
                    )
                return None
            assert state.centroid is not None
            sim = float(np.dot(_normalize(embedding), state.centroid))
            # cosine sim is in [-1, 1] for general vectors; for embedded text
            # it sits in [0, 1]. Map to a 0..1 boundary-proximity score where
            # 1 = maximally drifted.
            return max(0.0, min(1.0, 1.0 - sim))

    def reset(self, session_id: str | None = None) -> None:
        """Drop the baseline for a single session, or all sessions when
        ``session_id`` is ``None``. Used between recording takes and when
        a session terminates."""
        with self._sessions_lock:
            if session_id is None:
                self._sessions.clear()
            else:
                self._sessions.pop(session_id, None)

    def is_established(self, session_id: str) -> bool:
        with self._sessions_lock:
            state = self._sessions.get(session_id)
            return state is not None and state.established

    # ----------------------------------------------------------------
    # Internals
    # ----------------------------------------------------------------

    def _embed(self, text: str) -> np.ndarray:
        model = self._ensure_model()
        vec = model.encode([text], show_progress_bar=False)[0]  # type: ignore[attr-defined]
        return np.asarray(vec, dtype=np.float32)


def _normalize(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    if n == 0.0:
        return v
    return v / n
