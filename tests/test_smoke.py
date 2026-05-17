"""Smoke tests — verify the package imports cleanly and the public surface
matches the LayerOne slide-18 commitment.

These tests cover the framework scaffold and public API contract.
Detector behavior is exercised in :mod:`test_detectors`; Carl-scenario
end-to-end behavior in :mod:`test_carl_scenarios`.
"""

from __future__ import annotations

import pytest

import saster_harness


def test_version_exported() -> None:
    assert saster_harness.__version__ == "0.1.0"


def test_public_api_matches_slide() -> None:
    """The slide-18 import line must keep working."""
    from saster_harness import MonitoringConfig, MonitoringHarness  # noqa: F401
    from saster_harness.adapters import HttpJsonAdapter  # noqa: F401


def test_config_validation_rejects_bad_endpoint() -> None:
    from saster_harness import MonitoringConfig

    with pytest.raises(ValueError, match="agent_endpoint"):
        MonitoringConfig(
            agent_name="x",
            agent_endpoint="ftp://nope",
            authorized_tools=[],
        )


def test_config_validation_rejects_bad_webhook() -> None:
    from saster_harness import MonitoringConfig

    with pytest.raises(ValueError, match="alert_webhook"):
        MonitoringConfig(
            agent_name="x",
            agent_endpoint="http://agent/chat",
            authorized_tools=[],
            alert_webhook="not-a-url",
        )


def test_slide_example_constructs() -> None:
    """The exact code from slide 18 must construct without raising."""
    from saster_harness import MonitoringConfig, MonitoringHarness
    from saster_harness.adapters import HttpJsonAdapter

    config = MonitoringConfig(
        agent_name="support-prod",
        agent_endpoint="http://your-agent/chat",
        authorized_tools=["search_kb", "create_ticket"],
        max_drift_score=25,
        max_autonomous_hits=2,
        probe_interval_hours=24,
        alert_webhook="https://hooks.slack.com/example",
    )
    harness = MonitoringHarness(config, adapter=HttpJsonAdapter())
    assert harness.config.agent_name == "support-prod"
    # Default detector set in v0.2.0: ten implementations spanning
    # eight SASTER patterns. SASTER-18 and SASTER-24 ship in both
    # passive and induced flavours; SASTER-15 ships induced-only
    # (no passive detector in v0.2; -both shortcut is
    # forward-compatible).
    ids = sorted(d.saster_id for d in harness.detectors)
    assert ids == [
        "SASTER-15-induced",
        "SASTER-18", "SASTER-18-induced",
        "SASTER-24", "SASTER-24-induced",
        "SASTER-26", "SASTER-27", "SASTER-28",
        "SASTER-31", "SASTER-33",
    ]


def test_detectors_declare_canonical_metadata() -> None:
    """Each shipped detector must declare a saster_id, pattern_name, tier."""
    from saster_harness import MonitoringConfig, MonitoringHarness
    from saster_harness.adapters import HttpJsonAdapter

    config = MonitoringConfig(
        agent_name="test",
        agent_endpoint="http://test/chat",
        authorized_tools=[],
    )
    harness = MonitoringHarness(config, adapter=HttpJsonAdapter())
    for d in harness.detectors:
        assert d.saster_id.startswith("SASTER-")
        assert d.pattern_name
        assert d.tier in (1, 2, 3, 4)
