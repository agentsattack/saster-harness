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
from collections.abc import Iterable, Iterator, Sequence
from typing import Any

from .adapters.base import BaseAdapter
from .adapters.http_json import HttpJsonAdapter
from .baseline import (
    EmbeddingBaseline,
    ObservedToolCallMix,
    SessionBaseline,
    TrainedRefusalBaseline,
)
from .config import HarnessMode, MonitoringConfig
from .detector import SasterDetector
from .detectors.base_induction import (
    MultiTurnInductionDetector,
    SingleTurnInductionDetector,
)
from .drift import DriftAccumulator, SusceptibilityCache, parse_host
from .event import DetectionEvent, TurnData
from .persistence import PersistenceStore
from .prober import HttpInjector, Prober
from .proxy import HarnessAddon
from .refusal_sampler import CalibrationReceipt, RefusalSampler
from .scheduler import ProbeScheduler

logger = logging.getLogger(__name__)


# Registry: SASTER-id (with optional mode suffix) → list of detector
# module paths. v0.1 shipped 9 detector implementations covering 7
# SASTER patterns; SASTER-18 and SASTER-24 each shipped both passive
# and induced variants. v0.3.2 adds SASTER-18-multiturn.
#
# Identifiers:
#   "SASTER-XX"            — passive detector (always available)
#   "SASTER-XX-induced"    — induced detector (active single-turn probing)
#   "SASTER-XX-multiturn"  — multi-turn induced detector (Crescendo shape)
#   "SASTER-XX-both"       — convenience: loads passive + induced
#   "SASTER-XX-all"        — convenience: loads passive + induced + multiturn
#                            (where every flavour exists)
#
# Practitioners register custom detector modules under their own ids via
# :func:`register_detector` (string id + dotted module path) or
# :func:`register_detector_instance` (string id + pre-built instance).
_DETECTOR_REGISTRY: dict[str, tuple[str, ...]] = {
    # Passive
    "SASTER-18": ("saster_harness.detectors.saster_18",),
    "SASTER-24": ("saster_harness.detectors.saster_24",),
    "SASTER-26": ("saster_harness.detectors.saster_26",),
    "SASTER-27": ("saster_harness.detectors.saster_27",),
    "SASTER-28": ("saster_harness.detectors.saster_28",),
    "SASTER-31": ("saster_harness.detectors.saster_31",),
    "SASTER-33": ("saster_harness.detectors.saster_33",),
    # Induced (single-turn)
    "SASTER-13-induced": ("saster_harness.detectors.saster_13_induced",),
    "SASTER-15-induced": ("saster_harness.detectors.saster_15_induced",),
    "SASTER-18-induced": ("saster_harness.detectors.saster_18_induced",),
    "SASTER-24-induced": ("saster_harness.detectors.saster_24_induced",),
    "SASTER-26-induced": ("saster_harness.detectors.saster_26_induced",),
    # Induced (multi-turn / Crescendo)
    "SASTER-18-multiturn": ("saster_harness.detectors.saster_18_multiturn",),
    # Both
    "SASTER-13-both": (
        # No passive SASTER-13 ships in v0.2; -both shortcut is
        # forward-compatible.
        "saster_harness.detectors.saster_13_induced",
    ),
    "SASTER-15-both": (
        # No passive SASTER-15 ships in v0.2; -both shortcut is
        # forward-compatible — when the passive detector ships in a
        # future release the registry entry expands.
        "saster_harness.detectors.saster_15_induced",
    ),
    "SASTER-18-both": (
        "saster_harness.detectors.saster_18",
        "saster_harness.detectors.saster_18_induced",
    ),
    "SASTER-24-both": (
        "saster_harness.detectors.saster_24",
        "saster_harness.detectors.saster_24_induced",
    ),
    "SASTER-26-both": (
        "saster_harness.detectors.saster_26",
        "saster_harness.detectors.saster_26_induced",
    ),
    # All — passive + induced + multiturn (where every flavour exists).
    # Only SASTER-18 has all three in v0.3.2; the shortcut is forward-
    # compatible for other patterns gaining multi-turn variants later.
    "SASTER-18-all": (
        "saster_harness.detectors.saster_18",
        "saster_harness.detectors.saster_18_induced",
        "saster_harness.detectors.saster_18_multiturn",
    ),
}

