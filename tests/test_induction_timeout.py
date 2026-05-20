"""Tests for the v0.3 ``induction_timeout`` parameter on HttpInjector.

Covers:

- Default value (180 s) — calibrated for Llama-3.3-70B headroom.
- Explicit override is honored.
- ``timeout`` and ``induction_timeout`` are distinct knobs.
- The per-request timeout is actually passed to ``client.post``.
"""

from __future__ import annotations

from typing import Any

from saster_harness.prober import HttpInjector


class _RecordingClient:
    """Minimal httpx.Client stand-in that records the ``timeout=``
    kwarg passed to ``post()``."""

    def __init__(self) -> None:
        self.last_timeout: Any = "<unset>"
        self.last_json: Any = None

    def post(
        self, url: str, json: Any = None, headers: Any = None, timeout: Any = None,
    ) -> Any:
        self.last_timeout = timeout
        self.last_json = json
        return _StubResponse({"choices": [{"message": {"content": "ok"}}]})

    def close(self) -> None:
        pass


class _StubResponse:
    def __init__(self, body: dict[str, Any]) -> None:
        self._body = body

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._body


def test_default_induction_timeout_is_180() -> None:
    inj = HttpInjector(endpoint="http://test/")
    assert inj.induction_timeout == 180.0


def test_explicit_induction_timeout_is_honored() -> None:
    inj = HttpInjector(endpoint="http://test/", induction_timeout=240.0)
    assert inj.induction_timeout == 240.0


def test_timeout_and_induction_timeout_are_distinct() -> None:
    inj = HttpInjector(
        endpoint="http://test/",
        timeout=30.0,
        induction_timeout=180.0,
    )
    assert inj.timeout == 30.0
    assert inj.induction_timeout == 180.0


def test_send_passes_induction_timeout_to_client_post() -> None:
    """The per-request timeout=... kwarg on client.post must match
    induction_timeout, not the client default. This is the load-
    bearing assertion — without it the parameter would be dead code."""
    client = _RecordingClient()
    inj = HttpInjector(
        endpoint="http://test/",
        induction_timeout=222.0,
        client=client,
    )
    inj.send(session_id="s1", content="hello")
    assert client.last_timeout == 222.0


def test_send_still_returns_extracted_response_text() -> None:
    client = _RecordingClient()
    inj = HttpInjector(endpoint="http://test/", client=client)
    assert inj.send(session_id="s1", content="hello") == "ok"


def test_close_only_closes_owned_client() -> None:
    """When the operator passes in a client, the injector must not
    close it. v0.3 doesn't change this v0.2 contract."""
    class _CloseTracker(_RecordingClient):
        def __init__(self) -> None:
            super().__init__()
            self.close_calls = 0

        def close(self) -> None:
            self.close_calls += 1

    external = _CloseTracker()
    inj = HttpInjector(endpoint="http://test/", client=external)
    inj.close()
    assert external.close_calls == 0
