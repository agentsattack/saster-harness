"""Tests for the boot-time RefusalSampler.

Covers:

- Successful sampling builds a centroid and a sampled receipt.
- Empty / failing prober falls back to the bundled refusal corpus.
- No prober + no corpus → unset baseline + honest receipt.
- TrainedRefusalBaseline.is_available reflects the centroid state.
"""

from __future__ import annotations

import numpy as np

from saster_harness.baseline import TrainedRefusalBaseline
from saster_harness.prober import InProcessInjector, Prober
from saster_harness.refusal_sampler import RefusalSampler


def _fake_embedder(text: str) -> np.ndarray:
    rng = np.random.default_rng(abs(hash(text)) % (2**32))
    v = rng.standard_normal(8).astype(np.float32)
    n = float(np.linalg.norm(v))
    return (v / n).astype(np.float32) if n > 0 else v


def _always_refuse(session_id: str, content: str) -> str:
    """Deterministic stand-in agent that always returns a refusal."""
    del session_id, content
    return "I cannot help with that request — it falls outside my permitted scope."


def _always_raises(session_id: str, content: str) -> str:
    del session_id, content
    raise ConnectionError("agent unreachable")


def test_sampler_builds_centroid_from_live_agent_responses() -> None:
    prober = Prober(backend=InProcessInjector(send_fn=_always_refuse))
    sampler = RefusalSampler(
        embedder=_fake_embedder,
        embedding_model_name="all-MiniLM-L6-v2",
        probes=["test probe 1", "test probe 2", "test probe 3"],
        fallback_corpus=["I refuse.", "Not permitted."],
    )
    baseline, receipt = sampler.sample(
        prober=prober, agent_endpoint="http://test/",
    )
    assert baseline.is_available()
    assert baseline.source == "sampled"
    assert baseline.n_probes == 3
    assert baseline.centroid is not None
    assert baseline.centroid.shape == (8,)
    # L2-normalized
    assert abs(float(np.linalg.norm(baseline.centroid)) - 1.0) < 1e-5
    # Receipt mirrors reality
    assert receipt.source == "sampled"
    assert receipt.n_attempted == 3
    assert receipt.n_probes == 3
    assert receipt.centroid_dim == 8
    assert receipt.failures == []


def test_sampler_falls_back_to_corpus_when_agent_unreachable() -> None:
    prober = Prober(backend=InProcessInjector(send_fn=_always_raises))
    sampler = RefusalSampler(
        embedder=_fake_embedder,
        embedding_model_name="all-MiniLM-L6-v2",
        probes=["test probe 1", "test probe 2"],
        fallback_corpus=["I refuse.", "I cannot.", "Not allowed."],
    )
    baseline, receipt = sampler.sample(
        prober=prober, agent_endpoint="http://test/",
    )
    assert baseline.is_available()
    assert baseline.source == "corpus"
    assert baseline.n_probes == 0  # zero LIVE probes
    assert receipt.source == "corpus"
    assert receipt.n_attempted == 2
    assert receipt.n_probes == 0
    assert len(receipt.failures) == 2


def test_sampler_falls_back_when_prober_is_none() -> None:
    sampler = RefusalSampler(
        embedder=_fake_embedder,
        probes=["p1", "p2"],
        fallback_corpus=["I refuse.", "Not allowed."],
    )
    baseline, receipt = sampler.sample(
        prober=None, agent_endpoint="http://test/",
    )
    assert baseline.source == "corpus"
    assert receipt.source == "corpus"
    # v0.3 fix #5: ``n_attempted`` is the count of LIVE probe attempts,
    # not the size of the configured probe list. With no prober there
    # are zero live attempts.
    assert receipt.n_attempted == 0


def test_n_attempted_is_zero_when_sampling_disabled(caplog) -> None:
    """The receipt must not pretend a probe ran when none did."""
    sampler = RefusalSampler(
        embedder=_fake_embedder,
        probes=["p1", "p2", "p3"],
        fallback_corpus=["I refuse."],
    )
    _, receipt = sampler.sample(prober=None, agent_endpoint="http://test/")
    assert receipt.n_attempted == 0
    assert receipt.n_probes == 0
    assert receipt.source == "corpus"


def test_sampler_logs_progress_per_probe(caplog) -> None:
    """v0.3 fix #2/#6: the sampler must log per-probe progress so the
    operator can see the slow boot rather than waiting in silence."""
    import logging

    prober = Prober(backend=InProcessInjector(send_fn=_always_refuse))
    sampler = RefusalSampler(
        embedder=_fake_embedder,
        probes=["p1", "p2", "p3"],
        fallback_corpus=["I refuse."],
    )
    with caplog.at_level(logging.INFO, logger="saster_harness.refusal_sampler"):
        sampler.sample(prober=prober, agent_endpoint="http://test/")
    progress_lines = [
        r.message for r in caplog.records
        if "probe " in r.message and "/3 ok" in r.message
    ]
    assert len(progress_lines) == 3, (
        f"expected 3 per-probe progress lines, got {progress_lines!r}"
    )


