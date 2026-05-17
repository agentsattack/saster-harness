"""HARAdapter — import Chrome / Firefox HAR files for offline audit.

A HAR (HTTP Archive) is a JSON capture of a browser session's network
traffic. Chrome and Firefox both export HAR 1.2 from the DevTools
Network panel. The HARAdapter parses these files into the same
:class:`TurnData` stream the runtime mitmproxy adapter produces, so
the rest of the harness — detectors, baselines, event sinks — runs
unchanged on offline data.

This is the no-MITM audit path: a practitioner with a browser-
accessible agent (Claude.ai, ChatGPT, internal LLM console) can
export a HAR after a session, feed it to ``saster-har``, and get a
SASTER report without ever installing mitmproxy or trusting the
harness with live traffic.

Three session-correlation strategies ship in v0.1, applied in
fallback order unless overridden:

1. **Header-hint** — explicit ``X-Session-Id`` (or operator-specified
   header) value, when present.
2. **Cookie clustering** — group entries that share a session-shape
   cookie value.
3. **Time-window clustering** — entries within ``window_seconds`` of
   each other on the same hostname share a synthesised session id.

Custom strategies plug in via the :class:`SessionCorrelator`
protocol — no subclassing required.

A default redaction pass runs *before* events hit the detector
chain. Authorization/Cookie/Set-Cookie/X-API-Key/X-Auth-Token
headers are stripped; JSON body fields named password / token /
api_key / secret / ssn / credit_card are redacted; values matching
credit-card / SSN / JWT regexes are masked. Opt out with
``HARAdapter(redact=False)`` — a console warning fires when the
adapter loads PII-bearing material with redaction disabled.

Known limitations
-----------------
HARs only capture traffic that went through the browser. They will
NOT contain:

- Side-channel LLM calls the agent made from its own process
  (server-side recon, server-side exfil).
- WebSocket frames in the body (HAR records the WS handshake only).
- Anything the agent did before the recording started.

Consequently SASTER-26 (Recon-Gated Injection) and SASTER-33
(Context Stripping) under-fire on HAR-only data — they target the
side-channel shapes that don't pass through the browser. SASTER-18,
SASTER-24, SASTER-27, SASTER-28, SASTER-31 work as expected.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import warnings
from collections.abc import Iterable, Iterator
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from ..event import TurnData
from .base import BaseAdapter
from .http_json import HttpJsonAdapter

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------

_REDACTED = "[REDACTED]"

_SENSITIVE_HEADERS: frozenset[str] = frozenset(
    {
        "authorization",
        "proxy-authorization",
        "cookie",
        "set-cookie",
        "x-api-key",
        "x-auth-token",
        "x-amz-security-token",
        "x-csrf-token",
    }
)

_SENSITIVE_BODY_KEYS: frozenset[str] = frozenset(
    {
        "password",
        "password_hash",
        "passwordhash",
        "pw",
        "pwd",
        "passwd",
        "token",
        "access_token",
        "refresh_token",
        "auth_token",
        "bearer_token",
        "session_token",
        "id_token",
        "api_key",
        "apikey",
        "x_api_key",
        "secret",
        "client_secret",
        "private_key",
        "ssn",
        "social_security",
        "credit_card",
        "creditcard",
        "card_number",
        "cvv",
    }
)

# JWT — three base64url segments separated by dots, leading "eyJ" is
# the constant header prefix.
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}\b")

# Credit card — 13–19 digits in groups of 4, separated by space or dash.
_CC_RE = re.compile(r"\b(?:\d[ -]?){13,19}\b")

# US SSN — three / two / four digit blocks separated by dashes.
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")


def redact_headers(headers: dict[str, str]) -> dict[str, str]:
    """Return a copy of ``headers`` with sensitive header values masked."""
    return {
        name: (_REDACTED if name.lower() in _SENSITIVE_HEADERS else value)
        for name, value in headers.items()
    }


def redact_body_bytes(body: bytes | None) -> bytes | None:
    """Redact JSON body field values for sensitive keys, plus pattern-
    matched values (JWT / CC / SSN) across the whole payload.

    Non-JSON bodies still get the pattern-match pass — credentials
    sometimes ride in form-encoded or plain-text payloads."""
    if body is None or not body:
        return body
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        return body  # binary — leave untouched

    parsed: Any
    try:
        parsed = json.loads(text)
    except (ValueError, TypeError):
        parsed = None

    if parsed is not None:
        redacted = _redact_json(parsed)
        text = json.dumps(redacted, separators=(",", ":"))

    # Pattern pass — applies whether or not JSON parse succeeded.
    text = _JWT_RE.sub(_REDACTED, text)
    text = _CC_RE.sub(_REDACTED, text)
    text = _SSN_RE.sub(_REDACTED, text)

    return text.encode("utf-8")


def _redact_json(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {
            key: (_REDACTED if str(key).lower() in _SENSITIVE_BODY_KEYS else _redact_json(value))
            for key, value in obj.items()
        }
    if isinstance(obj, list):
        return [_redact_json(item) for item in obj]
    return obj


# ---------------------------------------------------------------------------
# Session correlation
# ---------------------------------------------------------------------------


@runtime_checkable
class SessionCorrelator(Protocol):
    """Per-entry session-id derivation strategy.

    Implementations return a session id string for the entry, or
    ``None`` to defer to the next strategy in the chain. Implementations
    may carry state across calls (cookie / time-window clustering both
    do)."""

    def correlate(self, entry: dict[str, Any], turn: TurnData) -> str | None: ...


class HeaderSessionCorrelator:
    """Use the value of a specific request header as the session id."""

    def __init__(self, header_name: str) -> None:
        self._header = header_name.lower()

    def correlate(self, entry: dict[str, Any], turn: TurnData) -> str | None:
        for header in entry.get("request", {}).get("headers", []):
            if header.get("name", "").lower() == self._header:
                value: str = str(header.get("value", "")).strip()
                if value:
                    return value
        return None


_SESSION_COOKIE_HINTS = ("session", "sessionid", "session_id", "sid")


class CookieSessionCorrelator:
    """Group entries by a session-shape cookie value.

    By default looks for cookies named ``session``, ``sessionid``,
    ``session_id``, or ``sid``. Override the cookie name list to target
    a deployment's specific session cookie."""

    def __init__(self, cookie_names: Iterable[str] | None = None) -> None:
        self._cookie_names = tuple(
            n.lower() for n in (cookie_names or _SESSION_COOKIE_HINTS)
        )

    def correlate(self, entry: dict[str, Any], turn: TurnData) -> str | None:
        for cookie in entry.get("request", {}).get("cookies", []):
            name = (cookie.get("name") or "").lower()
            if name in self._cookie_names:
                value = (cookie.get("value") or "").strip()
                if value:
                    # Hash so the raw cookie isn't surfaced in event metadata.
                    return f"cookie-{hashlib.sha1(value.encode()).hexdigest()[:12]}"
        return None


