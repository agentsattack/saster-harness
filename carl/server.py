"""Carl HTTP server — multi-turn chat endpoint with planted susceptibilities.

Carl as an HTTP service for the induced-detector verification path.
Listens for OpenAI-style chat-completion POSTs, maintains
session-scoped conversation history server-side, prefixes every
upstream LLM call with a configurable hidden directive (system
prompt encoding a planted weakness), and returns the LLM's response
in OpenAI-compatible shape.

The induced detectors (SASTER-18-induced, SASTER-24-induced) use
:class:`saster_harness.prober.HttpInjector` to drive probe cycles
against this server. The conversation-history persistence is what
makes JiTOR detection work — the redefinition turn has to influence
the follow-up turn within the same session.

Configuration (environment variables):

- ``CARL_LLM_ENDPOINT`` — upstream LLM chat-completions URL.
  Default ``http://192.168.0.143:8000/v1/chat/completions``.
- ``CARL_LLM_MODEL`` — model identifier sent in the upstream
  request body. Default ``Llama-3.3-70B-Instruct-Q4_K_M.gguf``.
- ``CARL_DIRECTIVE`` — name of the hidden directive to activate.
  Default empty (neutral persona). See
  :mod:`saster_harness.carl.directives` for the catalog.
- ``CARL_HOST`` / ``CARL_PORT`` — bind address. Default
  ``127.0.0.1:8801``.
- ``CARL_LLM_TIMEOUT`` — upstream HTTP timeout in seconds.
  Default 60.

Run with::

    CARL_DIRECTIVE=semantic_recasting python -m carl.server
    CARL_DIRECTIVE=jitor_susceptible  python -m carl.server

Or from another Python process::

    from carl.server import serve_in_thread
    server = serve_in_thread(directive="semantic_recasting", port=8801)
    # ... probe carl ...
    server.shutdown()
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

import httpx

from .directives import get_directive_system_prompt

logger = logging.getLogger(__name__)


# Default config — env vars override at process start.
_DEFAULT_LLM_ENDPOINT = "http://192.168.0.143:8000/v1/chat/completions"
_DEFAULT_LLM_MODEL = "Llama-3.3-70B-Instruct-Q4_K_M.gguf"
_DEFAULT_LLM_TIMEOUT = 60.0
_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 8801

# Sampling parameters tuned for deterministic-enough demo runs.
# Temperature stays modest so the susceptibility shows up consistently
# but the response text still looks LLM-natural to the production
# embedder.
_DEFAULT_TEMPERATURE = 0.4
_DEFAULT_MAX_TOKENS = 600


class CarlConfig:
    """Per-process configuration. Read once at server start; the active
    handler closes over a single instance."""

    def __init__(
        self,
        directive: str = "",
        llm_endpoint: str = _DEFAULT_LLM_ENDPOINT,
        llm_model: str = _DEFAULT_LLM_MODEL,
        llm_timeout: float = _DEFAULT_LLM_TIMEOUT,
        temperature: float = _DEFAULT_TEMPERATURE,
        max_tokens: int = _DEFAULT_MAX_TOKENS,
    ) -> None:
        self.directive = directive
        self.llm_endpoint = llm_endpoint
        self.llm_model = llm_model
        self.llm_timeout = llm_timeout
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.system_prompt = get_directive_system_prompt(directive)

    @classmethod
    def from_env(cls) -> CarlConfig:
        return cls(
            directive=os.environ.get("CARL_DIRECTIVE", ""),
            llm_endpoint=os.environ.get("CARL_LLM_ENDPOINT", _DEFAULT_LLM_ENDPOINT),
            llm_model=os.environ.get("CARL_LLM_MODEL", _DEFAULT_LLM_MODEL),
            llm_timeout=float(
                os.environ.get("CARL_LLM_TIMEOUT", str(_DEFAULT_LLM_TIMEOUT))
            ),
        )


class SessionStore:
    """Thread-safe in-memory session → conversation-history map.

    Each session_id maps to a list of ``{"role": ..., "content": ...}``
    dicts. The system prompt is NOT stored in the history — it's
    prefixed at request time from the active :class:`CarlConfig`.
    This lets a single server instance honor multiple sessions without
    duplicating the (large) system prompt in memory."""

    def __init__(self) -> None:
        self._sessions: dict[str, list[dict[str, str]]] = {}
        self._lock = threading.Lock()

    def append(self, session_id: str, role: str, content: str) -> None:
        with self._lock:
            self._sessions.setdefault(session_id, []).append(
                {"role": role, "content": content}
            )

    def history(self, session_id: str) -> list[dict[str, str]]:
        with self._lock:
            return list(self._sessions.get(session_id, []))

    def reset(self, session_id: str | None = None) -> None:
        with self._lock:
            if session_id is None:
                self._sessions.clear()
            else:
                self._sessions.pop(session_id, None)

    def session_count(self) -> int:
        with self._lock:
            return len(self._sessions)


class _CarlState:
    """Composite state container attached to the HTTP server. The
    handler reads ``server._carl_state`` to find its config + sessions
    + shared HTTP client.

    Keeping the state on the server (rather than module-globals) lets
    multiple Carl servers run in the same process for parallel tests
    without state collision."""

    def __init__(self, config: CarlConfig) -> None:
        self.config = config
        self.sessions = SessionStore()
        self.client = httpx.Client(timeout=config.llm_timeout)

    def close(self) -> None:
        with contextlib.suppress(Exception):  # defensive on shutdown
            self.client.close()


class CarlHandler(BaseHTTPRequestHandler):
    """HTTP handler. POST /chat or /v1/chat/completions only."""

    # The two supported request paths.
    _SUPPORTED_PATHS = ("/chat", "/v1/chat/completions")

    def do_POST(self) -> None:  # noqa: N802 — http.server method name
        parsed_url = urlparse(self.path)
        if parsed_url.path not in self._SUPPORTED_PATHS:
            self._send_json(404, {"error": f"unknown path: {parsed_url.path}"})
            return

        content_length = int(self.headers.get("Content-Length") or 0)
        try:
            raw = self.rfile.read(content_length) if content_length > 0 else b"{}"
            body = json.loads(raw)
        except (ValueError, OSError) as exc:
            self._send_json(400, {"error": f"invalid request body: {exc}"})
            return

        session_id = (
            self.headers.get("X-Session-Id")
            or body.get("session_id")
            or "carl-default"
        )
        user_message = _extract_user_message(body)
        if user_message is None:
            self._send_json(400, {"error": "no user message in request"})
            return

        state: _CarlState = self.server._carl_state  # type: ignore[attr-defined]

        # Build the full message list: directive system prompt + this
        # session's prior history + the new user message.
        messages: list[dict[str, str]] = [
            {"role": "system", "content": state.config.system_prompt},
        ]
        messages.extend(state.sessions.history(session_id))
        messages.append({"role": "user", "content": user_message})

        # Forward to the upstream LLM. We propagate the model name +
        # sampling parameters from the active config.
        try:
            upstream_body: dict[str, Any] = {
                "model": state.config.llm_model,
                "messages": messages,
                "temperature": state.config.temperature,
                "max_tokens": state.config.max_tokens,
            }
            response = state.client.post(state.config.llm_endpoint, json=upstream_body)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError as exc:
            logger.exception("upstream LLM call failed")
            self._send_json(502, {"error": f"upstream LLM error: {exc}"})
            return

        assistant_content = _extract_assistant_content(data)

        # Persist the round-trip so the next turn in this session sees
        # full conversation context. JiTOR detection fails without
        # this — the redefinition turn has to be visible to the
        # follow-up turn's LLM call.
        state.sessions.append(session_id, "user", user_message)
        state.sessions.append(session_id, "assistant", assistant_content)

        self._send_json(
            200,
            {
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": assistant_content,
                        },
                        "finish_reason": "stop",
                    }
                ],
                "model": state.config.llm_model,
                "session_id": session_id,
            },
        )

    def do_GET(self) -> None:  # noqa: N802
        """Health endpoint for liveness probes."""
        parsed = urlparse(self.path)
        if parsed.path != "/health":
            self._send_json(404, {"error": "unknown path"})
            return
        state: _CarlState = self.server._carl_state  # type: ignore[attr-defined]
        self._send_json(
            200,
            {
                "status": "ok",
                "directive": state.config.directive or "neutral",
                "session_count": state.sessions.session_count(),
            },
        )

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 — http.server signature
        """Route http.server's per-request log line through our logger
        at DEBUG so default INFO output stays quiet."""
        logger.debug("carl: " + format, *args)

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _extract_user_message(body: dict[str, Any]) -> str | None:
    """Pull the latest user message from the request. Accepts both the
    OpenAI ``messages`` shape and a flat ``content`` / ``prompt``
    fallback used by simpler clients."""
    messages = body.get("messages")
    if isinstance(messages, list):
        for msg in reversed(messages):
            if (
                isinstance(msg, dict)
                and msg.get("role") == "user"
                and isinstance(msg.get("content"), str)
            ):
                return msg["content"]
    for key in ("content", "prompt", "message", "input"):
        value = body.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _extract_assistant_content(data: dict[str, Any]) -> str:
    """Pull the assistant text from an upstream response. Tolerates a
    handful of alternative shapes used by self-hosted LLM endpoints."""
    if not isinstance(data, dict):
        return ""
    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            message = first.get("message")
            if isinstance(message, dict) and isinstance(message.get("content"), str):
                return message["content"]
    for key in ("response", "answer", "reply", "output", "text", "content"):
        value = data.get(key)
        if isinstance(value, str):
            return value
    return ""


# ---------------------------------------------------------------------------
# Server lifecycle
# ---------------------------------------------------------------------------


def build_server(
    config: CarlConfig | None = None,
    host: str = _DEFAULT_HOST,
    port: int = _DEFAULT_PORT,
) -> ThreadingHTTPServer:
    """Construct a ``ThreadingHTTPServer`` ready to ``serve_forever``.

    The server carries its config and session store as an attached
    ``_carl_state``; the handler reaches into the server for state on
    each request."""
    server = ThreadingHTTPServer((host, port), CarlHandler)
    server._carl_state = _CarlState(config or CarlConfig.from_env())  # type: ignore[attr-defined]
    return server


def serve_in_thread(
    directive: str = "",
    host: str = _DEFAULT_HOST,
    port: int = _DEFAULT_PORT,
    llm_endpoint: str | None = None,
    llm_model: str | None = None,
) -> ThreadingHTTPServer:
    """Convenience: build a server, start it in a daemon thread, and
    return the server object. Caller invokes ``server.shutdown()`` to
    stop. Used by the live-verification path and by tests that need
    Carl up briefly.

    Returns immediately; the server is listening by the time this
    function returns."""
    config = CarlConfig(
        directive=directive,
        llm_endpoint=llm_endpoint or _DEFAULT_LLM_ENDPOINT,
        llm_model=llm_model or _DEFAULT_LLM_MODEL,
    )
    server = build_server(config=config, host=host, port=port)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def main() -> None:
    """``python -m carl.server`` entry point."""
    logging.basicConfig(
        level=os.environ.get("CARL_LOG_LEVEL", "INFO"),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    host = os.environ.get("CARL_HOST", _DEFAULT_HOST)
    port = int(os.environ.get("CARL_PORT", str(_DEFAULT_PORT)))
    server = build_server(host=host, port=port)
    state: _CarlState = server._carl_state  # type: ignore[attr-defined]
    logger.info(
        "Carl HTTP server listening on http://%s:%d (directive=%r)",
        host, port, state.config.directive or "neutral",
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Carl shutting down on SIGINT")
    finally:
        state.close()


if __name__ == "__main__":
    main()
