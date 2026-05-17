"""Prober subsystem — active-injection induction-mode detection.

Public API:

- :class:`Prober` — orchestrator. Construct with an injection
  backend, then call :meth:`Prober.establish_baseline` and
  :meth:`Prober.inject_turn` to drive a probe cycle.
- :class:`InjectorBackend` — protocol for custom injection
  strategies. Backends that additionally expose ``lock_session``
  get adapter-appropriate session locking via
  :meth:`Prober.session_lock`.
- :class:`InProcessInjector` — direct-call backend for tests and
  in-process scenarios.
- :class:`HttpInjector` — production backend for OpenAI-style
  chat completion endpoints.
- :class:`ProbeRecord` — data class for one probe round.
"""

from __future__ import annotations

from .base import InjectorBackend, Prober, ProbeRecord
from .http import HttpInjector
from .in_process import InProcessInjector

__all__ = [
    "HttpInjector",
    "InjectorBackend",
    "InProcessInjector",
    "ProbeRecord",
    "Prober",
]
