"""Tests for the v0.3.2 extra_reframings / extra_turn_sequences config.

Coverage:
- Config dict pushed into matching SingleTurnInductionDetector via add_reframings.
- Config dict pushed into matching MultiTurnInductionDetector via add_turn_sequences.
- _full_strategy concatenates built-in + extras in order.
- Unknown detector id in extras logs WARNING but doesn't raise.
- Wrong shape (multi-turn ramps under a single-turn id) logs WARNING.
- Config validation rejects malformed shapes.
"""

from __future__ import annotations

import logging

import numpy as np
import pytest

from saster_harness import (
    MonitoringConfig,
    MonitoringHarness,
    Saster18InducedDetector,
    Saster18MultiTurnDetector,
    register_detector_instance,
)
from saster_harness.detectors.base_induction import SingleTurnInductionDetector
from saster_harness.event import DetectionEvent, TurnData
from saster_harness.harness import _DETECTOR_INSTANCE_REGISTRY, _DETECTOR_REGISTRY
from saster_harness.prober import InProcessInjector, Prober


# ---------------------------------------------------------------------------
# Registry isolation
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_registry() -> None:
    snapshot_path = dict(_DETECTOR_REGISTRY)
    snapshot_instance = dict(_DETECTOR_INSTANCE_REGISTRY)
    yield
    _DETECTOR_REGISTRY.clear()
    _DETECTOR_REGISTRY.update(snapshot_path)
    _DETECTOR_INSTANCE_REGISTRY.clear()
    _DETECTOR_INSTANCE_REGISTRY.update(snapshot_instance)


# ---------------------------------------------------------------------------
# Stub embedder so detectors don't pull sentence-transformers
# ---------------------------------------------------------------------------

_REFUSAL_VECTOR = np.array([1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], dtype=np.float32)


def _stub_embed(text: str) -> np.ndarray:
    return _REFUSAL_VECTOR.copy()


# ---------------------------------------------------------------------------
# add_reframings (single-turn detector)
# ---------------------------------------------------------------------------


def test_add_reframings_appends_to_built_in_strategy() -> None:
    det = Saster18InducedDetector(
        threshold=0.6,
        refusal_centroid=_REFUSAL_VECTOR.copy(),
        embedder=_stub_embed,
    )
    built_in = tuple(det.induction_strategy())
    det.add_reframings(["custom prompt one", "custom prompt two"])
    full = det._full_strategy()
    assert full[: len(built_in)] == built_in
    assert full[len(built_in):] == ("custom prompt one", "custom prompt two")


def test_add_reframings_rejects_empty_string() -> None:
    det = Saster18InducedDetector(
        threshold=0.6, refusal_centroid=_REFUSAL_VECTOR.copy(), embedder=_stub_embed,
    )
    with pytest.raises(ValueError, match="non-empty"):
        det.add_reframings(["", "valid"])


def test_added_reframings_actually_get_sent_to_prober() -> None:
    """End-to-end: an extra reframing reaches the prober and contributes
    to the divergence loop."""
    call_log: list[str] = []

    def stub(session_id: str, content: str) -> str:
        call_log.append(content)
        return "I can't help with that."

    det = Saster18InducedDetector(
        threshold=0.6, refusal_centroid=_REFUSAL_VECTOR.copy(), embedder=_stub_embed,
    )
    built_in_count = len(tuple(det.induction_strategy()))
    det.add_reframings(["EXTRA-PROMPT-MARKER-XYZ"])

    prober = Prober(InProcessInjector(stub))
    det.induce(prober, "test-session")

    # Baseline + every reframing (built-in + extra) should be sent.
    assert "EXTRA-PROMPT-MARKER-XYZ" in call_log
    # 1 baseline + N built-in + 1 extra = built_in_count + 2 calls.
    assert len(call_log) == built_in_count + 2


# ---------------------------------------------------------------------------
# Harness distribution: extra_reframings
# ---------------------------------------------------------------------------


def test_harness_pushes_extra_reframings_into_matching_detector() -> None:
    """The harness reads MonitoringConfig.extra_reframings and calls
    add_reframings on detectors whose saster_id matches."""
    # Use a pre-built detector via the instance registry so the test
    # avoids the sentence-transformer load at construction.
    sentinel = Saster18InducedDetector(
        threshold=0.6, refusal_centroid=_REFUSAL_VECTOR.copy(), embedder=_stub_embed,
    )
    register_detector_instance("SASTER-18-induced", sentinel)

    config = MonitoringConfig(
        agent_name="test-agent",
        agent_endpoint="http://localhost:9999/chat",
        authorized_tools=["any"],
        enabled_detectors=["SASTER-18-induced"],
        extra_reframings={
            "SASTER-18-induced": ["HARNESS-PUSHED-1", "HARNESS-PUSHED-2"],
        },
        sample_refusal_baseline=False,
    )
    MonitoringHarness(config)

    full = sentinel._full_strategy()
    assert "HARNESS-PUSHED-1" in full
    assert "HARNESS-PUSHED-2" in full


