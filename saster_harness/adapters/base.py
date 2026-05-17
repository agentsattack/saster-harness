"""BaseAdapter — protocol-specific extractor interface.

An adapter takes a captured flow (request + response + metadata) and produces
a :class:`~saster_harness.event.TurnData`. Adapters decide:

- whether the captured flow is one this adapter handles (return ``None`` if not)
- how to derive the session identifier from headers, cookies, or body fields
- how to extract user and assistant messages from protocol-specific shapes
- whether the request carried the structural elements detectors care about
  (e.g. a ``role: "system"`` message for the SASTER-33 baseline)

The harness tries each registered adapter in order; the first one that
returns a non-``None`` :class:`TurnData` wins.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ..event import TurnData


class BaseAdapter(ABC):
    """Wire-protocol adapter interface.

    Implementations are stateless: a single adapter instance handles all
    captured flows. Per-session state (counters, baselines) lives in the
    harness, not the adapter.
    """

    @abstractmethod
    def extract(
        self,
        url: str,
        method: str,
        request_headers: dict[str, str],
        request_body: bytes,
        response_headers: dict[str, str],
        response_body: bytes,
    ) -> TurnData | None:
        """Build a TurnData from one captured request/response pair.

        Return ``None`` when the flow does not match this adapter's
        protocol (the harness will try the next adapter).
        """

    # ----------------------------------------------------------------
    # Optional helpers commonly needed by subclasses
    # ----------------------------------------------------------------

    @staticmethod
    def _safe_json(body: bytes) -> dict[str, Any] | None:
        if not body:
            return None
        try:
            import json

            decoded = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return None
        return decoded if isinstance(decoded, dict) else None
