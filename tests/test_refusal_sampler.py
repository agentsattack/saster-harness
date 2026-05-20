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