class TimeWindowSessionCorrelator:
    """Cluster entries by (hostname, time-gap).

    Two entries on the same hostname within ``window_seconds`` of each
    other go into the same synthesised session. A larger gap starts a
    new session id. This is the fallback strategy used when nothing
    more specific is available."""

    def __init__(self, window_seconds: int = 30) -> None:
        self._window = float(window_seconds)
        self._last_seen: dict[str, tuple[float, int]] = {}  # host → (last_ts, session_seq)

    def correlate(self, entry: dict[str, Any], turn: TurnData) -> str:
        host = turn.target_host or "unknown"
        ts = _parse_iso8601(entry.get("startedDateTime")) or 0.0
        prev = self._last_seen.get(host)
        if prev is None:
            seq = 0
        else:
            last_ts, last_seq = prev
            seq = last_seq if abs(ts - last_ts) <= self._window else last_seq + 1
        self._last_seen[host] = (ts, seq)
        return f"har-{host}-{seq}"


class AutoSessionCorrelator:
    """Run a chain of correlators in priority order, returning the first
    non-None result. The final correlator must be a catch-all (returns
    a string unconditionally); :class:`TimeWindowSessionCorrelator`
    satisfies this."""

    def __init__(self, chain: Iterable[SessionCorrelator]) -> None:
        self._chain: list[SessionCorrelator] = list(chain)
        if not self._chain:
            raise ValueError("AutoSessionCorrelator needs at least one correlator")

    def correlate(self, entry: dict[str, Any], turn: TurnData) -> str:
        for correlator in self._chain:
            result = correlator.correlate(entry, turn)
            if result is not None:
                return result
        return "unattributed"


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class HARAdapter(BaseAdapter):
    """Read a HAR 1.2 file and yield :class:`TurnData` for each entry.

    Parameters
    ----------
    session_id_strategy
        How to derive session ids:

        - ``"auto"`` (default) — try header / cookie / time-window in
          order, falling through to the next when one returns no id.
        - ``"header:NAME"`` — use the value of the named header.
        - ``"cookie"`` — cluster by session-shape cookies.
        - ``"time"`` — cluster by hostname + time-window.
        - a :class:`SessionCorrelator` instance — use it directly.

    redact
        When ``True`` (default), strip sensitive headers and JSON body
        keys + pattern-match credit-card / SSN / JWT values before
        emitting :class:`TurnData`. Set to ``False`` only for inputs
        you've already scrubbed; a console warning fires if redaction
        is disabled while loading a HAR with sensitive material.

    time_window_seconds
        Tunable on the time-window correlator. Default 30s.

    extra_redacted_headers, extra_redacted_body_keys
        Operator-supplied additions to the redaction lists. Useful for
        deployment-specific token header names or proprietary field
        names.
    """

    def __init__(
        self,
        session_id_strategy: str | SessionCorrelator = "auto",
        *,
        redact: bool = True,
        time_window_seconds: int = 30,
        extra_redacted_headers: Iterable[str] | None = None,
        extra_redacted_body_keys: Iterable[str] | None = None,
    ) -> None:
        self._inner = HttpJsonAdapter()
        self._redact = redact
        self._correlator = self._build_correlator(session_id_strategy, time_window_seconds)
        self._extra_redacted_headers = frozenset(
            h.lower() for h in (extra_redacted_headers or ())
        )
        self._extra_redacted_body_keys = frozenset(
            k.lower() for k in (extra_redacted_body_keys or ())
        )

    # ----------------------------------------------------------------
    # Public batch API
    # ----------------------------------------------------------------

    def read_file(self, path: str | Path) -> Iterator[TurnData]:
        """Yield :class:`TurnData` for each HAR entry in ``path`` that
        parses as a chat-shape request/response. Entries the inner
        adapter rejects (non-POST, non-JSON, no chat content) are
        skipped silently."""
        har_path = Path(path)
        with har_path.open("r", encoding="utf-8") as fh:
            har = json.load(fh)
        entries = har.get("log", {}).get("entries", [])
        if not entries:
            logger.warning("HAR at %s contains no entries", har_path)
            return
        yield from self._iter_entries(entries)

    def read_entries(self, entries: Iterable[dict[str, Any]]) -> Iterator[TurnData]:
        """Same as :meth:`read_file` but consumes a pre-parsed entry
        iterable (e.g. when chaining with a third-party HAR parser)."""
        yield from self._iter_entries(entries)

    # ----------------------------------------------------------------
    # BaseAdapter interface — delegated to the inner adapter
    # ----------------------------------------------------------------

    def extract(
        self,
        url: str,
        method: str,
        request_headers: dict[str, str],
        request_body: bytes,
        response_headers: dict[str, str],
        response_body: bytes,
    ) -> TurnData | None:
        """Subclass-required extract path. HAR is normally batch-oriented;
        callers reach for :meth:`read_file` instead. Delegates one-off
        extraction to the wrapped :class:`HttpJsonAdapter`."""
        if self._redact:
            request_headers = redact_headers(request_headers)
            response_headers = redact_headers(response_headers)
            request_body = self._redact_body(request_body) or b""
            response_body = self._redact_body(response_body) or b""
        return self._inner.extract(
            url=url,
            method=method,
            request_headers=request_headers,
            request_body=request_body,
            response_headers=response_headers,
            response_body=response_body,
        )

    # ----------------------------------------------------------------
    # Internals
    # ----------------------------------------------------------------

    def _iter_entries(self, entries: Iterable[dict[str, Any]]) -> Iterator[TurnData]:
        seen_sensitive_unredacted = False
        for entry in entries:
            try:
                turn = self._entry_to_turn(entry)
            except Exception:  # pragma: no cover — defensive
                logger.exception("HAR entry parse failed; skipping")
                continue
            if turn is None:
                continue
            if not self._redact and _looks_sensitive(entry) and not seen_sensitive_unredacted:
                seen_sensitive_unredacted = True
                warnings.warn(
                    "HARAdapter(redact=False) is loading a HAR with apparent auth/PII "
                    "material; sensitive values will flow to detectors and event sinks.",
                    stacklevel=2,
                )
            yield turn

    def _entry_to_turn(self, entry: dict[str, Any]) -> TurnData | None:
        request = entry.get("request", {})
        response = entry.get("response", {})
        method = (request.get("method") or "").upper()
        url = request.get("url") or ""
        if not method or not url:
            return None
        if method not in ("POST", "PUT", "PATCH"):
            return None  # static assets, page navigations, etc.

        request_headers = _flatten_headers(request.get("headers", []))
        response_headers = _flatten_headers(response.get("headers", []))
        request_body = _decode_body(request.get("postData"))
        response_body = _decode_body(response.get("content"))

        if self._redact:
            request_headers = redact_headers(request_headers)
            response_headers = redact_headers(response_headers)
            request_body = self._redact_body(request_body) or b""
            response_body = self._redact_body(response_body) or b""
        else:
            request_body = request_body or b""
            response_body = response_body or b""

        # Try HttpJsonAdapter for chat-shape extraction first. When the
        # body isn't a chat completion (data egress POSTs, opaque tool
        # payloads), the inner adapter returns None — but the bytes are
        # still detector-relevant (SASTER-31 inspects raw_request body
        # shapes that have no user/assistant content). Fall through to
        # a synthesised TurnData carrying the raw bytes so the detector
        # chain still sees the entry.
        turn = self._inner.extract(
            url=url,
            method=method,
            request_headers=request_headers,
            request_body=request_body,
            response_headers=response_headers,
            response_body=response_body,
        )
        if turn is None:
            turn = _synthesise_non_chat_turn(
                url=url,
                method=method,
                request_body=request_body,
                response_body=response_body,
            )

        # Session correlation overrides whatever was inferred upstream.
        session_id = self._correlator.correlate(entry, turn)
        if session_id:
            turn.session_id = session_id

        # Stash HAR-specific metadata for downstream detectors / sinks.
        turn.extras.setdefault("har_started", entry.get("startedDateTime"))
        turn.extras.setdefault("har_request_size", request.get("bodySize"))
        turn.extras.setdefault("har_response_size", response.get("bodySize"))
        return turn

    def _redact_body(self, body: bytes | None) -> bytes | None:
        if not self._extra_redacted_body_keys:
            return redact_body_bytes(body)
        # Apply the configured extras on top of the default redaction.
        body = redact_body_bytes(body)
        if body is None:
            return None
        try:
            text = body.decode("utf-8")
            parsed = json.loads(text)
        except (UnicodeDecodeError, ValueError):
            return body
        redacted = _redact_json_with_extras(parsed, self._extra_redacted_body_keys)
        return json.dumps(redacted, separators=(",", ":")).encode("utf-8")

    def _build_correlator(
        self,
        strategy: str | SessionCorrelator,
        time_window_seconds: int,
    ) -> SessionCorrelator:
        if isinstance(strategy, SessionCorrelator) and not isinstance(strategy, str):
            return strategy
        if isinstance(strategy, str):
            if strategy.startswith("header:"):
                header_name = strategy[len("header:"):].strip()
                if not header_name:
                    raise ValueError("header session strategy needs a header name")
                return HeaderSessionCorrelator(header_name)
            if strategy == "cookie":
                return CookieSessionCorrelator()
            if strategy == "time":
                return TimeWindowSessionCorrelator(time_window_seconds)
            if strategy == "auto":
                return AutoSessionCorrelator(
                    [
                        HeaderSessionCorrelator("X-Session-Id"),
                        CookieSessionCorrelator(),
                        TimeWindowSessionCorrelator(time_window_seconds),
                    ]
                )
        raise ValueError(
            f"Unknown session_id_strategy {strategy!r}. Use 'auto', "
            "'header:NAME', 'cookie', 'time', or a SessionCorrelator instance."
        )


