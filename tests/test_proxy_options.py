"""Tests for the v0.3.2 mitmproxy option fields.

Coverage:
- Config validation: listen_host non-empty, upstream_proxy scheme.
- Default values preserve v0.3.1 behavior (loopback bind, TLS-insecure).
- mitm_options collision with managed keys raises at start time.
- _run_proxy passes the configured values to Options(...).

These tests stub out the mitmproxy DumpMaster — exercising the real
event loop in a unit test would block and bind a port. The mitmproxy
Options class is a thin dataclass-like surface; verifying we pass it
the right kwargs is sufficient.
"""

from __future__ import annotations

import sys
import threading
from unittest.mock import MagicMock, patch

import pytest

from saster_harness import MonitoringConfig, MonitoringHarness
from saster_harness.proxy import HarnessAddon


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------


def _base_config(**overrides):  # type: ignore[no-untyped-def]
    base = dict(
        agent_name="test-agent",
        agent_endpoint="http://localhost:9999/chat",
        authorized_tools=["t"],
        sample_refusal_baseline=False,
    )
    base.update(overrides)
    return MonitoringConfig(**base)


def test_default_listen_host_is_loopback() -> None:
    config = _base_config()
    assert config.listen_host == "127.0.0.1"


def test_default_ssl_insecure_is_true() -> None:
    config = _base_config()
    assert config.ssl_insecure is True


def test_default_upstream_proxy_is_none() -> None:
    config = _base_config()
    assert config.upstream_proxy is None


def test_default_mitm_options_is_empty_dict() -> None:
    config = _base_config()
    assert config.mitm_options == {}


def test_listen_host_empty_string_rejected() -> None:
    with pytest.raises(ValueError, match="listen_host"):
        _base_config(listen_host="")


def test_listen_host_whitespace_only_rejected() -> None:
    with pytest.raises(ValueError, match="listen_host"):
        _base_config(listen_host="   ")


def test_upstream_proxy_requires_scheme() -> None:
    with pytest.raises(ValueError, match="upstream_proxy"):
        _base_config(upstream_proxy="localhost:3128")


def test_upstream_proxy_accepts_http_url() -> None:
    config = _base_config(upstream_proxy="http://proxy.corp:3128")
    assert config.upstream_proxy == "http://proxy.corp:3128"


def test_upstream_proxy_accepts_https_url() -> None:
    config = _base_config(upstream_proxy="https://proxy.corp:3128")
    assert config.upstream_proxy == "https://proxy.corp:3128"


def test_upstream_proxy_rejects_ftp_scheme() -> None:
    with pytest.raises(ValueError, match="upstream_proxy"):
        _base_config(upstream_proxy="ftp://proxy.corp")


def test_mitm_options_must_be_dict() -> None:
    with pytest.raises(TypeError, match="mitm_options"):
        _base_config(mitm_options=["not", "a", "dict"])


def test_listen_host_non_loopback_accepted() -> None:
    """Setting listen_host=0.0.0.0 is accepted at config time (harness
    logs a WARNING at start time, not a validation error)."""
    config = _base_config(listen_host="0.0.0.0")
    assert config.listen_host == "0.0.0.0"


# ---------------------------------------------------------------------------
# _run_proxy — Options construction
# ---------------------------------------------------------------------------


def _run_proxy_and_capture_options(config: MonitoringConfig) -> dict:
    """Helper: invoke _run_proxy with mocked mitmproxy stack and return
    the kwargs that were passed to Options()."""
    captured: dict = {}

    fake_options_module = type(sys)("mitmproxy.options")

    class _FakeOptions:
        def __init__(self, **kwargs):  # type: ignore[no-untyped-def]
            captured.update(kwargs)

    fake_options_module.Options = _FakeOptions

    fake_dump_module = type(sys)("mitmproxy.tools.dump")

    class _FakeDumpMaster:
        def __init__(self, opts, *, with_termlog: bool, with_dumper: bool):  # type: ignore[no-untyped-def]
            self.opts = opts
            self.addons = MagicMock()

        async def run(self) -> None:
            return

        def shutdown(self) -> None:
            return

    fake_dump_module.DumpMaster = _FakeDumpMaster

    with patch.dict(sys.modules, {
        "mitmproxy.options": fake_options_module,
        "mitmproxy.tools.dump": fake_dump_module,
    }):
        harness = MonitoringHarness(config)
        # Trigger _run_proxy directly — it builds Options + DumpMaster and
        # runs the asyncio loop until shutdown. The stop_event is set
        # immediately so the loop exits without blocking.
        harness._stop_event.set()
        addon = HarnessAddon(
            adapter=harness._adapter,
            detectors=harness._detectors,
            baseline=harness._baseline,
            sink=harness._handle_event,
            agent_name=config.agent_name,
        )
        harness._run_proxy(addon)
    return captured


def test_default_options_match_v031_behavior() -> None:
    config = _base_config()
    captured = _run_proxy_and_capture_options(config)
    assert captured["listen_host"] == "127.0.0.1"
    assert captured["listen_port"] == 8888
    assert captured["ssl_insecure"] is True
    assert "mode" not in captured  # no upstream proxy by default


def test_listen_host_override_propagates() -> None:
    config = _base_config(listen_host="0.0.0.0", listen_port=9000)
    captured = _run_proxy_and_capture_options(config)
    assert captured["listen_host"] == "0.0.0.0"
    assert captured["listen_port"] == 9000


def test_ssl_insecure_false_propagates() -> None:
    config = _base_config(ssl_insecure=False)
    captured = _run_proxy_and_capture_options(config)
    assert captured["ssl_insecure"] is False


def test_upstream_proxy_propagates_as_upstream_mode() -> None:
    config = _base_config(upstream_proxy="http://corp-proxy:3128")
    captured = _run_proxy_and_capture_options(config)
    # mitmproxy's mode field takes a tuple of mode strings.
    assert captured["mode"] == ("upstream:http://corp-proxy:3128",)


def test_mitm_options_passes_through_to_options_constructor() -> None:
    config = _base_config(mitm_options={"cadir": "/tmp/mitm-ca"})
    captured = _run_proxy_and_capture_options(config)
    assert captured["cadir"] == "/tmp/mitm-ca"


def test_mitm_options_collision_with_managed_key_raises() -> None:
    """Putting listen_host into mitm_options must raise at start time —
    we don't want silent override."""
    config = _base_config(mitm_options={"listen_host": "0.0.0.0"})
    with pytest.raises(ValueError, match="listen_host"):
        _run_proxy_and_capture_options(config)


def test_non_loopback_listen_host_logs_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging

    config = _base_config(listen_host="0.0.0.0")
    with caplog.at_level(logging.WARNING):
        _run_proxy_and_capture_options(config)
    assert any(
        "non-loopback" in rec.message or "0.0.0.0" in rec.message
        for rec in caplog.records
    )
