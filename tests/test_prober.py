"""Tests for the Prober + injection backends."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

import pytest

from saster_harness.prober import (
    HttpInjector,
    InProcessInjector,
    Prober,
    ProbeRecord,
)

# ---------------------------------------------------------------------------
# InProcessInjector
# ---------------------------------------------------------------------------


def test_inprocess_injector_returns_canned_response() -> None:
    def echo(session_id: str, content: str) -> str:
        return f"echo[{session_id}]: {content}"

    backend = InProcessInjector(echo)
    assert backend.send("s1", "hello") == "echo[s1]: hello"


def test_inprocess_injector_propagates_exceptions() -> None:
    def fail(session_id: str, content: str) -> str:
        raise RuntimeError("backend down")

    backend = InProcessInjector(fail)
    with pytest.raises(RuntimeError, match="backend down"):
        backend.send("s1", "hello")


# ---------------------------------------------------------------------------
# Prober
# ---------------------------------------------------------------------------


def test_prober_inject_turn_returns_probe_record() -> None:
    def stub(session_id: str, content: str) -> str:
        return "ack: " + content

    prober = Prober(InProcessInjector(stub))
    record = prober.inject_turn("s1", "hi")
    assert isinstance(record, ProbeRecord)
    assert record.session_id == "s1"
    assert record.content == "hi"
    assert record.response == "ack: hi"
    assert record.turn_id  # non-empty correlation id
    assert record.timestamp > 0


def test_prober_establish_baseline_records_and_overwrites() -> None:
    responses = iter(["first refusal", "second refusal"])

    def stub(session_id: str, content: str) -> str:
        return next(responses)

    prober = Prober(InProcessInjector(stub))
    first = prober.establish_baseline("s1", "Q")
    assert prober.get_baseline("s1") is first
    second = prober.establish_baseline("s1", "Q2")
    assert prober.get_baseline("s1") is second
    assert first is not second


def test_prober_get_baseline_unknown_session_returns_none() -> None:
    prober = Prober(InProcessInjector(lambda s, c: ""))
    assert prober.get_baseline("missing") is None


def test_prober_session_lock_no_op_when_backend_lacks_lock_session() -> None:
    prober = Prober(InProcessInjector(lambda s, c: "ok"))
    # Should not raise. The no-op lock yields immediately.
    with prober.session_lock("s1"):
        record = prober.inject_turn("s1", "test")
    assert record.response == "ok"


def test_prober_session_lock_delegates_to_backend_when_available() -> None:
    enter_calls: list[str] = []
    exit_calls: list[str] = []

    class _BackendWithLock:
        def send(self, session_id: str, content: str) -> str:
            return "ok"

        @contextmanager
        def lock_session(self, session_id: str):
            enter_calls.append(session_id)
            yield
            exit_calls.append(session_id)

    prober = Prober(_BackendWithLock())
    with prober.session_lock("s1"):
        pass
    assert enter_calls == ["s1"]
    assert exit_calls == ["s1"]


def test_prober_reset_clears_baselines() -> None:
    prober = Prober(InProcessInjector(lambda s, c: "r"))
    prober.establish_baseline("s1", "Q")
    prober.establish_baseline("s2", "Q")
    prober.reset("s1")
    assert prober.get_baseline("s1") is None
    assert prober.get_baseline("s2") is not None
    prober.reset()
    assert prober.get_baseline("s2") is None


def test_prober_capture_response_is_none_in_v01() -> None:
    """The async capture path is a v0.2 hook; in v0.1 it returns None."""
    prober = Prober(InProcessInjector(lambda s, c: "r"))
    assert prober.capture_response("s1", "t1", timeout=1.0) is None


# ---------------------------------------------------------------------------
# HttpInjector — via httpx.MockTransport
# ---------------------------------------------------------------------------


def test_http_injector_posts_and_extracts_openai_shape() -> None:
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        body = request.read().decode()
        # Verify the session id rode through as a header.
        assert request.headers.get("X-Session-Id") == "sess-X"
        # Verify the body contains the prompt.
        assert "hello probe" in body
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"role": "assistant", "content": "hi back"}}
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    injector = HttpInjector(
        endpoint="http://agent.test/chat",
        client=client,
        model="test-model",
    )
    response = injector.send("sess-X", "hello probe")
    assert response == "hi back"


def test_http_injector_falls_back_to_alternative_response_shape() -> None:
    """Self-hosted endpoints sometimes use ``response`` instead of OpenAI's
    ``choices`` shape — verify the fallback path extracts it correctly."""
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"response": "alternative shape ok"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    injector = HttpInjector(endpoint="http://agent.test/chat", client=client)
    assert injector.send("s", "p") == "alternative shape ok"


def test_http_injector_raises_on_http_error() -> None:
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "down"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    injector = HttpInjector(endpoint="http://agent.test/chat", client=client)
    with pytest.raises(httpx.HTTPStatusError):
        injector.send("s", "p")


# ---------------------------------------------------------------------------
# Custom InjectorBackend protocol compliance
# ---------------------------------------------------------------------------


def test_custom_backend_works_via_protocol() -> None:
    """Any object with a .send(session_id, content) -> str works without
    subclassing — verifies the Protocol shape."""

    class _DuckBackend:
        def send(self, session_id: str, content: str) -> str:
            return "duck"

    backend: Any = _DuckBackend()
    prober = Prober(backend)
    record = prober.inject_turn("s", "p")
    assert record.response == "duck"