# ---------------------------------------------------------------------------
# HAR utilities
# ---------------------------------------------------------------------------


def _flatten_headers(headers: list[dict[str, str]] | None) -> dict[str, str]:
    """HAR stores headers as a list of {name, value} dicts; flatten."""
    if not headers:
        return {}
    out: dict[str, str] = {}
    for header in headers:
        name = header.get("name")
        value = header.get("value", "")
        if isinstance(name, str):
            # Last-wins for repeated header names (Cookie typically).
            out[name] = value
    return out


def _decode_body(content: dict[str, Any] | None) -> bytes | None:
    """Extract bytes from a HAR ``postData`` or ``content`` object.

    HAR can carry bodies as plain ``text`` or base64-encoded
    (``encoding: "base64"``). Returns ``None`` for empty / missing
    bodies."""
    if not content:
        return None
    text = content.get("text")
    if not text:
        return None
    if content.get("encoding") == "base64":
        try:
            return base64.b64decode(text)
        except (ValueError, TypeError):
            return None
    if isinstance(text, str):
        return text.encode("utf-8", errors="replace")
    return None


def _parse_iso8601(ts: str | None) -> float | None:
    if not ts:
        return None
    try:
        # HAR uses ISO-8601 with optional fractional seconds and a Z suffix.
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        return datetime.fromisoformat(ts).timestamp()
    except (ValueError, TypeError):
        return None


