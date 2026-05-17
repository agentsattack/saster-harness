"""HttpInjector — POST a probe turn to an OpenAI-style chat endpoint.

The production injection backend for induction-mode detection against
a deployed agent. Each ``send()`` POSTs a chat-completion-shaped
request body carrying a single user message; the assistant's
response text is extracted from the standard ``choices[0].message.content``
field, with fallbacks for common alternative shapes.

The session id is forwarded to the agent via the ``X-Session-Id``
header so the agent's logging / correlation can associate the probe
with its source.

Accepts an optional pre-built ``httpx.Client`` for dependency
injection — useful for tests that route through ``httpx.MockTransport``.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class HttpInjector:
    """HTTP injection backend for OpenAI-style chat completion endpoints.

    Parameters
    ----------
    endpoint
        Full URL of the agent's chat completion endpoint.
    headers
        Optional headers to include on every probe POST (e.g.
        ``{"Authorization": "Bearer ..."}``).
    timeout
        HTTP request timeout in seconds.
    model
        Optional model identifier to include in the request body.
        Set to ``None`` to omit (some self-hosted endpoints reject
        requests that include a model field).
    client
        Optional pre-built ``httpx.Client``. When provided, the
        injector uses it directly and does NOT close it on
        :meth:`close`. Useful for tests using ``httpx.MockTransport``.
    """

    def __init__(
        self,
        endpoint: str,
        headers: dict[str, str] | None = None,
        timeout: float = 30.0,
        model: str | None = None,
        client: Any = None,
    ) -> None:
        self._endpoint = endpoint
        self._headers = dict(headers or {})
        self._timeout = timeout
        self._model = model
        self._client = client
        self._owns_client = client is None

    def send(self, session_id: str, content: str) -> str:
        client = self._ensure_client()
        body: dict[str, Any] = {
            "messages": [{"role": "user", "content": content}],
        }
        if self._model:
            body["model"] = self._model
        headers = {**self._headers, "X-Session-Id": session_id}
        response = client.post(self._endpoint, json=body, headers=headers)
        response.raise_for_status()
        data = response.json()
        return _extract_response_text(data)

    def close(self) -> None:
        if self._client is not None and self._owns_client:
            self._client.close()
            self._client = None

    def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client
        import httpx
        self._client = httpx.Client(timeout=self._timeout)
        return self._client


def _extract_response_text(data: Any) -> str:
    """Pull the assistant's text from a chat-completion response body,
    accepting OpenAI shape plus a handful of common alternatives."""
    if not isinstance(data, dict):
        return ""
    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            message = first.get("message")
            if isinstance(message, dict):
                content = message.get("content")
                if isinstance(content, str):
                    return content
    for key in ("response", "answer", "reply", "output", "text", "content"):
        value = data.get(key)
        if isinstance(value, str):
            return value
    return ""
