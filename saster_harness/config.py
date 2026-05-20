"""MonitoringConfig — user-facing configuration dataclass.

The public API in this module is locked: the field names and defaults are
referenced in the LayerOne 2026 talk slides and in published examples.
Additions must be backward-compatible (new fields default to None or to a
documented sensible value); renames or removals require a major version bump.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from urllib.parse import urlparse


class HarnessMode(str, Enum):
    """Operating mode for the harness.

    OBSERVE
        Passive wire capture. The harness watches every request and response
        between the agent and its tools/network, runs detectors, and emits
        events. No synthetic traffic is generated. This is the default mode
        and the only mode safe to enable in production without coordination.

    PROBE
        OBSERVE plus a scheduled synthetic probe injection every
        ``probe_interval_hours``. Probes are derived from the SASTER taxonomy
        and are designed to elicit a detector response from a healthy
        agent — they are how the harness self-tests against your specific
        deployment. Probes carry an ``X-Saster-Probe`` header so downstream
        systems can filter them out of analytics.

    INDUCE
        Active adversarial testing. The harness generates probes that target
        observed weak spots in the agent's behavioral baseline. Off by
        default and gated behind an explicit opt-in because INDUCE can cause
        real agent behavior change. Intended for staging environments.
    """

    OBSERVE = "observe"
    PROBE = "probe"
    INDUCE = "induce"


# Slack-style webhook URL pattern (loose — accepts any HTTPS POST endpoint).
_WEBHOOK_RE = re.compile(r"^https?://", re.IGNORECASE)


@dataclass
class MonitoringConfig:
    """Runtime configuration for a single agent under monitoring.

    The first six fields are the public surface referenced in the LayerOne
    slides. Fields below ``alert_webhook`` are operational knobs with
    sensible defaults.

    Parameters
    ----------
    agent_name
        Stable identifier for the agent. Used as the ``agent_name`` field on
        every emitted :class:`~saster_harness.event.DetectionEvent` and as
        the routing key in alert payloads. Recommend lowercase-dash form
        (``"support-prod"``).
    agent_endpoint
        The HTTP(S) URL of the agent under monitoring. The harness does not
        connect to this URL itself — it is used for documentation in events
        and as a sanity check that the captured traffic actually belongs to
        the configured agent.
    authorized_tools
        Allow-list of tool names the agent is permitted to invoke. Used by
        compositional and recon-gated detectors to flag tool calls outside
        the authorized set.
    max_drift_score
        Cumulative drift score per session before the harness raises an
        alert independent of any single detector firing. Drift accumulates
        as the per-turn boundary proximity exceeds 0.5; a typical legitimate
        session stays under 10. Tune against your baseline traffic.
    max_autonomous_hits
        Maximum number of detector firings in a single session before the
        harness escalates to a session-level alert. ``2`` means the third
        firing triggers escalation. Set to ``0`` to escalate on every hit.
    probe_interval_hours
        Cadence for synthetic probe injection in PROBE mode. Ignored in
        OBSERVE and INDUCE modes. Set to ``0`` to disable scheduled probing.
    probe_on_start
        When ``True``, the PROBE scheduler runs its first cycle
        immediately at :meth:`MonitoringHarness.start`. Default
        ``False`` waits ``probe_interval_hours`` before the first
        cycle. The immediate-start mode is intended for stage demos
        and CI runs that need to see PROBE results before the
        interval elapses.
    alert_webhook
        Optional HTTPS endpoint that receives a JSON POST per detection
        event. Compatible with Slack and Microsoft Teams incoming-webhook
        URLs; the payload also conforms to the generic JSON event shape
        documented in ``docs/methodology.md``. Set to ``None`` to suppress
        alerts (events still go to the local log and the :meth:`stream`
        iterator).
    listen_port
        TCP port the wire-capture proxy binds to. Default ``8888``.
    baseline_turns
        Number of in-band turns required before the session baseline is
        considered established. Detectors that depend on the baseline
        (boundary proximity, SASTER-33) suppress firings until this count
        is reached.
    baseline_hours
        Wall-clock duration the session must accumulate before the
        baseline locks in. Default ``0.0`` (no clock-time gate; the
        baseline locks as soon as ``baseline_turns`` is reached, matching
        v0.2 behavior). When ``> 0.0``, both conditions must hold —
        the session is considered baselined only once it has observed
        ``baseline_turns`` AND been open for ``baseline_hours``. Use
        24 to demand a full day of OBSERVE before any drift signal
        leaves the harness in shadow mode.
    embedding_model
        Sentence-transformer model identifier used for the session baseline.
        Default ``"all-MiniLM-L6-v2"`` — fast, ~90 MB, ships from
        HuggingFace.
    mode
        Initial harness mode. Defaults to :attr:`HarnessMode.OBSERVE`.
    shadow_mode
        When ``True`` (the default), passive-detector events fired
        before the session embedding baseline is established are
        suppressed from the alert webhook — they still enter the
        in-memory event buffer and the stream iterator and log at
        DEBUG level. Once the baseline locks in for that session,
        the full firing path resumes. Set to ``False`` to fire
        alerts from turn 0, restoring the v0.2 behavior. The default
        matches the operational story in the LayerOne slide deck:
        the harness OBSERVES before it ALERTS.
    sample_refusal_baseline
        When ``True`` (the default), the harness probes the agent at
        ``start()`` with the bundled refusal-eliciting corpus
        (``corpora/refusal_probes.txt``) and builds the TRAINED
        refusal centroid from the responses. The centroid is then
        injected into SASTER-18-induced and used by the drift
        accumulator's ``refusal_pattern_change`` signal. Falls back
        gracefully to the bundled refusal corpus centroid if the
        agent endpoint is unreachable. Set to ``False`` to skip the
        live sampling and use the corpus-only centroid.
    sampling_timeout_seconds
        Total time budget for boot-time refusal sampling, regardless
        of per-probe ``induction_timeout``. Default ``60.0`` s caps
        worst-case boot at ~1 minute even when every probe is hitting
        the 180 s induction-timeout ceiling. Whichever probes have
        completed when the budget is exhausted feed the centroid;
        if zero completed, the sampler falls back to the corpus
        centroid. Set to ``0.0`` to disable the cap (unbounded
        sampling — matches v0.3.0-dev behavior).
    state_dir
        Optional directory for disk-backed persistence. When set, the
        harness writes per-agent state under ``<state_dir>/<agent_name>/``:
        session embedding centroids, SASTER-33 structural baselines,
        drift events log, and the boot-time calibration receipt. State
        is read back at ``start()`` if present. Default ``None`` =
        in-memory only (matches v0.2 behavior — process restart wipes
        baselines).
    snapshot_every_turns
        When ``state_dir`` is set, take a state snapshot every N
        captured turns. Default ``50``. The accumulating drift log
        is appended on every drift event regardless of this value;
        only the heavyweight centroids/structural snapshots respect
        this cadence.
    """

    agent_name: str
    agent_endpoint: str
    authorized_tools: list[str]
    max_drift_score: int = 25
    max_autonomous_hits: int = 2
    probe_interval_hours: int = 24
    probe_on_start: bool = False
    alert_webhook: str | None = None

    # Operational knobs (not on the slide but available to advanced users).
    listen_port: int = 8888
    baseline_turns: int = 10
    baseline_hours: float = 0.0
    embedding_model: str = "all-MiniLM-L6-v2"
    mode: HarnessMode = HarnessMode.OBSERVE
    shadow_mode: bool = True
    sample_refusal_baseline: bool = True
    sampling_timeout_seconds: float = 60.0
    state_dir: Path | None = None
    snapshot_every_turns: int = 50
    enabled_detectors: list[str] | None = field(default=None, repr=False)
    """SASTER detector identifiers to load. ``None`` loads the full v0.1
    set (9 implementations covering 7 SASTER patterns — five passive
    detectors plus the two patterns that ship in both passive and
    induced flavours).

    Accepted identifiers:

    - Plain ids (``"SASTER-18"``, ``"SASTER-26"``, …) — passive
      detectors.
    - ``"-induced"`` suffix (``"SASTER-18-induced"``,
      ``"SASTER-24-induced"``) — induction-mode detectors that
      actively probe agent sessions.
    - ``"-both"`` suffix (``"SASTER-18-both"``,
      ``"SASTER-24-both"``) — convenience shortcut for both the
      passive and induced flavour of the same SASTER pattern.

    Default-when-omitted loads all nine implementations. Restricting
    the set is the recommended path for initial deployments;
    additions go through the pattern-authoring workflow."""

    def __post_init__(self) -> None:
        if not self.agent_name or not self.agent_name.strip():
            raise ValueError("agent_name must be a non-empty string")
        if not self.agent_endpoint:
            raise ValueError("agent_endpoint is required")
        parsed = urlparse(self.agent_endpoint)
        if parsed.scheme not in ("http", "https"):
            raise ValueError(
                f"agent_endpoint must be http:// or https:// (got {parsed.scheme!r})"
            )
        if not isinstance(self.authorized_tools, list):
            raise TypeError("authorized_tools must be a list[str]")
        if any(not isinstance(t, str) or not t for t in self.authorized_tools):
            raise ValueError("authorized_tools entries must be non-empty strings")
        if self.max_drift_score < 0:
            raise ValueError("max_drift_score must be >= 0")
        if self.max_autonomous_hits < 0:
            raise ValueError("max_autonomous_hits must be >= 0")
        if self.probe_interval_hours < 0:
            raise ValueError("probe_interval_hours must be >= 0")
        if self.alert_webhook is not None and not _WEBHOOK_RE.match(self.alert_webhook):
            raise ValueError(
                "alert_webhook must be an http:// or https:// URL when set"
            )
        if not (1 <= self.listen_port <= 65535):
            raise ValueError("listen_port must be in [1, 65535]")
        if self.baseline_turns < 1:
            raise ValueError("baseline_turns must be >= 1")
        if self.baseline_hours < 0:
            raise ValueError("baseline_hours must be >= 0.0")
        if self.snapshot_every_turns < 1:
            raise ValueError("snapshot_every_turns must be >= 1")
        if self.sampling_timeout_seconds < 0:
            raise ValueError("sampling_timeout_seconds must be >= 0.0")
        if self.state_dir is not None and not isinstance(self.state_dir, Path):
            self.state_dir = Path(self.state_dir)
        if isinstance(self.mode, str):
            try:
                self.mode = HarnessMode(self.mode)
            except ValueError as exc:
                raise ValueError(
                    f"mode must be one of {[m.value for m in HarnessMode]}"
                ) from exc