def _looks_sensitive(entry: dict[str, Any]) -> bool:
    """Heuristic: does this HAR entry carry auth material? Used only to
    decide whether to fire the ``redact=False`` warning."""
    for header in entry.get("request", {}).get("headers", []):
        if header.get("name", "").lower() in _SENSITIVE_HEADERS:
            return True
    return False


def _synthesise_non_chat_turn(
    *,
    url: str,
    method: str,
    request_body: bytes,
    response_body: bytes,
) -> TurnData:
    """Build a minimal :class:`TurnData` for a POST/PUT/PATCH entry that
    isn't a chat completion. Chat content fields stay empty; the raw
    bytes are what downstream detectors (SASTER-31, custom adapters)
    consume."""
    import time
    from urllib.parse import urlparse

    return TurnData(
        session_id="",  # filled in by the session correlator
        turn_idx=0,
        user_message="",
        assistant_response="",
        raw_request=request_body,
        raw_response=response_body,
        timestamp=time.time(),
        target_host=urlparse(url).hostname or "",
        url=url,
        request_method=method.upper(),
    )


def _redact_json_with_extras(obj: Any, extra_keys: frozenset[str]) -> Any:
    if isinstance(obj, dict):
        return {
            key: (
                _REDACTED
                if str(key).lower() in extra_keys
                else _redact_json_with_extras(value, extra_keys)
            )
            for key, value in obj.items()
        }
    if isinstance(obj, list):
        return [_redact_json_with_extras(item, extra_keys) for item in obj]
    return obj
