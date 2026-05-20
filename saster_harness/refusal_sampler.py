"""RefusalSampler — boot-time sampling of the target agent's refusal
signature.

The TRAINED source in the slide-11 boundary calculation. The sampler
takes a :class:`~saster_harness.prober.Prober` (typically an
:class:`HttpInjector` pointed at ``config.agent_endpoint``) and the
bundled ``corpora/refusal_probes.txt`` file, sends each refusal-
eliciting prompt to the agent, embeds the responses with the shared
embedder, and computes their L2-normalized mean. The resulting centroid
is the agent's empirical refusal centroid — used by
:class:`saster_harness.drift.DriftAccumulator.refusal_pattern_change`
and by :class:`saster_harness.detectors.saster_18_induced.Saster18InducedDetector`.

Three failure modes are handled gracefully:

1. **No prober supplied** — sampling is skipped. The
   :class:`~saster_harness.baseline.TrainedRefusalBaseline` returned
   carries ``source="unset"`` and ``centroid=None``; downstream code
   degrades to corpus-only behavior.
2. **Prober fails on individual prompts** — that prompt's response is
   skipped. The centroid is computed over whatever responses did
   succeed. A receipt records ``n_probes`` actually used vs
   ``n_attempted``.
3. **Prober fails on every prompt** (agent endpoint unreachable, auth
   wrong, etc.) — sampling falls back to the bundled
   ``corpora/refusals.txt`` centroid. ``source="corpus"`` records the
   fallback.

The sampler is intentionally synchronous — it runs once at harness
startup, before the proxy thread starts, so the few-seconds latency
of N probes does not block the wire path."""

from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .baseline import TrainedRefusalBaseline
from .prober import Prober

logger = logging.getLogger(__name__)


_REFUSAL_PROBES_PATH = (
    Path(__file__).parent / "corpora" / "refusal_probes.txt"
)
_FALLBACK_CORPUS_PATH = (
    Path(__file__).parent / "corpora" / "refusals.txt"
)


def _load_probes(path: Path = _REFUSAL_PROBES_PATH) -> list[str]:
    """Read the refusal-eliciting probe file. Skip blank lines."""
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as fh:
        return [line.strip() for line in fh if line.strip()]


def _load_fallback_corpus(path: Path = _FALLBACK_CORPUS_PATH) -> list[str]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as fh:
        return [line.strip() for line in fh if line.strip()]


def _corpus_fingerprint(path: Path = _REFUSAL_PROBES_PATH) -> str:
    """SHA-256 of the probe file, truncated to 16 hex chars. Used by
    calibration receipts to record exactly which corpus was sampled
    against."""
    if not path.exists():
        return ""
    data = path.read_bytes()
    return hashlib.sha256(data).hexdigest()[:16]


@dataclass
class CalibrationReceipt:
    """Audit record describing how the trained refusal centroid was
    built. Persisted to ``state_dir/<agent>/calibration_receipt.json``
    when persistence is enabled.

    A receipt is the artifact a stage-credibility audit asks for:
    "show me proof your TRAINED baseline came from this agent at this
    time against this corpus." If the source was the fallback corpus
    rather than a live sample, the receipt says so honestly.
    """

    sampled_at: float
    agent_endpoint: str
    n_attempted: int
    n_probes: int
    centroid_dim: int
    embedding_model: str
    corpus_sha: str
    source: str  # "sampled" | "corpus" | "unset"
    failures: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "sampled_at": self.sampled_at,
            "agent_endpoint": self.agent_endpoint,
            "n_attempted": self.n_attempted,
            "n_probes": self.n_probes,
            "centroid_dim": self.centroid_dim,
            "embedding_model": self.embedding_model,
            "corpus_sha": self.corpus_sha,
            "source": self.source,
            "failures": list(self.failures),
        }


