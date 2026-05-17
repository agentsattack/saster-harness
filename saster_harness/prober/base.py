"""Prober — coordinator for active-injection induction-mode detection.

The Prober class abstracts how a synthetic probe turn reaches an agent.
Three responsibilities:

1. :meth:`inject_turn` — push a single user message into a session via
   the configured :class:`InjectorBackend` and return the agent's
   response wrapped in a :class:`ProbeRecord`.

2. :meth:`establish_baseline` — record the agent's baseline response
   to a reference prompt. Induction detectors compare every subsequent
   reframed response against this baseline; the comparison only
   makes sense if the baseline itself is a clear refusal.

3. :meth:`session_lock` — context manager that prevents real user
   turns from interleaving with probe turns. v0.1 ships a no-op
   implementation that delegates to ``backend.lock_session`` when
   present; v0.2 will wire adapter-specific lock semantics for the
   HTTP and OpenAI-Assistant paths.

The Prober is agnostic to which detector invokes it. Detector code
calls into a Prober that is passed in at probe time; the Prober does
not know about detectors.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class InjectorBackend(Protocol):
    """Adapter-specific injection strategy.

    Implementations decide how a probe turn reaches the agent —
    direct in-process call, HTTP POST, message queue, etc. The
    contract is intentionally narrow: take a session id + content,
    return the assistant's response text synchronously.

    Implementations MAY additionally expose a ``lock_session`` method
    returning a context manager. When present, :meth:`Prober.session_lock`
    delegates to it; when absent, the lock is a no-op.
    """

    def send(self, session_id: str, content: str) -> str:
        """Send a user turn into ``session_id`` and return the
        assistant's response. Raises on transport failure."""
        ...


@dataclass
class ProbeRecord:
    """One probe round: the prompt sent and the response captured.

    Detectors consume :class:`ProbeRecord` instances when computing
    divergence; the runtime-stable fields are ``content``,
    ``response``, and ``session_id``. ``turn_id`` is a Prober-internal
    correlation id and may change between runs."""

    session_id: str
    turn_id: str
    content: str
    response: str
    timestamp: float


class Prober:
    """Inject-and-capture coordinator for induction-mode detectors."""

    def __init__(self, backend: InjectorBackend) -> None:
        self._backend = backend
        self._baselines: dict[str, ProbeRecord] = {}
        self._lock = threading.Lock()

    # ----------------------------------------------------------------
    # Public API
    # ----------------------------------------------------------------

    def inject_turn(self, session_id: str, content: str) -> ProbeRecord:
        """Send ``content`` as a user turn into ``session_id`` and
        return a :class:`ProbeRecord` capturing the response."""
        turn_id = str(uuid.uuid4())[:8]
        logger.debug(
            "prober: inject session=%s turn=%s content=%r",
            session_id, turn_id, content[:80],
        )
        response = self._backend.send(session_id, content)
        return ProbeRecord(
            session_id=session_id,
            turn_id=turn_id,
            content=content,
            response=response,
            timestamp=time.time(),
        )

    def establish_baseline(self, session_id: str, prompt: str) -> ProbeRecord:
        """Inject ``prompt`` into ``session_id`` and record the
        response as the session's baseline. Subsequent
        :meth:`get_baseline` calls return this record; subsequent
        :meth:`establish_baseline` calls overwrite it."""
        record = self.inject_turn(session_id, prompt)
        with self._lock:
            self._baselines[session_id] = record
        return record

    def get_baseline(self, session_id: str) -> ProbeRecord | None:
        """Return the recorded baseline for ``session_id`` or ``None``
        if none has been established."""
        with self._lock:
            return self._baselines.get(session_id)

    def capture_response(
        self,
        session_id: str,
        turn_id: str,
        timeout: float = 30.0,
    ) -> str | None:
        """v0.1: returns ``None`` — :meth:`inject_turn` is synchronous,
        so responses are captured at injection time. The method is
        retained as an API-forward-compatibility hook; v0.2 wires it
        load-bearing for asynchronous backends."""
        del session_id, turn_id, timeout
        return None

    @contextmanager
    def session_lock(self, session_id: str) -> Iterator[None]:
        """Prevent real user turns from interleaving with probe turns
        in ``session_id``.

        v0.1 delegates to the backend's ``lock_session`` method when
        present; otherwise no-op. Custom backends implementing
        ``lock_session(session_id) -> ContextManager`` get adapter-
        appropriate locking out of the box.
        """
        lock_fn = getattr(self._backend, "lock_session", None)
        if callable(lock_fn):
            with lock_fn(session_id):
                yield
        else:
            yield

    # ----------------------------------------------------------------
    # Lifecycle
    # ----------------------------------------------------------------

    def reset(self, session_id: str | None = None) -> None:
        """Drop the baseline for one session, or all sessions when
        ``session_id`` is ``None``."""
        with self._lock:
            if session_id is None:
                self._baselines.clear()
            else:
                self._baselines.pop(session_id, None)
