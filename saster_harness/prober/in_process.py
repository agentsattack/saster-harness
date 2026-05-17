"""InProcessInjector — direct-call injection backend.

Used by:

- The test suite, where a scripted send function returns deterministic
  responses for unit testing induction detectors.
- In-process scenarios where the agent is callable from the same
  Python process (no HTTP involved), such as the bundled Carl
  scenarios when extended with induced patterns.

Constructor takes a callable ``(session_id, content) -> response``.
The Prober calls it through the :class:`InjectorBackend` protocol.
"""

from __future__ import annotations

from collections.abc import Callable


class InProcessInjector:
    """Direct-call injection backend.

    Parameters
    ----------
    send_fn
        Callable invoked as ``send_fn(session_id, content)`` for each
        probe turn. Returns the assistant's response string.
    """

    def __init__(self, send_fn: Callable[[str, str], str]) -> None:
        self._send_fn = send_fn

    def send(self, session_id: str, content: str) -> str:
        return self._send_fn(session_id, content)