def test_harness_warns_on_unknown_detector_id_in_extras(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A stale entry shouldn't break startup — just log a WARNING."""
    sentinel = Saster18InducedDetector(
        threshold=0.6, refusal_centroid=_REFUSAL_VECTOR.copy(), embedder=_stub_embed,
    )
    register_detector_instance("SASTER-18-induced", sentinel)

    config = MonitoringConfig(
        agent_name="test-agent",
        agent_endpoint="http://localhost:9999/chat",
        authorized_tools=["any"],
        enabled_detectors=["SASTER-18-induced"],
        extra_reframings={"NOT-LOADED": ["x"]},
        sample_refusal_baseline=False,
    )
    with caplog.at_level(logging.WARNING):
        MonitoringHarness(config)
    assert any("NOT-LOADED" in rec.message for rec in caplog.records)


def test_harness_warns_when_pushing_reframings_to_non_single_turn_detector(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Putting prompts under a multi-turn detector's id should log
    WARNING (use extra_turn_sequences instead) and not raise."""
    sentinel = Saster18MultiTurnDetector(
        threshold=0.6, refusal_centroid=_REFUSAL_VECTOR.copy(), embedder=_stub_embed,
        sequences=[("a",)],
    )
    register_detector_instance("SASTER-18-multiturn", sentinel)

    config = MonitoringConfig(
        agent_name="test-agent",
        agent_endpoint="http://localhost:9999/chat",
        authorized_tools=["any"],
        enabled_detectors=["SASTER-18-multiturn"],
        extra_reframings={"SASTER-18-multiturn": ["mis-routed"]},
        sample_refusal_baseline=False,
    )
    with caplog.at_level(logging.WARNING):
        MonitoringHarness(config)
    assert any(
        "not a single-turn" in rec.message for rec in caplog.records
    )


# ---------------------------------------------------------------------------
# Harness distribution: extra_turn_sequences
# ---------------------------------------------------------------------------


def test_harness_pushes_extra_turn_sequences_into_multiturn_detector() -> None:
    sentinel = Saster18MultiTurnDetector(
        threshold=0.6, refusal_centroid=_REFUSAL_VECTOR.copy(), embedder=_stub_embed,
        sequences=[("built-in-only",)],
    )
    register_detector_instance("SASTER-18-multiturn", sentinel)

    config = MonitoringConfig(
        agent_name="test-agent",
        agent_endpoint="http://localhost:9999/chat",
        authorized_tools=["any"],
        enabled_detectors=["SASTER-18-multiturn"],
        extra_turn_sequences={
            "SASTER-18-multiturn": [
                ("custom-warm", "custom-final"),
            ],
        },
        sample_refusal_baseline=False,
    )
    MonitoringHarness(config)

    full = sentinel._full_sequences()
    assert len(full) == 2
    assert full[1] == ("custom-warm", "custom-final")


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------


def test_config_rejects_non_dict_extra_reframings() -> None:
    with pytest.raises(TypeError, match="extra_reframings"):
        MonitoringConfig(
            agent_name="x",
            agent_endpoint="http://x/chat",
            authorized_tools=["t"],
            extra_reframings=["not", "a", "dict"],  # type: ignore[arg-type]
        )


def test_config_rejects_non_string_extra_reframing_prompt() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        MonitoringConfig(
            agent_name="x",
            agent_endpoint="http://x/chat",
            authorized_tools=["t"],
            extra_reframings={"SASTER-18-induced": ["", "valid"]},
        )


def test_config_rejects_empty_extra_turn_sequence_ramp() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        MonitoringConfig(
            agent_name="x",
            agent_endpoint="http://x/chat",
            authorized_tools=["t"],
            extra_turn_sequences={"SASTER-18-multiturn": [()]},
        )


def test_config_rejects_non_string_extra_turn_sequence_entry() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        MonitoringConfig(
            agent_name="x",
            agent_endpoint="http://x/chat",
            authorized_tools=["t"],
            extra_turn_sequences={"SASTER-18-multiturn": [("ok", "")]},
        )
