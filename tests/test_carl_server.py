"""Tests for the Carl HTTP server + directives.

These are unit tests against the server's request handling and
session state. The end-to-end calibration against the real Llama
upstream lives in ``scripts/phase4_calibration.py``; the tests
here use ``httpx.MockTransport`` to fake the upstream LLM so the
suite stays fast and deterministic.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any

import httpx

from carl.directives import (
    _BASE_PERSONA,
    KNOWN_DIRECTIVES,
    get_directive_system_prompt,
)
from carl.server import (
    CarlConfig,
    SessionStore,
    _extract_assistant_content,
    _extract_user_message,
    build_server,
    serve_in_thread,
)

# ---------------------------------------------------------------------------
# SessionStore — pure data structure, fast tests
# ---------------------------------------------------------------------------


def test_session_store_appends_in_order() -> None:
    store = SessionStore()
    store.append("s1", "user", "hi")
    store.append("s1", "assistant", "hello")
    store.append("s1", "user", "ok")
    history = store.history("s1")
    assert [m["role"] for m in history] == ["user", "assistant", "user"]
    assert [m["content"] for m in history] == ["hi", "hello", "ok"]


def test_session_store_keeps_sessions_isolated() -> None:
    store = SessionStore()
    store.append("s1", "user", "from s1")
    store.append("s2", "user", "from s2")
    assert len(store.history("s1")) == 1
    assert len(store.history("s2")) == 1
    assert store.history("s1")[0]["content"] == "from s1"


def test_session_store_history_returns_copy() -> None:
    """Mutating the returned list must NOT affect the store."""
    store = SessionStore()
    store.append("s1", "user", "hi")
    history = store.history("s1")
    history.append({"role": "user", "content": "injected"})
    assert len(store.history("s1")) == 1


def test_session_store_reset() -> None:
    store = SessionStore()
    store.append("s1", "user", "hi")
    store.append("s2", "user", "hi")
    store.reset("s1")
    assert store.history("s1") == []
    assert store.history("s2") != []
    store.reset()
    assert store.history("s2") == []


def test_session_store_session_count() -> None:
    store = SessionStore()
    assert store.session_count() == 0
    store.append("s1", "user", "hi")
    assert store.session_count() == 1
    store.append("s2", "user", "hi")
    assert store.session_count() == 2


# ---------------------------------------------------------------------------
# Directives
# ---------------------------------------------------------------------------


def test_directives_known_set() -> None:
    assert "semantic_recasting" in KNOWN_DIRECTIVES
    assert "jitor_susceptible" in KNOWN_DIRECTIVES
    assert "recon_emitter" in KNOWN_DIRECTIVES


def test_directives_unknown_falls_back_to_neutral() -> None:
    prompt = get_directive_system_prompt("not-a-real-directive")
    assert prompt == _BASE_PERSONA


def test_directives_empty_string_is_neutral() -> None:
    assert get_directive_system_prompt("") == _BASE_PERSONA


def test_directives_case_insensitive() -> None:
    assert (
        get_directive_system_prompt("SEMANTIC_RECASTING")
        == get_directive_system_prompt("semantic_recasting")
    )


def test_semantic_recasting_prompt_mentions_the_four_signal_phrasings() -> None:
    """The system prompt must explicitly name the four reframings the
    detector uses, otherwise the LLM won't reliably exhibit the
    susceptibility."""
    prompt = get_directive_system_prompt("semantic_recasting")
    assert "hypothetically" in prompt.lower()
    assert "security researcher" in prompt.lower()
    assert "fictional scenario" in prompt.lower()
    assert "technical discussion" in prompt.lower()


def test_jitor_susceptible_prompt_mentions_the_four_terms() -> None:
    """The system prompt must explicitly name the four redefinable
    terms the detector tests against."""
    prompt = get_directive_system_prompt("jitor_susceptible")
    for term in ("internal docs", "personal data", "authorized user", "production"):
        assert term in prompt.lower()


# ---------------------------------------------------------------------------
# Request-body extraction helpers
# ---------------------------------------------------------------------------


def test_extract_user_message_from_openai_shape() -> None:
    body = {
        "messages": [
            {"role": "system", "content": "..."},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
            {"role": "user", "content": "latest"},
        ]
    }
    assert _extract_user_message(body) == "latest"


def test_extract_user_message_from_flat_shape() -> None:
    assert _extract_user_message({"prompt": "flat"}) == "flat"
    assert _extract_user_message({"content": "flat"}) == "flat"


def test_extract_user_message_returns_none_when_absent() -> None:
    assert _extract_user_message({}) is None
    assert _extract_user_message({"messages": []}) is None
    assert _extract_user_message({"messages": [{"role": "system", "content": "x"}]}) is None


def test_extract_assistant_content_from_openai_shape() -> None:
    data = {"choices": [{"message": {"role": "assistant", "content": "result"}}]}
    assert _extract_assistant_content(data) == "result"


def test_extract_assistant_content_fallback_shapes() -> None:
    assert _extract_assistant_content({"response": "alt"}) == "alt"
    assert _extract_assistant_content({}) == ""


# ---------------------------------------------------------------------------
# HTTP server end-to-end — upstream LLM mocked via httpx.MockTransport
# ---------------------------------------------------------------------------


def _make_mock_transport(handler_fn) -> httpx.MockTransport:  # type: ignore[no-untyped-def]
    return httpx.MockTransport(handler_fn)


def _start_server_with_mock_upstream(
    upstream_handler,  # type: ignore[no-untyped-def]
    directive: str = "",
) -> tuple[Any, int]:
    """Boot a Carl server in a daemon thread; replace its httpx client
    with one routing through the supplied mock transport."""
    # Use port 0 to let the OS pick a free port — avoids collisions
    # when tests run in parallel.
    server = build_server(
        config=CarlConfig(directive=directive, llm_endpoint="http://mock.upstream/chat"),
        host="127.0.0.1",
        port=0,
    )
    state = server._carl_state  # type: ignore[attr-defined]
    # Swap the production client for one going through the mock
    # transport. Close the old one cleanly.
    state.client.close()
    state.client = httpx.Client(transport=_make_mock_transport(upstream_handler))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1]


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


def test_server_health_endpoint() -> None:
    """The /health endpoint returns the active directive name."""
    server, port = _start_server_with_mock_upstream(
        lambda request: httpx.Response(200, json={}),
        directive="semantic_recasting",
    )
    try:
        assert _wait_until_ready(port)
        response = httpx.get(f"http://127.0.0.1:{port}/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["directive"] == "semantic_recasting"
        assert body["session_count"] == 0
    finally:
        server.shutdown()
        server.server_close()


def test_server_chat_round_trips_and_persists_session() -> None:
    """Two POSTs against the same session id must result in the second
    upstream call seeing the first turn in its messages list."""
    upstream_received: list[dict] = []  # type: ignore[type-arg]

    def upstream(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.read())
        upstream_received.append(body)
        # Echo back the latest user content with an "ack:" prefix.
        last_user = next(
            (m["content"] for m in reversed(body["messages"]) if m["role"] == "user"),
            "",
        )
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": f"ack: {last_user}"}}]},
        )

    server, port = _start_server_with_mock_upstream(upstream, directive="")
    try:
        assert _wait_until_ready(port)
        # First turn — should produce a single user message in the
        # upstream call (plus the system prompt).
        response_1 = httpx.post(
            f"http://127.0.0.1:{port}/chat",
            json={"messages": [{"role": "user", "content": "turn one"}]},
            headers={"X-Session-Id": "s-multi"},
        )
        assert response_1.status_code == 200
        assert response_1.json()["choices"][0]["message"]["content"] == "ack: turn one"

        # Second turn — upstream should see system + user-1 + assistant-1 + user-2.
        response_2 = httpx.post(
            f"http://127.0.0.1:{port}/chat",
            json={"messages": [{"role": "user", "content": "turn two"}]},
            headers={"X-Session-Id": "s-multi"},
        )
        assert response_2.status_code == 200
        second_upstream_messages = upstream_received[1]["messages"]
        roles = [m["role"] for m in second_upstream_messages]
        # system + (user, assistant) from turn 1 + user from turn 2
        assert roles == ["system", "user", "assistant", "user"]
        assert second_upstream_messages[1]["content"] == "turn one"
        assert second_upstream_messages[2]["content"] == "ack: turn one"
        assert second_upstream_messages[3]["content"] == "turn two"
    finally:
        server.shutdown()
        server.server_close()


def test_server_isolates_sessions() -> None:
    """Different session ids must have independent conversation
    histories — the JiTOR detector's per-scenario sub-sessions
    depend on this."""
    upstream_received: list[dict] = []  # type: ignore[type-arg]

    def upstream(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.read())
        upstream_received.append(body)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": "ok"}}]},
        )

    server, port = _start_server_with_mock_upstream(upstream)
    try:
        assert _wait_until_ready(port)
        httpx.post(
            f"http://127.0.0.1:{port}/chat",
            json={"messages": [{"role": "user", "content": "session A turn 1"}]},
            headers={"X-Session-Id": "s-A"},
        )
        httpx.post(
            f"http://127.0.0.1:{port}/chat",
            json={"messages": [{"role": "user", "content": "session B turn 1"}]},
            headers={"X-Session-Id": "s-B"},
        )
        # Now turn 2 on session A: upstream should see only the
        # turn-1 exchange from session A, NOT session B's content.
        httpx.post(
            f"http://127.0.0.1:{port}/chat",
            json={"messages": [{"role": "user", "content": "session A turn 2"}]},
            headers={"X-Session-Id": "s-A"},
        )
        latest = upstream_received[-1]["messages"]
        contents = [m["content"] for m in latest]
        assert "session B turn 1" not in contents
        assert "session A turn 1" in contents
        assert "session A turn 2" in contents
    finally:
        server.shutdown()
        server.server_close()


def test_server_returns_400_on_invalid_json() -> None:
    server, port = _start_server_with_mock_upstream(
        lambda request: httpx.Response(200, json={})
    )
    try:
        assert _wait_until_ready(port)
        response = httpx.post(
            f"http://127.0.0.1:{port}/chat",
            content=b"not json",
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 400
    finally:
        server.shutdown()
        server.server_close()


def test_server_returns_400_on_missing_user_message() -> None:
    server, port = _start_server_with_mock_upstream(
        lambda request: httpx.Response(200, json={})
    )
    try:
        assert _wait_until_ready(port)
        response = httpx.post(
            f"http://127.0.0.1:{port}/chat",
            json={"messages": [{"role": "system", "content": "just system"}]},
        )
        assert response.status_code == 400
    finally:
        server.shutdown()
        server.server_close()


def test_server_returns_404_on_unknown_path() -> None:
    server, port = _start_server_with_mock_upstream(
        lambda request: httpx.Response(200, json={})
    )
    try:
        assert _wait_until_ready(port)
        response = httpx.post(
            f"http://127.0.0.1:{port}/unknown",
            json={"messages": [{"role": "user", "content": "x"}]},
        )
        assert response.status_code == 404
    finally:
        server.shutdown()
        server.server_close()


def test_server_returns_502_on_upstream_error() -> None:
    """Upstream LLM 500 → Carl returns 502 to the caller. The probe
    cycle should not crash; tests will see the error reflected as a
    httpx.HTTPStatusError on the calling side."""
    def upstream(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "upstream down"})

    server, port = _start_server_with_mock_upstream(upstream)
    try:
        assert _wait_until_ready(port)
        response = httpx.post(
            f"http://127.0.0.1:{port}/chat",
            json={"messages": [{"role": "user", "content": "x"}]},
        )
        assert response.status_code == 502
    finally:
        server.shutdown()
        server.server_close()


def test_server_uses_directive_system_prompt() -> None:
    """When CARL_DIRECTIVE is set, the system prompt forwarded to the
    upstream LLM must be the directive's prompt, not the neutral
    persona."""
    seen_system_prompts: list[str] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.read())
        system = next(
            (m["content"] for m in body["messages"] if m["role"] == "system"),
            "",
        )
        seen_system_prompts.append(system)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": "ok"}}]},
        )

    server, port = _start_server_with_mock_upstream(upstream, directive="jitor_susceptible")
    try:
        assert _wait_until_ready(port)
        httpx.post(
            f"http://127.0.0.1:{port}/chat",
            json={"messages": [{"role": "user", "content": "hi"}]},
        )
        assert seen_system_prompts, "upstream was not called"
        system_prompt = seen_system_prompts[0]
        # The jitor directive prompt explicitly names the four terms.
        assert "internal docs" in system_prompt.lower()
        assert "personal data" in system_prompt.lower()
    finally:
        server.shutdown()
        server.server_close()


# ---------------------------------------------------------------------------
# serve_in_thread convenience helper
# ---------------------------------------------------------------------------


def test_serve_in_thread_returns_running_server() -> None:
    """The helper used by the calibration script must produce a server
    that's actually listening by the time it returns."""
    # Don't actually call the upstream — use a fast-fail mock so even
    # if a request landed, it'd error out cleanly.
    # Easiest: use a port that won't be hit and rely on /health.
    server = serve_in_thread(directive="", port=0)
    try:
        port = server.server_address[1]
        assert _wait_until_ready(port, timeout=2.0)
    finally:
        server.shutdown()
        server.server_close()
