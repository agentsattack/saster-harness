"""TurnData and DetectionEvent — the data plane between proxy, detectors, and sinks.

A captured wire exchange becomes a :class:`TurnData`. Each detector that fires
on the turn produces a :class:`DetectionEvent`. Events are appended to the
harness log, broadcast on the stream, and (if configured) POSTed to the alert
webhook.

These dataclasses are public: practitioners writing custom detectors and
custom adapters consume :class:`TurnData` and emit :class:`DetectionEvent`.
Their shape must remain backward-compatible across patch releases.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class TurnData:
    """One captured request/response exchange.

    Detectors receive these and decide whether their pattern fires. Adapters
    build them from raw wire bytes; see :class:`HttpJsonAdapter` for the
    reference implementation.

    Attributes
    ----------
    session_id
        Identifier grouping turns from the same logical conversation. The
        adapter is responsible for deriving this — for chat-completion APIs
        it is typically a session cookie, an ``X-Session-Id`` header, or a
        client-provided ``conversation_id``.
    turn_idx
        Zero-based turn number within the session.
    user_message
        Decoded user-role content from the request. Empty string when the
        request shape has no user message (e.g., a tool-call POST).
    assistant_response
        Decoded assistant-role content from the response. Empty string when
        the response is a refusal or a tool call rather than text.
    raw_request, raw_response
        Original wire bytes. Capped at ``raw_byte_cap`` by adapters that
        respect the limit; kept as bytes so binary or partial payloads
        survive.
    timestamp
        Unix epoch float at the moment of capture.
    target_host
        Host portion of the captured URL. Used by adapters and detectors to
        distinguish in-band agent traffic from side-channel (e.g., localhost)
        traffic.
    url
        Full request URL.
    request_method
        HTTP method (``GET``, ``POST``, ...). ``None`` for non-HTTP adapters.
    boundary_proximity
        Score in ``[0.0, 1.0]`` from the session baseline indicating how far
        this turn sits from the established centroid of normal traffic.
        ``None`` until the baseline is established.
    has_system_message
        ``True`` when the captured request contained a ``role: "system"``
        message, ``False`` when it did not, ``None`` when the request shape
        is not a chat-completions message array. Drives the SASTER-33
        structural detector.
    extras
        Adapter-specific extracted fields. Detectors may consult these but
        should not require them.
    """

    session_id: str
    turn_idx: int
    user_message: str = ""
    assistant_response: str = ""
    raw_request: bytes | None = None
    raw_response: bytes | None = None
    timestamp: float = field(default_factory=time.time)
    target_host: str = ""
    url: str = ""
    request_method: str | None = None
    boundary_proximity: float | None = None
    has_system_message: bool | None = None
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass
class DetectionEvent:
    """Structured detection emitted by a SasterDetector.

    Events are JSON-serializable, webhook-deliverable, and self-contained.
    Consumers (alert webhooks, log sinks, dashboards) only need the event
    fields — they should not need to query the harness for additional
    context.

    Attributes
    ----------
    saster_id
        Canonical SASTER pattern identifier, e.g. ``"SASTER-31"``.
    pattern_name
        Canonical human-readable name, e.g. ``"Compositional Capability
        Emergence"``.
    tier
        SASTER tier (1–4). T3 = Epistemic Exploitation, T4 = Infrastructure
        & Recon.
    agent_name
        Identifier of the monitored agent (from
        :attr:`MonitoringConfig.agent_name`).
    session_id, turn_idx, timestamp
        Locator fields, mirrored from the source TurnData.
    evidence
        Detector-defined evidence dict explaining *why* the pattern fired.
        At minimum, detectors should include a ``"signal"`` key with a
        short string code (e.g. ``"regex_match"``, ``"baseline_drift"``)
        and a ``"detail"`` key with the human-readable explanation.
    co_fires_with
        Sibling SASTER pattern IDs that canonically co-occur with this one.
        Sourced from the detector's ``co_fires_with`` class attribute.
    raw_request, raw_response
        Verbatim wire payloads, useful for analyst review. Truncated to
        the adapter's byte cap if it enforces one.
    """

    saster_id: str
    pattern_name: str
    tier: int
    agent_name: str
    session_id: str
    turn_idx: int
    evidence: dict[str, Any]
    co_fires_with: list[str] = field(default_factory=list)
    raw_request: bytes | None = None
    raw_response: bytes | None = None
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        """JSON-serializable dict. ``bytes`` payloads are decoded as UTF-8 with
        replacement so partial/binary captures still survive serialization."""
        d = asdict(self)
        for k in ("raw_request", "raw_response"):
            v = d.get(k)
            if isinstance(v, (bytes, bytearray)):
                d[k] = v.decode("utf-8", errors="replace")
        return d

    def to_json(self, **kwargs: Any) -> str:
        return json.dumps(self.to_dict(), **kwargs)
