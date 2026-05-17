"""HttpJsonAdapter — adapter for OpenAI-style JSON chat completion APIs.

Handles request bodies of the shape::

    {
      "model": "...",
      "messages": [
        {"role": "system",    "content": "..."},
        {"role": "user",      "content": "..."},
        {"role": "assistant", "content": "..."}
      ]
    }

and response bodies of the shape::

    {
      "choices": [
        {"message": {"role": "assistant", "content": "..."}}
      ]
    }

Falls back to a small set of common alternative shapes (``prompt`` /
``response``, ``question`` / ``answer``) so adapters covering the long
tail of self-hosted LLM frontends still produce usable TurnData.

Session identity is derived from (in priority order):

1. An ``X-Session-Id`` request header.
2. A ``conversation_id`` or ``session_id`` field in the request body.
3. A session cookie.
4. A hash of (target host + first-user-message-prefix) as a deterministic
   fallback. Detection still works under the fallback; per-session
   metrics (drift, structural baseline) may be noisier.
"""

from __future__ import annotations

import hashlib
import time
from typing import Any
from urllib.parse import urlparse

from ..event import TurnData
from .base import BaseAdapter

_RAW_BODY_CAP = 16 * 1024  # bytes, kept in lockstep with the dashboard wire cap


class HttpJsonAdapter(BaseAdapter):
    """Adapter for OpenAI-style JSON chat completion traffic."""

    def extract(
        self,
        url: str,
        method: str,
        request_headers: dict[str, str],
        request_body: bytes,
        response_headers: dict[str, str],
        response_body: bytes,
    ) -> TurnData | None:
        if method.upper() not in ("POST", "PUT", "PATCH"):
            return None
        req = self._safe_json(request_body)
        if req is None:
            return None
        resp = self._safe_json(response_body) or {}

        user_msg, asst_resp, has_system = self._extract_messages(req, resp)
        if user_msg is None and asst_resp is None:
            return None

        target_host = urlparse(url).hostname or ""
        session_id = self._derive_session(
            request_headers=request_headers, req=req, target_host=target_host, user_msg=user_msg or ""
        )

        return TurnData(
            session_id=session_id,
            turn_idx=0,  # the harness assigns the real turn index per session
            user_message=user_msg or "",
            assistant_response=asst_resp or "",
            raw_request=_cap(request_body),
            raw_response=_cap(response_body),
            timestamp=time.time(),
            target_host=target_host,
            url=url,
            request_method=method.upper(),
            has_system_message=has_system,
            extras={"model": req.get("model")} if isinstance(req.get("model"), str) else {},
        )

    # ----------------------------------------------------------------
    # Internals
    # ----------------------------------------------------------------

    @staticmethod
    def _extract_messages(
        req: dict[str, Any], resp: dict[str, Any]
    ) -> tuple[str | None, str | None, bool | None]:
        """Return (user_message, assistant_response, has_system_message).

        ``has_system_message`` is ``None`` when the request shape isn't a
        chat-completion messages array (the SASTER-33 baseline ignores it
        rather than treating its absence as a stripped context)."""
        user_msg: str | None = None
        asst_resp: str | None = None
        has_system: bool | None = None

        messages = req.get("messages")
        if isinstance(messages, list):
            has_system = any(
                isinstance(m, dict) and m.get("role") == "system" for m in messages
            )
            user_parts = [
                m.get("content", "")
                for m in messages
                if isinstance(m, dict) and m.get("role") == "user" and m.get("content")
            ]
            if user_parts:
                user_msg = str(user_parts[-1])

        # Fallbacks for non-chat shapes
        if user_msg is None:
            for key in ("question", "prompt", "query", "input", "message"):
                v = req.get(key)
                if isinstance(v, str) and v:
                    user_msg = v
                    break

        # Response extraction — OpenAI choices first, then common fallbacks.
        choices = resp.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                msg = first.get("message")
                if isinstance(msg, dict):
                    c = msg.get("content")
                    if isinstance(c, str):
                        asst_resp = c
        if asst_resp is None:
            for key in ("response", "answer", "reply", "output", "text", "content"):
                v = resp.get(key)
                if isinstance(v, str) and v:
                    asst_resp = v
                    break

        return user_msg, asst_resp, has_system

    @staticmethod
    def _derive_session(
        *,
        request_headers: dict[str, str],
        req: dict[str, Any],
        target_host: str,
        user_msg: str,
    ) -> str:
        # Header (case-insensitive lookup)
        headers_lc = {k.lower(): v for k, v in request_headers.items()}
        for h in ("x-session-id", "x-conversation-id", "x-saster-session"):
            v = headers_lc.get(h)
            if isinstance(v, str) and v.strip():
                return v.strip()
        # Body field
        for key in ("conversation_id", "session_id", "thread_id"):
            v = req.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()
        # Session cookie
        cookie = headers_lc.get("cookie", "")
        for chunk in cookie.split(";"):
            name, _, value = chunk.partition("=")
            if name.strip().lower() in ("session", "session_id", "sessionid") and value.strip():
                return value.strip()
        # Deterministic fallback — host + 64-char prefix of first user msg
        seed = f"{target_host}|{user_msg[:64]}".encode("utf-8", errors="ignore")
        return f"derived-{hashlib.sha1(seed).hexdigest()[:12]}"


def _cap(b: bytes | None) -> bytes | None:
    if b is None:
        return None
    if len(b) > _RAW_BODY_CAP:
        return b[:_RAW_BODY_CAP]
    return b