# Parallel registry for pre-built detector instances (rather than module
# paths). Checked first by :func:`_load_default_detectors` — when a
# saster_id appears in both registries, the instance wins. Used by
# :func:`register_detector_instance` so practitioners can plug in a
# fully-constructed detector (custom config, mocked dependencies, …)
# without needing to expose a module-level ``DETECTOR`` attribute.
_DETECTOR_INSTANCE_REGISTRY: dict[str, SasterDetector] = {}


def register_detector(saster_id: str, *module_paths: str) -> None:
    """Register a custom detector module under ``saster_id``.

    After registration the id is loadable via
    :attr:`MonitoringConfig.enabled_detectors` like any shipped
    detector. Each module path must point at a module exposing a
    module-level ``DETECTOR`` attribute (an instance, not a class) —
    the same convention the shipped detectors follow.

    Re-registering an existing id replaces the previous entry. To
    register a pre-built instance instead of a module path, use
    :func:`register_detector_instance`.

    Examples
    --------
    >>> register_detector("MY-PATTERN-1", "mypkg.detectors.my_pattern")
    >>> config = MonitoringConfig(..., enabled_detectors=["MY-PATTERN-1"])
    """
    if not isinstance(saster_id, str) or not saster_id.strip():
        raise ValueError("saster_id must be a non-empty string")
    if not module_paths:
        raise ValueError(
            "at least one module path is required when registering a detector"
        )
    for path in module_paths:
        if not isinstance(path, str) or not path.strip():
            raise ValueError("detector module paths must be non-empty strings")
    _DETECTOR_REGISTRY[saster_id] = tuple(module_paths)


def register_detector_instance(
    saster_id: str, detector: SasterDetector,
) -> None:
    """Register a pre-built detector instance under ``saster_id``.

    Use this when the detector needs constructor arguments (custom
    threshold, mocked embedder, dependency-injected resources) that
    can't be supplied by a module-level ``DETECTOR`` attribute. After
    registration the id is loadable via
    :attr:`MonitoringConfig.enabled_detectors` like any shipped detector.

    When the same id is registered via both this function and
    :func:`register_detector`, the instance wins.
    """
    if not isinstance(saster_id, str) or not saster_id.strip():
        raise ValueError("saster_id must be a non-empty string")
    if not isinstance(detector, SasterDetector):
        raise TypeError(
            "detector must be a SasterDetector instance "
            f"(got {type(detector).__name__})"
        )
    _DETECTOR_INSTANCE_REGISTRY[saster_id] = detector


def registered_detector_ids() -> tuple[str, ...]:
    """Return every currently-registered detector id, sorted. Includes
    both shipped detectors and any added via :func:`register_detector`
    or :func:`register_detector_instance`."""
    return tuple(sorted(set(_DETECTOR_REGISTRY) | set(_DETECTOR_INSTANCE_REGISTRY)))

