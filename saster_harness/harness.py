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


# Registry: SASTER-id (with optional mode suffix) → list of detector
# module paths. v0.1 ships 9 detector implementations covering 7
# SASTER patterns; SASTER-18 and SASTER-24 each ship both passive and
# induced variants.
#
# Identifiers:
#   "SASTER-XX"          — passive detector (always available)
#   "SASTER-XX-induced"  — induced detector (active probing)
#   "SASTER-XX-both"     — convenience: loads passive + induced
_DETECTOR_REGISTRY: dict[str, tuple[str, ...]] = {
    # Passive
    "SASTER-18": ("saster_harness.detectors.saster_18",),
    "SASTER-24": ("saster_harness.detectors.saster_24",),
    "SASTER-26": ("saster_harness.detectors.saster_26",),
    "SASTER-27": ("saster_harness.detectors.saster_27",),
    "SASTER-28": ("saster_harness.detectors.saster_28",),
    "SASTER-31": ("saster_harness.detectors.saster_31",),
    "SASTER-33": ("saster_harness.detectors.saster_33",),
    # Induced
    "SASTER-18-induced": ("saster_harness.detectors.saster_18_induced",),
    "SASTER-24-induced": ("saster_harness.detectors.saster_24_induced",),
    # Both
    "SASTER-18-both": (
        "saster_harness.detectors.saster_18",
        "saster_harness.detectors.saster_18_induced",
    ),
    "SASTER-24-both": (
        "saster_harness.detectors.saster_24",
        "saster_harness.detectors.saster_24_induced",
    ),
}

# Default-when-not-specified: all 9 implementations. SASTER-18 and
# SASTER-24 use the ``-both`` shortcut so both flavours load; the
# five other passive patterns load directly.
_DEFAULT_ENABLED_DETECTORS: tuple[str, ...] = (
    "SASTER-18-both",
    "SASTER-24-both",
    "SASTER-26",
    "SASTER-27",
    "SASTER-28",
    "SASTER-31",
    "SASTER-33",
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
        Override the detector set with pre-constructed instances.
        ``None`` (the default) loads the registry-driven default per
        :attr:`MonitoringConfig.enabled_detectors` — all 9
        implementations spanning 7 SASTER patterns. Pass an empty
        list to disable all detectors (baseline-only operation).
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
        # Build a shared sentence-transformer embedder used by both the
        # session baseline and any induced detectors. One model per
        # process — eliminates the ~5–15 s double-load cold-start
        # penalty and halves the steady-state RAM footprint when both
        # paths are active.
        from .embedding import build_shared_embedder
        self._shared_embedder = build_shared_embedder(config.embedding_model)
        self._detectors: list[SasterDetector] = (
            list(detectors)
            if detectors is not None
            else _load_default_detectors(config.enabled_detectors)
        )
        # Inject the shared embedder into every induced detector that
        # supports it. Detectors that don't expose set_embedder (the
        # passive ones) are unaffected.
        for detector in self._detectors:
            setter = getattr(detector, "set_embedder", None)
            if callable(setter):
                setter(self._shared_embedder)
        self._allow_induce = allow_induce
        self._baseline = SessionBaseline(
            model_name=config.embedding_model,
            baseline_turns=config.baseline_turns,
            embedder=self._shared_embedder,
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


def _load_default_detectors(
    enabled: list[str] | None = None,
) -> list[SasterDetector]:
    """Load detectors per ``enabled`` from the registry.

    ``enabled`` is a list of SASTER identifiers — plain
    (``"SASTER-18"``), ``-induced``, or ``-both``. ``None`` loads the
    default v0.1 set (all 9 implementations). Unknown identifiers
    raise :class:`ValueError`; module-import failures log a warning
    and skip that detector rather than aborting the harness.

    Each module exposes its detector class via a module-level
    ``DETECTOR`` attribute (instance, not class) — the registry
    expands a single identifier into one or more module paths and
    this loader assembles the resulting detector instances."""
    import importlib

    identifiers = list(enabled) if enabled is not None else list(_DEFAULT_ENABLED_DETECTORS)
    unknown = [ident for ident in identifiers if ident not in _DETECTOR_REGISTRY]
    if unknown:
        raise ValueError(
            f"Unknown detector identifier(s): {unknown}. Accepted: "
            f"{sorted(_DETECTOR_REGISTRY)}."
        )

    # Deduplicate module paths (``SASTER-18-both`` and ``SASTER-18``
    # both pull the passive module) while preserving order so the
    # detector list ends up in the canonical SASTER-id order practitioners
    # expect from logs and reports.
    seen_modules: set[str] = set()
    ordered_modules: list[str] = []
    for ident in identifiers:
        for mod_name in _DETECTOR_REGISTRY[ident]:
            if mod_name not in seen_modules:
                seen_modules.add(mod_name)
                ordered_modules.append(mod_name)

    out: list[SasterDetector] = []
    for mod_name in ordered_modules:
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