def test_sampler_breaks_loop_when_total_timeout_exhausted(caplog) -> None:
    """v0.3 fix: sampling_timeout_seconds caps total time spent in
    sample(), regardless of per-probe induction_timeout. Honors the
    deadline; ships whichever probes completed."""
    import logging
    import time as time_module

    def _slow_refuse(_sid: str, _content: str) -> str:
        time_module.sleep(0.05)
        return "I cannot help with that."

    prober = Prober(backend=InProcessInjector(send_fn=_slow_refuse))
    sampler = RefusalSampler(
        embedder=_fake_embedder,
        probes=[f"probe {i}" for i in range(20)],
        fallback_corpus=["I refuse."],
    )
    t0 = time_module.perf_counter()
    with caplog.at_level(logging.WARNING, logger="saster_harness.refusal_sampler"):
        baseline, receipt = sampler.sample(
            prober=prober,
            agent_endpoint="http://test/",
            timeout_seconds=0.1,
        )
    elapsed = time_module.perf_counter() - t0
    # Honors the 100ms deadline with reasonable slack — must not run
    # all 20 probes × 50ms = 1s.
    assert elapsed < 0.5, f"sampler did not honor timeout, took {elapsed:.2f}s"
    # Either we got a sampled centroid from whichever probes completed,
    # or we fell back to the corpus when zero probes completed in time.
    assert baseline.source in ("sampled", "corpus")
    # The warning naming the budget exhaustion should have fired.
    assert any(
        "budget" in r.message and "exhausted" in r.message
        for r in caplog.records
    )


def test_sampler_disabled_timeout_runs_full_corpus() -> None:
    """timeout_seconds=0 (default) preserves v0.3.0-dev behavior:
    no cap, run every configured probe."""
    prober = Prober(backend=InProcessInjector(send_fn=_always_refuse))
    sampler = RefusalSampler(
        embedder=_fake_embedder,
        probes=["a", "b", "c", "d", "e"],
        fallback_corpus=["I refuse."],
    )
    baseline, receipt = sampler.sample(
        prober=prober,
        agent_endpoint="http://test/",
        timeout_seconds=0.0,
    )
    assert receipt.source == "sampled"
    assert receipt.n_attempted == 5
    assert receipt.n_probes == 5


def test_sampler_logs_preamble_with_duration_estimate(caplog) -> None:
    """When the backend exposes induction_timeout (HttpInjector does),
    the preamble line includes the worst-case duration estimate."""
    import logging

    class _TimeoutBackend:
        induction_timeout = 60.0

        def send(self, session_id: str, content: str) -> str:
            return "I cannot help with that."

    prober = Prober(backend=_TimeoutBackend())  # type: ignore[arg-type]
    sampler = RefusalSampler(
        embedder=_fake_embedder,
        probes=["p1", "p2"],
        fallback_corpus=["I refuse."],
    )
    with caplog.at_level(logging.INFO, logger="saster_harness.refusal_sampler"):
        sampler.sample(prober=prober, agent_endpoint="http://test/")
    preamble = [
        r.message for r in caplog.records
        if "blocks start()" in r.message
    ]
    assert preamble, "expected preamble line"
    # 2 probes × 60 s = 120 s worst case
    assert "120" in preamble[0]


def test_sampler_returns_unset_baseline_when_no_corpus_and_no_prober() -> None:
    sampler = RefusalSampler(
        embedder=_fake_embedder,
        probes=["p1"],
        fallback_corpus=[],
    )
    baseline, receipt = sampler.sample(
        prober=None, agent_endpoint="http://test/",
    )
    assert not baseline.is_available()
    assert baseline.source == "unset"
    assert receipt.source == "unset"


def test_receipt_to_dict_is_json_serialisable() -> None:
    import json
    sampler = RefusalSampler(
        embedder=_fake_embedder,
        probes=["p1"],
        fallback_corpus=["I refuse."],
    )
    _, receipt = sampler.sample(prober=None, agent_endpoint="http://test/")
    payload = json.dumps(receipt.to_dict())
    assert "source" in payload
    assert "corpus_sha" in payload


def test_trained_baseline_is_available_only_when_centroid_present() -> None:
    empty = TrainedRefusalBaseline()
    assert not empty.is_available()

    populated = TrainedRefusalBaseline(
        centroid=np.zeros(8, dtype=np.float32),
        n_probes=5,
        sampled_at=1234.0,
        source="sampled",
    )
    assert populated.is_available()
