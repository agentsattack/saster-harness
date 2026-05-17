"""Adapters translate raw wire bytes into :class:`~saster_harness.event.TurnData`.

The harness is wire-protocol-agnostic; adapters handle the protocol-specific
extraction. v0.1 ships two adapters:

- :class:`HttpJsonAdapter` — OpenAI-style JSON chat completion traffic
  captured live through mitmproxy.
- :class:`HARAdapter` — Chrome / Firefox HAR file import for offline
  audit of browser-accessible agents (no MITM required).

Custom adapters (gRPC, MCP, server-sent events) should subclass
:class:`BaseAdapter`.
"""

from __future__ import annotations

from .base import BaseAdapter
from .har_adapter import HARAdapter
from .http_json import HttpJsonAdapter

__all__ = ["BaseAdapter", "HARAdapter", "HttpJsonAdapter"]
