"""Wire-capture proxy — mitmproxy addon that bridges captured flows to the harness.

This module exposes a single class, :class:`HarnessAddon`, which mitmproxy
loads as an addon. The addon receives every HTTP/HTTPS flow that passes
through, calls the registered adapter to build a :class:`TurnData`, scores
the turn against the session baseline, runs the registered detectors, and
emits :class:`DetectionEvent` instances to the harness sink.

There are two ways to run the proxy:

- **Embedded** (recommended for ``MonitoringHarness.start()``): the harness
  instantiates :class:`HarnessAddon` and registers it with an in-process
  ``mitmproxy.tools.dump.DumpMaster``. Everything runs in a single Python
  process; ``Ctrl-C`` stops both.
- **Out-of-process**: use the CLI entrypoint::

      mitmdump -s -m saster_harness.proxy:HarnessAddon -p 8888

  This is useful for advanced deployments that want mitmproxy under
  systemd / supervisord control.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Iterable
from typing import Any

from .adapters.base import BaseAdapter
from .baseline import SessionBaseline
from .detector import SasterDetector
from .event import DetectionEvent, TurnData

logger = logging.getLogger(__name__)


EventSink = Callable[[DetectionEvent], None]


class HarnessAddon:
    """mitmproxy addon that runs the saster-harness pipeline.

    The class is intentionally framework-light: it owns a list of detectors,
    a session baseline, an adapter, and an event sink. Lifecycle is managed
    by mitmproxy (``running``, ``done`` hooks) or by the embedding harness.
    """

    def __init__(
        self,
        *,
        adapter: BaseAdapter,
        detectors: Iterable[SasterDetector],
        baseline: SessionBaseline,
        sink: EventSink,
        agent_name: str,
    ) -> None:
        self._adapter = adapter
        self._detectors = list(detectors)
        self._baseline = baseline
        self._sink = sink
        self._agent_name = agent_name
        self._turn_counters: dict[str, int] = {}

    # ----------------------------------------------------------------
    # mitmproxy lifecycle hooks
    # ----------------------------------------------------------------

    async def running(self) -> None:
        logger.info(
            "saster-harness addon running — agent=%s detectors=%d",
            self._agent_name,
            len(self._detectors),
        )
        # Warm the baseline in the background — first model load can take
        # 5–15 s and we don't want the first captured flow to block on it.
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._baseline.warm)

    async def response(self, flow: Any) -> None:  # noqa: ANN401 — mitmproxy types
        """Main hook: called once per request/response cycle."""
        try:
            self._process_flow(flow)
        except Exception:  # pragma: no cover — defensive, never let the proxy crash
            logger.exception("Error processing flow %s", getattr(flow.request, "url", "?"))

    async def done(self) -> None:
        logger.info("saster-harness addon shutting down.")

    # ----------------------------------------------------------------
    # Core pipeline
    # ----------------------------------------------------------------

    def _process_flow(self, flow: Any) -> None:
        request = flow.request
        response = flow.response
        if response is None:
            return
        turn = self._adapter.extract(
            url=request.url,
            method=request.method,
            request_headers=dict(request.headers),
            request_body=request.content or b"",
            response_headers=dict(response.headers),
            response_body=response.content or b"",
        )
        if turn is None:
            return

        turn.turn_idx = self._turn_counters.get(turn.session_id, 0)
        self._turn_counters[turn.session_id] = turn.turn_idx + 1

        turn.boundary_proximity = self._baseline.observe(
            turn.session_id, turn.user_message or turn.assistant_response or ""
        )

        self._run_detectors(turn)

    def _run_detectors(self, turn: TurnData) -> None:
        for detector in self._detectors:
            if detector.needs_baseline() and not self._baseline.is_established(turn.session_id):
                continue
            try:
                event = detector.evaluate(turn)
            except NotImplementedError:
                # Detector stubs raise NotImplementedError until they ship
                # — skip rather than crash the proxy. v0.1.0 ships only
                # implemented detectors; this guards local dev branches.
                continue
            except Exception:  # pragma: no cover
                logger.exception(
                    "Detector %s crashed on turn %s/%d",
                    detector.saster_id,
                    turn.session_id,
                    turn.turn_idx,
                )
                continue
            if event is not None:
                # Detectors that subclass _build_event already populate
                # agent_name. Detectors that build events manually may
                # not — backfill defensively.
                if not event.agent_name:
                    event.agent_name = self._agent_name
                self._sink(event)