# Default-when-not-specified: all 9 implementations. SASTER-18 and
# SASTER-24 use the ``-both`` shortcut so both flavours load; the
# five other passive patterns load directly.
_DEFAULT_ENABLED_DETECTORS: tuple[str, ...] = (
    "SASTER-13-induced",
    "SASTER-15-induced",
    "SASTER-18-both",
    "SASTER-24-both",
    "SASTER-26-both",
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
        prober: Prober | None = None,
    ) -> None:
        self._config = config
        self._adapter: BaseAdapter = adapter or HttpJsonAdapter()
        # Optional Prober for active-injection paths (boot-time refusal
        # sampling, PROBE-mode scheduler, demo-time induce calls). When
        # the operator does not supply one, the harness constructs an
        # HttpInjector against ``config.agent_endpoint`` only at the
        # moment it is actually needed — we do not want to open the
        # client just because the operator instantiated the harness.
        self._prober: Prober | None = prober
        self._composite_baseline: SessionBaseline | None = None
        self._calibration_receipt: CalibrationReceipt | None = None
        self._susceptibility_cache = SusceptibilityCache()
        self._drift: DriftAccumulator | None = None
        self._probe_scheduler: ProbeScheduler | None = None
        self._probe_thread: threading.Thread | None = None
        self._store: PersistenceStore | None = (
            PersistenceStore(
                state_dir=self._config.state_dir,
                agent_name=self._config.agent_name,
            )
            if self._config.state_dir is not None
            else None
        )
        self._turns_since_snapshot = 0
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

        # Distribute the operator's declared authorized-tool allow-list
        # (Source 1: DECLARED) to every detector that consumes it.
        # SasterDetector.set_authorized_tools is a no-op on the base
        # class; Saster13InducedDetector and future allow-list-aware
        # detectors override.
        authorized = tuple(self._config.authorized_tools)
        for detector in self._detectors:
            detector.set_authorized_tools(authorized)

        # Distribute operator-supplied extra reframings (single-turn)
        # and extra ramps (multi-turn) into matching detectors. Keys
        # that don't match any loaded detector log a WARNING rather
        # than raising — practitioners commonly leave entries in place
        # while toggling enabled_detectors and we don't want a stale
        # extras key to take the harness down.
        self._apply_extra_reframings(self._config.extra_reframings)
        self._apply_extra_turn_sequences(self._config.extra_turn_sequences)
        self._allow_induce = allow_induce
        self._baseline = EmbeddingBaseline(
            model_name=config.embedding_model,
            baseline_turns=config.baseline_turns,
            baseline_hours=config.baseline_hours,
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
        # Bounded thread pool for webhook dispatch — v0.3 fix making the
        # proxy thread no longer block on webhook POSTs. max_workers=2 is
        # plenty for the typical low-volume alert traffic and keeps the
        # thread count predictable on long-running deployments. Lazy
        # construction: only spawned when ``alert_webhook`` is set.
        self._webhook_executor: Any = None

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

        # Restore persisted state before any boot-time work runs so
        # the refusal sampler etc. see prior state when present.
        if self._store is not None:
            self._store.load_centroids(self._baseline)
            self._store.load_structural(self._detectors)

        # Boot-time refusal sampling (Source 2: TRAINED). Builds the
        # trained refusal centroid before the proxy starts so the first
        # captured flow can score against it. Failures degrade
        # gracefully to corpus-only behavior.
        trained = self._build_trained_baseline()
        if self._store is not None and self._calibration_receipt is not None:
            self._store.write_calibration_receipt(self._calibration_receipt)
        self._composite_baseline = SessionBaseline(
            declared=tuple(self._config.authorized_tools),
            trained=trained,
            observed=self._baseline,
            tool_call_mix=ObservedToolCallMix(window_hours=24.0),
        )
        # Push the trained centroid into SASTER-18-induced so its
        # corpus-distance signal uses the agent-sampled centroid
        # instead of lazy-computing from the bundled corpus on first
        # scoring call.
        if trained.is_available():
            for detector in self._detectors:
                setter = getattr(detector, "set_refusal_centroid", None)
                if callable(setter):
                    setter(trained.centroid)

        # DriftAccumulator — computes the four-signal composite per turn
        # and emits SASTER-DRIFT-COMPOSITE / SASTER-AUTONOMOUS-ESCALATION
        # synthetic events through the same sink the proxy uses.
        self._drift = DriftAccumulator(
            baseline=self._composite_baseline,
            max_drift_score=self._config.max_drift_score,
            max_autonomous_hits=self._config.max_autonomous_hits,
            embedder=self._shared_embedder,
            susceptibility_cache=self._susceptibility_cache,
            agent_endpoint_host=parse_host(self._config.agent_endpoint),
            sink=self._handle_event,
            agent_name=self._config.agent_name,
            weight_unauthorized=self._config.drift_weight_unauthorized,
            weight_refusal_change=self._config.drift_weight_refusal_change,
            weight_behavioral=self._config.drift_weight_behavioral,
            weight_susceptibility=self._config.drift_weight_susceptibility,
        )

        addon = HarnessAddon(
            adapter=self._adapter,
            detectors=self._detectors,
            baseline=self._baseline,
            sink=self._handle_event,
            agent_name=self._config.agent_name,
            turn_sink=self._handle_turn,
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
        # Final snapshot before exit so the next start() restores fully.
        if self._store is not None:
            try:
                self._store.snapshot(self._baseline, self._detectors)
            except Exception:  # pragma: no cover — defensive
                logger.exception("Final snapshot failed")
        # Drain pending webhook POSTs with a short wait so events already
        # in the queue have a chance to land before the executor closes.
        # Bounded shutdown — we don't want stop() to block indefinitely
        # if the webhook endpoint is hung.
        if self._webhook_executor is not None:
            try:
                self._webhook_executor.shutdown(wait=False, cancel_futures=False)
            except Exception:  # pragma: no cover — defensive
                logger.exception("Webhook executor shutdown failed")
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
        is set.

        v0.3.2 surfaces ``listen_host``, ``ssl_insecure``,
        ``upstream_proxy``, and an ``mitm_options`` escape hatch from
        :class:`MonitoringConfig`. The harness-managed keys are passed
        explicitly; any conflicting key in ``mitm_options`` raises
        :class:`ValueError` at start time so the operator gets a clear
        signal rather than silent override surprise."""
        import asyncio

        from mitmproxy.options import Options
        from mitmproxy.tools.dump import DumpMaster

        if self._config.listen_host != "127.0.0.1":
            logger.warning(
                "listen_host=%r — proxy will accept connections on a "
                "non-loopback interface. The mitmproxy CA intercepts TLS "
                "for everything passing through; restrict access at the "
                "network layer.", self._config.listen_host,
            )

        managed_keys = {"listen_host", "listen_port", "ssl_insecure", "mode"}
        extra_options = dict(self._config.mitm_options)
        conflicts = managed_keys & extra_options.keys()
        if conflicts:
            raise ValueError(
                "mitm_options collides with harness-managed keys "
                f"{sorted(conflicts)}; set listen_host / listen_port / "
                "ssl_insecure / upstream_proxy on MonitoringConfig directly."
            )

        opts_kwargs: dict[str, Any] = {
            "listen_host": self._config.listen_host,
            "listen_port": self._config.listen_port,
            "ssl_insecure": self._config.ssl_insecure,
        }
        if self._config.upstream_proxy is not None:
            opts_kwargs["mode"] = (f"upstream:{self._config.upstream_proxy}",)
        opts_kwargs.update(extra_options)

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        opts = Options(**opts_kwargs)
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

        # Feed distinct-firings tracking to the drift accumulator.
        # The accumulator filters out its own synthetic events.
        if self._drift is not None:
            self._drift.observe_event(event)

        # Append drift / escalation events to the on-disk audit log.
        if self._store is not None:
            self._store.append_drift_event(event)

        in_shadow = self._is_in_shadow(event)
        if in_shadow:
            # Shadow mode: record + DEBUG-log only; do NOT page out via
            # the alert webhook. The event is still available on the
            # in-memory buffer and the stream iterator for tests and
            # analyst tooling.
            logger.debug(
                "SHADOW %s · %s · T%d · session=%s turn=%d (baseline not yet established)",
                event.saster_id,
                event.pattern_name,
                event.tier,
                event.session_id[:12],
                event.turn_idx,
            )
            return

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

    def _handle_turn(self, turn: TurnData) -> None:
        """Per-turn callback wired into the proxy's ``turn_sink``.

        Routes the turn to the drift accumulator (if constructed) and
        to the observed-tool-call mix counter on the composite
        baseline. Synthetic-event emission is the accumulator's
        responsibility — this method does not directly fire anything."""
        if self._drift is not None:
            self._drift.observe_turn(turn)
        if self._composite_baseline is not None:
            host = (turn.target_host or "").lower().strip()
            if host:
                self._composite_baseline.tool_call_mix.observe(
                    host, timestamp=turn.timestamp,
                )
        if self._store is not None:
            self._turns_since_snapshot += 1
            if self._turns_since_snapshot >= self._config.snapshot_every_turns:
                self._turns_since_snapshot = 0
                self._store.snapshot(self._baseline, self._detectors)

    def _is_in_shadow(self, event: DetectionEvent) -> bool:
        """Return True when ``event`` should be suppressed from the
        alert webhook because the session baseline has not locked in
        and shadow mode is enabled."""
        if not self._config.shadow_mode:
            return False
        # Synthetic events emitted by the drift / probe / sampler
        # subsystems are not tied to a live session baseline — they
        # always fire through the full alert path.
        synthetic_prefixes = (
            "SASTER-DRIFT", "SASTER-AUTONOMOUS", "SASTER-PROBE",
        )
        if any(event.saster_id.startswith(p) for p in synthetic_prefixes):
            return False
        if not event.session_id:
            return False
        # PROBE-scheduler synthetic sessions never go through
        # EmbeddingBaseline.observe, so is_established always returns
        # False for them — without this bypass, every induced-detector
        # firing from the scheduler would be silently shadow-gated in
        # the default config. Bypass them so PROBE-mode demos and
        # production probe cycles actually page out.
        if event.session_id.startswith("probe::"):
            return False
        return not self._baseline.is_established(event.session_id)

    def _dispatch_webhook(self, event: DetectionEvent) -> None:
        """Fire-and-forget POST.

        v0.3 makes this non-blocking on the caller thread: the actual
        HTTP request runs on a bounded ThreadPoolExecutor so a slow or
        hung webhook endpoint can no longer stall the proxy pipeline.
        A broken Slack URL must not take down the proxy thread.

        Failures are logged but do not raise. If the executor queue is
        full (rare — only happens under sustained webhook latency at
        high detection rates), the dispatch is dropped with a WARNING
        rather than blocking the caller to make room.
        """
        executor = self._ensure_webhook_executor()
        if executor is None:
            return
        try:
            executor.submit(self._post_webhook, event)
        except RuntimeError:  # pragma: no cover — executor already shut down
            logger.debug("Webhook executor shut down; dropping event.")
        except Exception:
            logger.exception("Failed to submit webhook task")

    def _ensure_webhook_executor(self) -> Any:
        """Lazily construct the webhook dispatch executor on first use.
        Returns ``None`` when httpx is unavailable so the caller can
        skip cleanly."""
        if self._webhook_executor is not None:
            return self._webhook_executor
        try:
            import httpx  # noqa: F401 — fail fast if httpx isn't available
        except ImportError:  # pragma: no cover — httpx is a hard dep
            logger.error("httpx not available; cannot dispatch alert webhook.")
            return None
        from concurrent.futures import ThreadPoolExecutor
        self._webhook_executor = ThreadPoolExecutor(
            max_workers=2,
            thread_name_prefix="saster-harness-webhook",
        )
        return self._webhook_executor

    def _post_webhook(self, event: DetectionEvent) -> None:
        """Execute the actual HTTP POST. Runs on the webhook executor
        thread, never on the proxy / caller thread."""
        try:
            import httpx
            if self._webhook_client is None:
                self._webhook_client = httpx.Client(timeout=3.0)
            self._webhook_client.post(
                self._config.alert_webhook,
                json=event.to_dict(),
            )
        except Exception:
            logger.exception("Alert webhook POST failed")

    def _start_probe_scheduler(self) -> None:
        """Construct and start the PROBE-mode side-loop.

        Replaces the v0.1/v0.2 logged-warning stub. The scheduler runs
        as a daemon thread, wakes every ``probe_interval_hours``, and
        invokes every :class:`InductionDetector` against the configured
        :class:`Prober`. Divergence scores feed the
        :class:`DriftAccumulator`'s susceptibility lookup."""
        prober = self._ensure_prober()
        if prober is None:
            logger.warning(
                "PROBE mode requested but no prober is available "
                "(operator did not pass one and HttpInjector could not "
                "be constructed against %s). Scheduler will idle.",
                self._config.agent_endpoint,
            )
        interval_seconds = float(self._config.probe_interval_hours) * 3600.0
        self._probe_scheduler = ProbeScheduler(
            detectors=self._detectors,
            prober=prober,
            sink=self._handle_event,
            susceptibility_cache=self._susceptibility_cache,
            interval_seconds=interval_seconds,
            probe_on_start=self._config.probe_on_start,
        )
        self._probe_thread = self._probe_scheduler.start_thread(self._stop_event)

    # ----------------------------------------------------------------
    # v0.3 baseline construction
    # ----------------------------------------------------------------

    def _apply_extra_reframings(
        self, extras: dict[str, Sequence[str]],
    ) -> None:
        """Push operator-supplied reframings into matching single-turn
        induction detectors.

        Keys that don't match any loaded detector log a WARNING and
        are skipped — likely a stale entry from a prior config rather
        than a hard error worth aborting startup over."""
        if not extras:
            return
        by_id = {d.saster_id: d for d in self._detectors}
        for det_id, prompts in extras.items():
            detector = by_id.get(det_id)
            if detector is None:
                logger.warning(
                    "extra_reframings: no detector loaded for id %r; "
                    "entry ignored.", det_id,
                )
                continue
            if not isinstance(detector, SingleTurnInductionDetector):
                logger.warning(
                    "extra_reframings: detector %r is not a single-turn "
                    "induction detector; entry ignored (use "
                    "extra_turn_sequences for multi-turn detectors).",
                    det_id,
                )
                continue
            detector.add_reframings(list(prompts))

    def _apply_extra_turn_sequences(
        self, extras: dict[str, Sequence[Sequence[str]]],
    ) -> None:
        """Push operator-supplied multi-turn ramps into matching
        multi-turn induction detectors."""
        if not extras:
            return
        by_id = {d.saster_id: d for d in self._detectors}
        for det_id, ramps in extras.items():
            detector = by_id.get(det_id)
            if detector is None:
                logger.warning(
                    "extra_turn_sequences: no detector loaded for id %r; "
                    "entry ignored.", det_id,
                )
                continue
            if not isinstance(detector, MultiTurnInductionDetector):
                logger.warning(
                    "extra_turn_sequences: detector %r is not a multi-turn "
                    "induction detector; entry ignored (use "
                    "extra_reframings for single-turn detectors).",
                    det_id,
                )
                continue
            detector.add_turn_sequences(list(ramps))

    def _ensure_prober(self) -> Prober | None:
        """Return the operator-supplied Prober, or construct a default
        HTTP one against ``config.agent_endpoint`` on first call.

        Returns ``None`` if construction fails (e.g., httpx not
        installed). The caller is responsible for graceful degradation.
        """
        if self._prober is not None:
            return self._prober
        try:
            injector = HttpInjector(
                endpoint=self._config.agent_endpoint,
            )
            self._prober = Prober(backend=injector)
        except Exception:  # pragma: no cover — defensive
            logger.exception(
                "Could not construct default HttpInjector for prober.",
            )
            return None
        return self._prober

    def _build_trained_baseline(self) -> TrainedRefusalBaseline:
        """Sample the agent's refusal distribution (Source 2: TRAINED)
        and return a populated baseline. Falls back to corpus-only
        centroid when sampling is disabled or the endpoint is
        unreachable."""
        if not self._config.sample_refusal_baseline:
            # Sampling explicitly off: ship a corpus-only centroid so
            # the trained signal still contributes to drift composition.
            sampler = RefusalSampler(
                embedder=self._shared_embedder,
                embedding_model_name=self._config.embedding_model,
            )
            baseline, receipt = sampler.sample(
                prober=None,
                agent_endpoint=self._config.agent_endpoint,
                timeout_seconds=self._config.sampling_timeout_seconds,
            )
            self._calibration_receipt = receipt
            return baseline

        prober = self._ensure_prober()
        sampler = RefusalSampler(
            embedder=self._shared_embedder,
            embedding_model_name=self._config.embedding_model,
        )
        baseline, receipt = sampler.sample(
            prober=prober,
            agent_endpoint=self._config.agent_endpoint,
            timeout_seconds=self._config.sampling_timeout_seconds,
        )
        self._calibration_receipt = receipt
        return baseline

    @property
    def probe_scheduler(self) -> ProbeScheduler | None:
        """The PROBE-mode scheduler, when ``start()`` was called with
        ``HarnessMode.PROBE`` and a non-zero ``probe_interval_hours``.
        Otherwise ``None``."""
        return self._probe_scheduler

    @property
    def composite_baseline(self) -> SessionBaseline | None:
        """The composite SessionBaseline assembled at ``start()``.
        ``None`` until ``start()`` has been called."""
        return self._composite_baseline

    @property
    def calibration_receipt(self) -> CalibrationReceipt | None:
        """The receipt produced by the boot-time refusal sampler.
        ``None`` until ``start()`` has been called."""
        return self._calibration_receipt


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
    (``"SASTER-18"``), ``-induced``, ``-multiturn``, ``-both``, or
    ``-all`` — plus any ids registered via :func:`register_detector`
    or :func:`register_detector_instance`. ``None`` loads the default
    v0.1 set (all 9 implementations). Unknown identifiers raise
    :class:`ValueError`; module-import failures log a warning and skip
    that detector rather than aborting the harness.

    For each identifier the loader checks the instance registry
    first; on a hit, it appends the pre-built instance and skips
    module loading. Otherwise each module exposes its detector class
    via a module-level ``DETECTOR`` attribute (instance, not class) —
    the registry expands a single identifier into one or more module
    paths and this loader assembles the resulting detector instances."""
    import importlib

    identifiers = list(enabled) if enabled is not None else list(_DEFAULT_ENABLED_DETECTORS)
    known_ids = set(_DETECTOR_REGISTRY) | set(_DETECTOR_INSTANCE_REGISTRY)
    unknown = [ident for ident in identifiers if ident not in known_ids]
    if unknown:
        raise ValueError(
            f"Unknown detector identifier(s): {unknown}. Accepted: "
            f"{sorted(known_ids)}."
        )

    out: list[SasterDetector] = []
    seen_modules: set[str] = set()
    seen_instances: set[int] = set()

    for ident in identifiers:
        # Instance registry wins when both registries carry the same id.
        if ident in _DETECTOR_INSTANCE_REGISTRY:
            inst = _DETECTOR_INSTANCE_REGISTRY[ident]
            if id(inst) in seen_instances:
                continue
            seen_instances.add(id(inst))
            out.append(inst)
            continue

        for mod_name in _DETECTOR_REGISTRY[ident]:
            if mod_name in seen_modules:
                continue
            seen_modules.add(mod_name)
            try:
                mod = importlib.import_module(mod_name)
            except ImportError as exc:
                logger.warning("Skipping %s — import failed: %s", mod_name, exc)
                continue
            detector_obj = getattr(mod, "DETECTOR", None)
            if detector_obj is None:
                logger.warning(
                    "Skipping %s — no module-level DETECTOR attribute", mod_name,
                )
                continue
            out.append(detector_obj)
    return out
