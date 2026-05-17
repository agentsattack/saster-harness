"""MonitoringHarness — the public orchestrator.

The harness composes the four moving parts of saster-harness into a single
object the practitioner instantiates and calls :meth:`start` on:

1. A :class:`~saster_harness.adapters.base.BaseAdapter` for wire-protocol
   extraction.
2. A :class:`~saster_harness.baseline.SessionBaseline` for per-session
   embedding drift.
3. A list of :class:`~saster_harness.detector.SasterDetector` instances —
   defaults to the full v0.1 detector set; configurable via
   :attr:`MonitoringConfig.detectors`.
4. A mitmproxy ``DumpMaster`` running the
   :class:`~saster_harness.proxy.HarnessAddon`.

Events emitted by detectors land on three sinks in priority order:

- The local log (always, at ``INFO`` level).
- An in-memory deque accessible via :meth:`recent_events`.
- The configured :attr:`MonitoringConfig.alert_webhook` (if set), via
  background HTTP POST.

The harness API surface is the same in every mode (OBSERVE / PROBE /
INDUCE); the difference is which side-loops the harness runs in addition
to wire capture. v0.1 ships OBSERVE fully; PROBE schedules synthetic
saster-derived prompts every ``probe_interval_hours``; INDUCE is wired but
gated behind an explicit ``allow_induce=True`` flag to prevent surprises.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from collections.abc import Iterable, Iterator
from typing import Any

from .adapters.base import BaseAdapter
from .adapters.http_json import HttpJsonAdapter
from .baseline import SessionBaseline
from .config import HarnessMode, MonitoringConfig
from .detector import SasterDetector
from .event import DetectionEvent
from .proxy import HarnessAddon

logger = logging.getLogger(__name__)


# Default v0.1 detector set, in canonical SASTER-id order. Loaded lazily so
# importing the harness module doesn't pay the cost of importing every
# detector when a practitioner overrides the set.
_DEFAULT_DETECTOR_MODULES: tuple[str, ...] = (
    "saster_harness.detectors.saster_18",
    "saster_harness.detectors.saster_24",
    "saster_harness.detectors.saster_26",
    "saster_harness.detectors.saster_27",
    "saster_harness.detectors.saster_28",
    "saster_harness.detectors.saster_31",
    "saster_harness.detectors.saster_33",
)


class MonitoringHarness:
    """Top-level harness object.

    Parameters
    ----------
    config
        Frozen :class:`MonitoringConfig`. Configuration is taken once at
        construction time; changes after :meth:`start` require a restart.
    adapter
        Wire-protocol adapter. Defaults to :class:`HttpJsonAdapter`.
    detectors
        Override the detector set. ``None`` loads the v0.1 default
        (SASTER-18, -24, -26, -27, -28, -31, -33). Pass an empty list to
        disable all detectors (baseline-only operation).
    allow_induce
        Safety gate for INDUCE mode. Must be ``True`` when
        ``config.mode == HarnessMode.INDUCE`` or :meth:`start` raises.
    event_buffer_size
        Maximum number of recent events to retain in memory for
        :meth:`recent_events` / :meth:`stream`.
    """

    def __init__(
        self,
        config: MonitoringConfig,
        adapter: BaseAdapter | None = None,
        detectors: Iterable[SasterDetector] | None = None,
        *,
        allow_induce: bool = False,
        event_buffer_size: int = 1000,
    ) -> None:
        self._config = config
        self._adapter: BaseAdapter = adapter or HttpJsonAdapter()
        self._detectors: list[SasterDetector] = (
            list(detectors) if detectors is not None else _load_default_detectors()
        )
        self._allow_induce = allow_induce
        self._baseline = SessionBaseline(
            model_name=config.embedding_model,
            baseline_turns=config.baseline_turns,
        )
        self._events: deque[DetectionEvent] = deque(maxlen=event_buffer_size)
        self._events_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._proxy_thread: threading.Thread | None = None
        # Lazily constructed when alert_webhook is set. Typed as Any so the
        # harness can defer the httpx import to the moment the webhook
        # actually fires; httpx is a hard dep at the package level but
        # tolerating a runtime-only attribute keeps the typing simple.
        self._webhook_client: Any = None

    # ----------------------------------------------------------------
    # Public API
    # ----------------------------------------------------------------

    @property
    def config(self) -> MonitoringConfig:
        return self._config

    @property
    def detectors(self) -> list[SasterDetector]:
        return list(self._detectors)

    def start(self, *, block: bool = True) -> None:
        """Start wire capture and any mode-specific side-loops.

        Parameters
        ----------
        block
            If ``True`` (the default for the slide-18 example), call blocks
            until ``Ctrl-C`` (SIGINT) or :meth:`stop`. If ``False``, returns
            immediately after the proxy thread is up; the caller is
            responsible for keeping the process alive.
        """
        if self._config.mode == HarnessMode.INDUCE and not self._allow_induce:
            raise RuntimeError(
                "INDUCE mode requires allow_induce=True at construction time. "
                "INDUCE generates active adversarial probes against the monitored "
                "agent — only enable in staging environments under direct supervision."
            )
        logger.info(
            "Starting saster-harness for agent=%s in %s mode on :%d",
            self._config.agent_name,
            self._config.mode.value,
            self._config.listen_port,
        )

        addon = HarnessAddon(
            adapter=self._adapter,
            detectors=self._detectors,
            baseline=self._baseline,
            sink=self._handle_event,
            agent_name=self._config.agent_name,
        )

        self._proxy_thread = threading.Thread(
            target=self._run_proxy,
            name="saster-harness-proxy",
            args=(addon,),
            daemon=True,
        )
        self._proxy_thread.start()

        if self._config.mode == HarnessMode.PROBE and self._config.probe_interval_hours > 0:
            self._start_probe_scheduler()

        if block:
            try:
                self._stop_event.wait()
            except KeyboardInterrupt:
                logger.info("SIGINT received — shutting down.")
            finally:
                self.stop()

    def stop(self) -> None:
        """Signal the harness to shut down. Safe to call multiple times."""
        if self._stop_event.is_set():
            return
        self._stop_event.set()
        logger.info("Harness stop signal sent.")
        # mitmproxy DumpMaster shutdown is initiated from within
        # _run_proxy via the stop event; the thread cleans up itself.

    def recent_events(self, limit: int = 50) -> list[DetectionEvent]:
        """Return the most recent N detection events from the in-memory buffer."""
        with self._events_lock:
            return list(self._events)[-limit:]

    def stream(self) -> Iterator[DetectionEvent]:
        """Yield events as they arrive. Blocks; consumes the live event
        stream. Intended for test harnesses and integrations that prefer
        pull over the webhook push model."""
        # Simple polling iterator; v0.1 keeps it pull-based to avoid the
        # complexity of a producer-consumer queue across threads. v0.2
        # will switch to ``asyncio.Queue`` once the harness goes async.
        last_len = 0
        while not self._stop_event.is_set():
            with self._events_lock:
                snapshot = list(self._events)
            if len(snapshot) > last_len:
                yield from snapshot[last_len:]
                last_len = len(snapshot)
            self._stop_event.wait(timeout=0.5)

    # ----------------------------------------------------------------
    # Internals
    # ----------------------------------------------------------------

    def _run_proxy(self, addon: HarnessAddon) -> None:
        """Run the embedded mitmproxy DumpMaster until ``self._stop_event``
        is set."""
        import asyncio

        from mitmproxy.options import Options
        from mitmproxy.tools.dump import DumpMaster

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        opts = Options(
            listen_host="127.0.0.1",
            listen_port=self._config.listen_port,
            ssl_insecure=True,
        )
        master = DumpMaster(opts, with_termlog=False, with_dumper=False)
        master.addons.add(addon)
        loop.create_task(_shutdown_when_stopped(master, self._stop_event))
        try:
            loop.run_until_complete(master.run())
        except Exception:  # pragma: no cover
            logger.exception("mitmproxy DumpMaster failed")
        finally:
            loop.close()

    def _handle_event(self, event: DetectionEvent) -> None:
        with self._events_lock:
            self._events.append(event)
        logger.info(
            "DETECTION %s · %s · T%d · session=%s turn=%d",
            event.saster_id,
            event.pattern_name,
            event.tier,
            event.session_id[:12],
            event.turn_idx,
        )
        if self._config.alert_webhook:
            self._dispatch_webhook(event)

    def _dispatch_webhook(self, event: DetectionEvent) -> None:
        """Fire-and-forget POST. Failures are logged but do not raise — a
        broken Slack URL must not take down the proxy pipeline."""
        try:
            import httpx
        except ImportError:  # pragma: no cover — httpx is a hard dep
            logger.error("httpx not available; cannot dispatch alert webhook.")
            return
        try:
            if self._webhook_client is None:
                self._webhook_client = httpx.Client(timeout=3.0)
            self._webhook_client.post(
                self._config.alert_webhook,
                json=event.to_dict(),
            )
        except Exception:
            logger.exception("Alert webhook POST failed")

    def _start_probe_scheduler(self) -> None:
        """v0.2 work — schedules probes derived from SASTER pattern
        definitions every ``probe_interval_hours``. For v0.1 this is
        a logged no-op so PROBE mode behaves identically to OBSERVE
        rather than silently failing."""
        logger.warning(
            "PROBE mode scheduler is a v0.2 feature; running as OBSERVE in v0.1."
        )


async def _shutdown_when_stopped(master: object, stop_event: threading.Event) -> None:
    """Translate the thread-safe stop_event into an asyncio shutdown of the
    mitmproxy master. Polls on a short interval — adequate because shutdown
    is rare and not latency-sensitive."""
    import asyncio

    while not stop_event.is_set():
        await asyncio.sleep(0.2)
    try:
        master.shutdown()  # type: ignore[attr-defined]
    except Exception:  # pragma: no cover
        logger.exception("DumpMaster shutdown failed")


def _load_default_detectors() -> list[SasterDetector]:
    """Import and instantiate each detector module in the default set.

    Detector modules expose their detector class via a module-level
    ``DETECTOR`` attribute. Modules whose detector raises ``NotImplementedError``
    at construction time are skipped with a warning, so a partially shipped
    detector set still produces a working harness (the user just won't see
    that pattern fire)."""
    import importlib

    out: list[SasterDetector] = []
    for mod_name in _DEFAULT_DETECTOR_MODULES:
        try:
            mod = importlib.import_module(mod_name)
        except ImportError as exc:
            logger.warning("Skipping %s — import failed: %s", mod_name, exc)
            continue
        detector_obj = getattr(mod, "DETECTOR", None)
        if detector_obj is None:
            logger.warning("Skipping %s — no module-level DETECTOR attribute", mod_name)
            continue
        out.append(detector_obj)
    return out
