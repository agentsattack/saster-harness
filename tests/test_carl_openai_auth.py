"""Tests for Carl's authenticated upstream support.

Carl ships as an HTTP shim that forwards OpenAI-shape chat completions
to a configurable upstream. v0.3.2 makes that upstream reachable when
authentication is required — OpenAI, OpenRouter, LiteLLM proxy,
authenticated self-hosted vLLM. These tests verify:

- ``CarlConfig.upstream_headers`` emits the expected Bearer header.
- ``CARL_LLM_API_KEY`` env var routes through ``from_env``.
- ``OPENAI_API_KEY`` is picked up only when the endpoint is
  ``api.openai.com`` (no leaking the OpenAI key to unrelated hosts).
- ``CARL_LLM_API_KEY`` wins when both env vars are set.
- ``CARL_LLM_EXTRA_HEADERS`` JSON env var parses and merges.
- The HTTP handler actually sends ``Authorization`` to the upstream
  request when the config carries an api_key.
- ``serve_in_thread(api_key=...)`` forwards the key into the config.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any

import httpx
import pytest

from carl.server import (
    CarlConfig,
    _parse_extra_headers_env,
    _resolve_api_key_from_env,
    build_server,
    serve_in_thread,
)


# ---------------------------------------------------------------------------
# CarlConfig.upstream_headers
# ---------------------------------------------------------------------------


def test_upstream_headers_emits_bearer_when_api_key_set() -> None:
    config = CarlConfig(api_key="sk-test-123")
    headers = config.upstream_headers()
    assert headers["Authorization"] == "Bearer sk-test-123"
    assert headers["Content-Type"] == "application/json"


def test_upstream_headers_omits_authorization_when_api_key_none() -> None:
    config = CarlConfig(api_key=None)
    headers = config.upstream_headers()
    assert "Authorization" not in headers


def test_upstream_headers_merges_extra_headers() -> None:
    config = CarlConfig(
        api_key="sk-test",
        extra_headers={"OpenAI-Organization": "org-abc", "OpenAI-Project": "proj-xyz"},
    )
    headers = config.upstream_headers()
    assert headers["Authorization"] == "Bearer sk-test"
    assert headers["OpenAI-Organization"] == "org-abc"
    assert headers["OpenAI-Project"] == "proj-xyz"


def test_upstream_headers_returns_fresh_dict() -> None:
    """Mutating the returned dict must not leak into the next call —
    handler thread safety relies on this."""
    config = CarlConfig(api_key="sk-test")
    first = config.upstream_headers()
    first["X-Mutated"] = "leak"
    second = config.upstream_headers()
    assert "X-Mutated" not in second


# ---------------------------------------------------------------------------
# Env-var resolution
# ---------------------------------------------------------------------------


def test_carl_llm_api_key_env_takes_precedence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CARL_LLM_API_KEY", "sk-carl")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    key = _resolve_api_key_from_env("https://api.openai.com/v1/chat/completions")
    assert key == "sk-carl"


def test_openai_api_key_env_fallback_when_endpoint_is_openai(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CARL_LLM_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-fallback")
    key = _resolve_api_key_from_env("https://api.openai.com/v1/chat/completions")
    assert key == "sk-openai-fallback"


def test_openai_api_key_NOT_used_for_non_openai_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Critical security property: never leak OPENAI_API_KEY to an
    unrelated host. A user's self-hosted vLLM at 192.168.0.143 must
    not receive their OpenAI key."""
    monkeypatch.delenv("CARL_LLM_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-must-not-leak")
    key = _resolve_api_key_from_env("http://192.168.0.143:8000/v1/chat/completions")
    assert key is None


def test_no_env_vars_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CARL_LLM_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert _resolve_api_key_from_env("https://api.openai.com/v1/chat/completions") is None
    assert _resolve_api_key_from_env("http://localhost/chat") is None


# ---------------------------------------------------------------------------
# CARL_LLM_EXTRA_HEADERS parsing
# ---------------------------------------------------------------------------


def test_extra_headers_parses_json_object() -> None:
    parsed = _parse_extra_headers_env(
        '{"OpenAI-Organization": "org-1", "OpenAI-Project": "proj-2"}'
    )
    assert parsed == {"OpenAI-Organization": "org-1", "OpenAI-Project": "proj-2"}


def test_extra_headers_empty_string_returns_empty_dict() -> None:
    assert _parse_extra_headers_env("") == {}
    assert _parse_extra_headers_env("   ") == {}


def test_extra_headers_invalid_json_returns_empty_dict_with_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging
    with caplog.at_level(logging.WARNING):
        result = _parse_extra_headers_env("not json")
    assert result == {}
    assert any("not valid JSON" in rec.message for rec in caplog.records)


def test_extra_headers_non_object_returns_empty_dict_with_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging
    with caplog.at_level(logging.WARNING):
        result = _parse_extra_headers_env('["not", "an", "object"]')
    assert result == {}
    assert any("must be a JSON object" in rec.message for rec in caplog.records)


def test_extra_headers_drops_non_string_values() -> None:
    parsed = _parse_extra_headers_env(
        '{"good": "value", "bad": 42, "": "empty-name", "another": "ok"}'
    )
    assert parsed == {"good": "value", "another": "ok"}


