"""Adapters translate raw wire bytes into :class:`~saster_harness.event.TurnData`.

The harness is wire-protocol-agnostic; adapters handle the protocol-specific
extraction. v0.1 ships :class:`HttpJsonAdapter` for OpenAI-style JSON chat
completions. Custom adapters (gRPC, MCP, server-sent events) should subclass
:class:`BaseAdapter`.
"""

from __future__ import annotations

from .base import BaseAdapter
from .http_json import HttpJsonAdapter

__all__ = ["BaseAdapter", "HttpJsonAdapter"]