class RefusalSampler:
    """Build a :class:`TrainedRefusalBaseline` by probing the agent.

    Parameters
    ----------
    embedder
        Callable mapping ``str -> np.ndarray``. The harness's shared
        sentence-transformer embedder.
    embedding_model_name
        Identifier of the embedding model. Recorded on the
        calibration receipt.
    probes
        Override the bundled refusal-eliciting probe list. ``None``
        loads :file:`corpora/refusal_probes.txt`.
    fallback_corpus
        Override the fallback refusal corpus. ``None`` loads
        :file:`corpora/refusals.txt`.
    """

    def __init__(
        self,
        embedder: Callable[[str], np.ndarray],
        embedding_model_name: str = "all-MiniLM-L6-v2",
        probes: list[str] | None = None,
        fallback_corpus: list[str] | None = None,
    ) -> None:
        self._embedder = embedder
        self._embedding_model_name = embedding_model_name
        self._probes = probes if probes is not None else _load_probes()
        self._fallback = (
            fallback_corpus
            if fallback_corpus is not None
            else _load_fallback_corpus()
        )
        self._probes_sha = _corpus_fingerprint()

    def _log_sampling_preamble(
        self, prober: Prober, agent_endpoint: str, n_probes: int,
    ) -> None:
        """Log a one-line summary of what the operator is about to wait
        for. Estimates worst-case duration when the backend exposes
        ``induction_timeout``; falls back to a generic message
        otherwise. This is the v0.3.0 fix for the v0.3.0-dev gap
        where ``start()`` would block silently for the duration of
        live refusal sampling."""
        per_probe = _backend_induction_timeout(prober)
        if per_probe is not None:
            worst_case_s = per_probe * n_probes
            logger.info(
                "RefusalSampler: probing %d prompts against %s. "
                "This blocks start() and can take up to %.0f s "
                "(worst case = %d probes × %.0f s per-probe timeout). "
                "Per-probe progress follows.",
                n_probes, agent_endpoint, worst_case_s, n_probes, per_probe,
            )
        else:
            logger.info(
                "RefusalSampler: probing %d prompts against %s. "
                "This blocks start(). Per-probe progress follows.",
                n_probes, agent_endpoint,
            )

    def sample(
        self,
        prober: Prober | None,
        agent_endpoint: str,
        session_prefix: str = "refusal_sampler",
        timeout_seconds: float = 0.0,
    ) -> tuple[TrainedRefusalBaseline, CalibrationReceipt]:
        """Probe the agent and build the trained refusal centroid.

        Parameters
        ----------
        prober
            Active-injection backend. When ``None`` the sampler skips
            straight to the corpus fallback.
        agent_endpoint
            Recorded on the calibration receipt.
        session_prefix
            Prefix for the synthetic session ids each probe uses.
        timeout_seconds
            Total wall-clock budget for the live-sampling loop. When
            ``> 0.0``, the sampler breaks the loop as soon as the
            elapsed time reaches the budget; whichever probes
            completed feed the centroid. ``0.0`` (default) disables
            the cap. The harness passes
            ``MonitoringConfig.sampling_timeout_seconds`` here.

        Returns the (baseline, receipt) pair. When ``prober`` is
        ``None`` or every probe fails, the baseline falls back to the
        bundled refusal corpus centroid and the receipt records the
        fallback honestly."""
        sampled_at = time.time()
        deadline = (
            sampled_at + timeout_seconds if timeout_seconds > 0 else None
        )
        # ``n_attempted`` records the number of LIVE probe attempts
        # against the prober — it stays 0 when no prober is supplied so
        # the receipt is honest about whether any sampling actually ran.
        n_attempted = 0
        failures: list[str] = []
        sampled_vectors: list[np.ndarray] = []

        if prober is not None and self._probes:
            self._log_sampling_preamble(prober, agent_endpoint, len(self._probes))
            for idx, prompt in enumerate(self._probes):
                if deadline is not None and time.time() >= deadline:
                    elapsed = time.time() - sampled_at
                    logger.warning(
                        "RefusalSampler: total budget %.1fs exhausted after "
                        "%d/%d probes (%d succeeded). Proceeding with the "
                        "centroid built so far.",
                        timeout_seconds, idx, len(self._probes),
                        len(sampled_vectors),
                    )
                    failures.append(
                        f"timeout: budget {timeout_seconds:.1f}s exhausted "
                        f"after {idx} probes (elapsed={elapsed:.1f}s)"
                    )
                    break
                n_attempted += 1
                session_id = f"{session_prefix}::{idx}::{int(sampled_at)}"
                try:
                    record = prober.inject_turn(session_id, prompt)
                    response_text = record.response
                except Exception as exc:  # pragma: no cover — defensive
                    failures.append(f"probe {idx}: {type(exc).__name__}: {exc}")
                    logger.warning(
                        "RefusalSampler: probe %d/%d failed (%s); continuing.",
                        idx + 1, len(self._probes), type(exc).__name__,
                    )
                    continue
                if not response_text:
                    failures.append(f"probe {idx}: empty response")
                    logger.warning(
                        "RefusalSampler: probe %d/%d returned empty response.",
                        idx + 1, len(self._probes),
                    )
                    continue
                try:
                    vec = np.asarray(self._embedder(response_text), dtype=np.float32)
                except Exception as exc:  # pragma: no cover — defensive
                    failures.append(f"probe {idx} embed: {type(exc).__name__}: {exc}")
                    logger.warning(
                        "RefusalSampler: probe %d/%d embed failed (%s).",
                        idx + 1, len(self._probes), type(exc).__name__,
                    )
                    continue
                sampled_vectors.append(vec)
                logger.info(
                    "RefusalSampler: probe %d/%d ok (response %d chars).",
                    idx + 1, len(self._probes), len(response_text),
                )

        if sampled_vectors:
            centroid = _normalize(np.mean(np.stack(sampled_vectors), axis=0))
            baseline = TrainedRefusalBaseline(
                centroid=centroid,
                n_probes=len(sampled_vectors),
                sampled_at=sampled_at,
                source="sampled",
            )
            receipt = CalibrationReceipt(
                sampled_at=sampled_at,
                agent_endpoint=agent_endpoint,
                n_attempted=n_attempted,
                n_probes=len(sampled_vectors),
                centroid_dim=int(centroid.shape[0]),
                embedding_model=self._embedding_model_name,
                corpus_sha=self._probes_sha,
                source="sampled",
                failures=failures,
            )
            logger.info(
                "RefusalSampler: sampled %d/%d refusal responses from %s "
                "(centroid dim=%d, failures=%d)",
                len(sampled_vectors), n_attempted, agent_endpoint,
                centroid.shape[0], len(failures),
            )
            return baseline, receipt

        # Fallback: corpus-only centroid.
        if self._fallback:
            corpus_vecs: list[np.ndarray] = []
            for phrase in self._fallback:
                try:
                    corpus_vecs.append(
                        np.asarray(self._embedder(phrase), dtype=np.float32)
                    )
                except Exception:  # pragma: no cover — defensive
                    continue
            if corpus_vecs:
                centroid = _normalize(np.mean(np.stack(corpus_vecs), axis=0))
                baseline = TrainedRefusalBaseline(
                    centroid=centroid,
                    n_probes=0,
                    sampled_at=sampled_at,
                    source="corpus",
                )
                receipt = CalibrationReceipt(
                    sampled_at=sampled_at,
                    agent_endpoint=agent_endpoint,
                    n_attempted=n_attempted,
                    n_probes=0,
                    centroid_dim=int(centroid.shape[0]),
                    embedding_model=self._embedding_model_name,
                    corpus_sha=self._probes_sha,
                    source="corpus",
                    failures=failures,
                )
                logger.warning(
                    "RefusalSampler: live sampling unavailable for %s "
                    "(failures=%d). Falling back to bundled refusal corpus "
                    "centroid (%d phrases).",
                    agent_endpoint, len(failures), len(corpus_vecs),
                )
                return baseline, receipt

        # No prober AND no usable fallback corpus.
        baseline = TrainedRefusalBaseline()
        receipt = CalibrationReceipt(
            sampled_at=sampled_at,
            agent_endpoint=agent_endpoint,
            n_attempted=n_attempted,
            n_probes=0,
            centroid_dim=0,
            embedding_model=self._embedding_model_name,
            corpus_sha=self._probes_sha,
            source="unset",
            failures=failures,
        )
        logger.warning(
            "RefusalSampler: no probes and no corpus fallback available; "
            "trained refusal baseline is unset."
        )
        return baseline, receipt


def _normalize(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    if n == 0.0:
        return v
    return v / n


def _backend_induction_timeout(prober: Prober) -> float | None:
    """Best-effort lookup of the backend's per-induction-request
    timeout. Used by :meth:`RefusalSampler._log_sampling_preamble`
    to estimate worst-case sampling duration. Returns ``None`` when
    the backend doesn't expose a timeout (e.g. InProcessInjector).
    """
    backend = getattr(prober, "_backend", None)
    if backend is None:
        return None
    timeout = getattr(backend, "induction_timeout", None)
    if isinstance(timeout, (int, float)) and timeout > 0:
        return float(timeout)
    return None