# ---------------------------------------------------------------------------
# CarlConfig.from_env integration
# ---------------------------------------------------------------------------


def test_from_env_picks_up_carl_llm_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CARL_LLM_API_KEY", "sk-from-env")
    monkeypatch.setenv(
        "CARL_LLM_ENDPOINT", "http://192.168.0.143:8000/v1/chat/completions",
    )
    config = CarlConfig.from_env()
    assert config.api_key == "sk-from-env"


def test_from_env_picks_up_openai_key_when_endpoint_is_openai(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CARL_LLM_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-env")
    monkeypatch.setenv(
        "CARL_LLM_ENDPOINT", "https://api.openai.com/v1/chat/completions",
    )
    config = CarlConfig.from_env()
    assert config.api_key == "sk-openai-env"


def test_from_env_parses_extra_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "CARL_LLM_EXTRA_HEADERS",
        '{"OpenAI-Organization": "org-abc"}',
    )
    config = CarlConfig.from_env()
    assert config.extra_headers == {"OpenAI-Organization": "org-abc"}


# ---------------------------------------------------------------------------
# End-to-end: handler sends the Bearer header to the upstream
# ---------------------------------------------------------------------------


def _start_server_capturing_upstream_headers(
    api_key: str | None,
    extra_headers: dict[str, str] | None = None,
    endpoint: str = "http://mock.upstream/chat",
) -> tuple[Any, int, list[httpx.Headers]]:
    captured_headers: list[httpx.Headers] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        captured_headers.append(request.headers)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": "ok"}}]},
        )

    server = build_server(
        config=CarlConfig(
            directive="",
            llm_endpoint=endpoint,
            api_key=api_key,
            extra_headers=extra_headers,
        ),
        host="127.0.0.1",
        port=0,
    )
    state = server._carl_state  # type: ignore[attr-defined]
    state.client.close()
    state.client = httpx.Client(transport=httpx.MockTransport(upstream))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1], captured_headers


def _wait_until_ready(port: int, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            response = httpx.get(f"http://127.0.0.1:{port}/health", timeout=0.5)
            if response.status_code == 200:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(0.05)
    return False


def test_handler_sends_bearer_authorization_to_upstream() -> None:
    """End-to-end: POST /chat → handler forwards to upstream with the
    Authorization header set."""
    server, port, captured = _start_server_capturing_upstream_headers(
        api_key="sk-end-to-end",
    )
    try:
        assert _wait_until_ready(port)
        response = httpx.post(
            f"http://127.0.0.1:{port}/chat",
            json={"messages": [{"role": "user", "content": "hello"}]},
            headers={"X-Session-Id": "auth-test"},
        )
        assert response.status_code == 200
        assert len(captured) == 1
        assert captured[0].get("Authorization") == "Bearer sk-end-to-end"
    finally:
        server.shutdown()
        server.server_close()


def test_handler_omits_authorization_when_no_api_key() -> None:
    server, port, captured = _start_server_capturing_upstream_headers(api_key=None)
    try:
        assert _wait_until_ready(port)
        httpx.post(
            f"http://127.0.0.1:{port}/chat",
            json={"messages": [{"role": "user", "content": "hello"}]},
        )
        assert len(captured) == 1
        assert "Authorization" not in captured[0]
    finally:
        server.shutdown()
        server.server_close()


def test_handler_sends_extra_headers_to_upstream() -> None:
    server, port, captured = _start_server_capturing_upstream_headers(
        api_key="sk-x",
        extra_headers={
            "OpenAI-Organization": "org-test",
            "OpenAI-Project": "proj-test",
        },
    )
    try:
        assert _wait_until_ready(port)
        httpx.post(
            f"http://127.0.0.1:{port}/chat",
            json={"messages": [{"role": "user", "content": "hello"}]},
        )
        assert len(captured) == 1
        assert captured[0].get("OpenAI-Organization") == "org-test"
        assert captured[0].get("OpenAI-Project") == "proj-test"
    finally:
        server.shutdown()
        server.server_close()


def test_serve_in_thread_accepts_api_key_argument() -> None:
    """The convenience launcher must thread api_key through to the
    config so phase4_calibration.py and other callers can configure
    auth without setting env vars."""
    # Use port 0 so the OS picks; use a localhost endpoint so the
    # OPENAI_API_KEY env-fallback path is NOT triggered.
    server = serve_in_thread(
        directive="",
        host="127.0.0.1",
        port=0,
        llm_endpoint="http://127.0.0.1:1/never-called",
        api_key="sk-from-arg",
    )
    try:
        state = server._carl_state  # type: ignore[attr-defined]
        assert state.config.api_key == "sk-from-arg"
        assert state.config.upstream_headers()["Authorization"] == "Bearer sk-from-arg"
    finally:
        server.shutdown()
        server.server_close()


def test_serve_in_thread_falls_back_to_openai_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When api_key is unset and endpoint is api.openai.com, the env
    var should be picked up."""
    monkeypatch.delenv("CARL_LLM_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env-fallback")
    server = serve_in_thread(
        directive="",
        host="127.0.0.1",
        port=0,
        llm_endpoint="https://api.openai.com/v1/chat/completions",
    )
    try:
        state = server._carl_state  # type: ignore[attr-defined]
        assert state.config.api_key == "sk-env-fallback"
    finally:
        server.shutdown()
        server.server_close()
