# saster-harness

[![CI](https://github.com/agentsattack/saster-harness/actions/workflows/test.yml/badge.svg)](https://github.com/agentsattack/saster-harness/actions/workflows/test.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python: 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

**Wire-level Agentic Detection and Response (ADR).** 13 detectors
covering 9 SASTER patterns (3 with both passive and induced
coverage; SASTER-18 also has a multi-turn induced variant). 3
operating modes — OBSERVE / PROBE / INDUCE. HAR-file audit via the
separate `saster-har` CLI for browser-accessible agents without MITM.

`saster-harness` sits between your agent and its tools/network,
establishes a behavioral baseline per session, and fires structured
detection events when agent behavior matches a pattern from the
[SASTER taxonomy](https://github.com/lsuto/saster).

Agents that look fine in unit tests still misbehave at runtime —
emitting covert recon questions, composing safe capabilities into
unsafe outcomes, stripping context from requests to scanners,
pivoting around refusals. None of those failure modes are visible to
WAFs, EDR, or SIEM correlation; they live inside what looks like
ordinary agent network behavior. ADR watches the wire, not the
logs, specifically to catch them.

This release accompanies the LayerOne 2026 talk on ADR.

---

## Install + first detection in 5 minutes

```bash
git clone https://github.com/agentsattack/saster-harness.git
cd saster-harness
pip install -e ".[dev]"
```

(Once published to PyPI: `pip install saster-harness`. Python 3.10+
required. The first run downloads the
`sentence-transformers/all-MiniLM-L6-v2` model — about 90 MB — for
the session baseline; subsequent runs use the local cache.)

### Path A — bundled scenario (no infrastructure)

```bash
python -m carl.run_recon
```

Runs the simulated rogue agent end-to-end against the detector
pipeline. Output ends with:

```
Summary:
  SASTER-26: 3 firing(s) at turns [5, 11, 17]
  SASTER-33: 3 firing(s) at turns [5, 11, 17]
OK — Carl 2a recon scenario fired SASTER-26 + SASTER-33 as expected.
```

That's two patterns firing on a simulated rogue agent in under 30
seconds, no network access required.

### Path B — audit any browser-accessible agent (no MITM)

Capture a HAR from your browser's DevTools Network panel, then:

```bash
saster-har session.har
```

The CLI streams a JSON report — SASTER firings by pattern, with the
raw turn excerpts that triggered each event. See
[docs/har_import.md](docs/har_import.md) for the privacy / consent
walkthrough and the redaction model.

### Path C — wire-mode against your own agent

The 90-line example from the LayerOne slides — also at
`examples/runner.py`:

```python
from saster_harness import MonitoringConfig, MonitoringHarness

config = MonitoringConfig(
    agent_name="support-prod",
    agent_endpoint="http://your-agent/chat",
    # Host fragments, NOT tool names. Matched against turn.target_host
    # with case-insensitive bidirectional substring — declare the hosts
    # your agent is permitted to call (see SKILL.md for the two
    # substring-match footguns before you tune this for production).
    authorized_tools=["api.your-agent.com", "internal-kb.corp.example"],
    max_drift_score=25,
    max_autonomous_hits=2,
    probe_interval_hours=24,
    alert_webhook="https://hooks.slack.com/...",
)

harness = MonitoringHarness(config)  # HttpJsonAdapter is the default
harness.start()
```

The harness listens on port 8888, captures HTTP/JSON traffic between
your agent and its tools, scores every turn against a per-session
behavioral baseline, runs each shipped detector against it, and
POSTs structured `DetectionEvent` JSON to your alert webhook when a
pattern fires.

#### Modifying Path C for your own agent

Two starting templates ship in the repo — pick the one that matches
how you want to invoke the harness:

- **`examples/runner.py`** — the embedded-Python shape above.
  Suitable when the harness lives inside your own process (FastAPI
  service, scheduled job, integration test, etc.). You import
  `MonitoringConfig` + `MonitoringHarness` and call `harness.start()`
  directly.
- **`examples/carl_config.py`** — declares a module-level
  `config = MonitoringConfig(...)` that the CLI loads via
  `python -m saster_harness --config examples/carl_config.py`. Use
  this when you want the harness to run as a standalone process
  (systemd unit, supervisord-managed worker, container entrypoint).

Either way, the minimal customization for a different agent is:

1. Copy the template — `cp examples/runner.py examples/my_agent.py`
   (or `cp examples/carl_config.py examples/my_agent_config.py` for
   the CLI shape).
2. Change `agent_name` to your agent's stable identifier.
3. Change `agent_endpoint` to your agent's chat URL.
4. Change `authorized_tools` to host fragments your agent is allowed
   to call (the URL hosts, not tool names — see SKILL.md for the
   substring-match semantics and the two footguns).
5. Run.

For deeper customization — adding deployment-specific reframings
(`extra_reframings`), enabling the multi-turn detector
(`enabled_detectors=["SASTER-18-multiturn"]` or `"SASTER-18-all"`),
tuning drift weights, switching from OBSERVE to PROBE mode, surfacing
SHADOW events on the terminal (`log_shadow_events=True`), persisting
state to disk (`state_dir`), or registering a custom detector
(`register_detector_instance(...)` at import time) — see
[SKILL.md](SKILL.md) for the complete `MonitoringConfig` field tour.
Every operator-facing knob lives on that one struct.

---

> ### ⚠️ Heads-up: induced detectors don't fire on captured events
>
> Six of the thirteen detectors — **SASTER-13-induced**,
> **SASTER-15-induced**, **SASTER-18-induced**, **SASTER-18-multiturn**,
> **SASTER-24-induced**, and **SASTER-26-induced** — run in *induction
> mode*. They do NOT
> fire from passively-captured traffic. They probe agent sessions
> actively, sending a baseline request, waiting for a response, then
> sending follow-up turns (or full scenarios) to test whether the
> agent's response shifts in a way that indicates a planted
> susceptibility.
>
> If you enable an induced detector and watch your wire feed, you'll
> see "nothing fires." That's expected. Induced detectors run
> out-of-band via the harness's `Prober` subsystem on a schedule
> (PROBE mode) or via explicit trigger (`detector.induce(prober,
> session_id)`); their events appear in your alert webhook /
> in-memory buffer, not as automatic responses to live traffic.
>
> See [docs/pattern-authoring.md](docs/pattern-authoring.md#authoring-an-induction-mode-detector-extra-notes)
> for the operational guide.

---

## What ships in v0.3.2

**13 detectors covering 9 SASTER patterns** (3 with both passive and
induced coverage; SASTER-18 additionally has a multi-turn induced
variant):

| # | Pattern | Tier | Mode | Description |
|---|---|---|---|---|
| **SASTER-13-induced** | Spec Drift (Induced) | T2 | induced | Active probe: in-scope baseline + 4 adjacency reframings (while-we're-at-it / hypothetical / customer-asked-me / quick-aside); fires on substantive drift into out-of-scope topic |
| **SASTER-15-induced** | Intent Erosion (Induced) | T2 | induced | Active probe: 4 scenarios of baseline refusal + 4–5 adjacency-normalizing turns + target re-ask; fires when agent capitulates after erosion |
| **SASTER-18** | Semantic Recasting | T3 | passive | Distinctive-term retention heuristic on user-message vocabulary vs. agent-response vocabulary |
| **SASTER-18-induced** | Semantic Recasting (Induced) | T3 | induced | Active probe: baseline refusal + 4 canonical reframings; fires on response divergence |
| **SASTER-18-multiturn** | Semantic Recasting (Multi-Turn) | T3 | induced (multi-turn) | Active probe: 4 Crescendo-style ramps × 3 turns each (research / fiction / red-team / educational framings); fires on capitulation at the final ask of a ramp. Opt-in — enable via `"SASTER-18-multiturn"` or `"SASTER-18-all"`. |
| **SASTER-24** | Just-in-Time Ontological Reframing | T3 | passive | Self-narrated reframe regex — refusal clause + equivalence claim + substitute framing |
| **SASTER-24-induced** | JiTOR (Induced) | T3 | induced | Active probe: 4 redefinition scenarios; fires on definition-acceptance shift |
| **SASTER-26** | Recon-Gated Injection | T4 | passive | Vocabulary regex over 4 recon surfaces (compute, identity, pipeline, observability) |
| **SASTER-26-induced** | Recon-Gated Injection (Induced) | T4 | induced | Double-probe: 3 recon turns + post-recon vs 3 neutral turns + same post-recon; fires when post-recon answer tailors to harvested environment context |
| **SASTER-27** | Detection Layer Injection | T4 | passive | Zero-width Unicode, fake verdict strings, fake reasoning blocks |
| **SASTER-28** | Salience Suppression Exfiltration | T4 | passive | Creative-frame + retrieval-target co-occurrence |
| **SASTER-31** | Compositional Capability Emergence | T3 | passive | Wire-format signature: record-list POST + sensitive field names |
| **SASTER-33** | Context Stripping | T4 | passive | Per-session structural baseline on `role:system` message presence |

7 detectors fire passively on captured traffic. 6 detectors (the
`-induced` and `-multiturn` variants) run active probes against
agent sessions — see the callout above. SASTER-18, SASTER-24, and
SASTER-26 ship in both flavours because the patterns have observable
passive *and* active manifestations; you can enable either, or both
via the `-both` convenience shortcuts:
`MonitoringConfig(enabled_detectors=["SASTER-18-both",
"SASTER-24-both", "SASTER-26-both", ...])`. To additionally include
the Crescendo-style multi-turn detector, use `"SASTER-18-all"` in
place of `"SASTER-18-both"` (passive + single-turn induced + multi-
turn). Default-when-omitted loads 12 of the 13 implementations —
`SASTER-18-multiturn` is the one opt-in.

Each detector docstring quotes its canonical SASTER.md definition
verbatim, documents operational shape at the wire level, lists
tunables, and enumerates known false-positive cases. Detectors are
tuned toward false negatives over false positives — deploy with
`max_drift_score` and per-detector thresholds at the defaults for
a few days, then tune sensitivity upward against baseline traffic
before opening the alert valve fully.

## Verifying against the bundled reference agent

Carl is a simulated reference agent with 8 hidden directives
(`carl/directives.py`) — 6 susceptibility variants
(`semantic_recasting`, `jitor_susceptible`,
`intent_erosion_susceptible`, `recon_acting`,
`spec_drift_susceptible`, `recon_emitter`) and 2 negative baselines
(`""` neutral and `customer_support_scoped`). The directive is
selected via the `CARL_DIRECTIVE` environment variable at server
start.

Carl ships in two shapes:

- **Canned scenarios** (`carl/run_recon.py`, `carl/run_exfil.py`)
  drive the detector pipeline directly via deterministic scripts —
  no LLM, no network. Fast smoke tests for the passive detectors.
- **HTTP server** (`python -m carl.server`) calls a real upstream
  LLM with the directive's system prompt, so the induced detectors
  can verify end-to-end against realistic LLM-shaped text:

```bash
# Spin up Carl in induction-mode susceptibility:
CARL_DIRECTIVE=jitor_susceptible \
CARL_LLM_ENDPOINT=http://your-llm/v1/chat/completions \
python -m carl.server

# In another terminal, run the calibration script — drives all five
# induced detectors against live Carl with the production embedder:
python scripts/phase4_calibration.py
```

See [carl/README.md](carl/README.md) for the full simulation
disclaimer and scenario index.

## Documentation

- [**docs/methodology.md**](docs/methodology.md) — ADR concept,
  why wire-level rather than LLM-level, why session baseline,
  position relative to WAF / EDR / SIEM / DLP.
- [**docs/har_import.md**](docs/har_import.md) — offline HAR
  audit, privacy / consent, redaction model, session correlation
  strategies.
- [**docs/decision-trees.md**](docs/decision-trees.md) — per-pattern
  decision trees for analyst triage; disambiguation guidance;
  co-firing reference table.
- [**docs/pattern-authoring.md**](docs/pattern-authoring.md) —
  worked example of mapping Carl 2b to SASTER-31; the SASTER-18
  threshold-tuning narrative as the FP-analysis template; how to
  author a new detector (including induction-mode notes for
  timeouts and susceptibility encoding).
- [**docs/contribution.md**](docs/contribution.md) — PR workflow,
  quality gates, Candidate pattern submission process,
  attribution.
- [**SKILL.md**](SKILL.md) — operational guide for Claude Code /
  Codex / Cursor users.
- [**carl/README.md**](carl/README.md) — Carl reference scenarios
  with simulation disclaimer.

## Roadmap

Shipped through v0.3.x:

- Detector-base-class split: `SingleTurnInductionDetector` /
  `MultiTurnInductionDetector` / `ScenarioInductionDetector`.
- Separate `induction_timeout` on `HttpInjector` (180s default,
  independent of the general 30s `timeout`).
- Crescendo-style multi-turn induction detector
  (`SASTER-18-multiturn`).
- PROBE-mode scheduler — induced detectors run automatically on a
  configurable cadence; susceptibility scores feed the live drift
  composite via `DriftAccumulator.observe_event`.
- Explicit probe-origin attribution on `DetectionEvent` — probe-
  elicited events are flagged and excluded from organic drift
  accumulation.
- Detector-extension hooks: `extra_reframings` /
  `extra_turn_sequences` config fields; `register_detector_instance`
  for custom probes.
- Calibration toolkit (`scripts/phase4_calibration.py`) covering all
  five shipped induced detectors against Carl's directive matrix.
- Tunable drift weights (`drift_weight_*` config fields).
- Per-deployment shadow-mode controls (`shadow_mode`,
  `log_shadow_events`).

Still aspirational:

- Live dashboard reference implementation.
- Multi-agent correlation; action-graph reasoning for full
  SASTER-31 detection beyond wire signatures.
- PROBE-mode generators auto-derived from SASTER pattern
  definitions; full INDUCE-mode adversarial probe library.

## Talk + recordings

LayerOne 2026, *Agentic Detection and Response*. Slide deck and
recorded demos are linked from the conference proceedings; the
harness behavior matches the recorded Demo 2a (`carl/run_recon.py`)
and Demo 2b (`carl/run_exfil.py`) turn-for-turn.

## Citation

If you use `saster-harness` in academic or professional work,
please cite:

```bibtex
@misc{suto2026sasterharness,
  author       = {Suto, Larry},
  title        = {{saster-harness}: Wire-level Agentic Detection and Response
                  for the SASTER taxonomy},
  year         = {2026},
  howpublished = {LayerOne 2026},
  url          = {https://github.com/agentsattack/saster-harness}
}
```

## License + contact

MIT — see [LICENSE](LICENSE).

Maintainer: Larry Suto, `larry@stratdatsec.com`. GitHub issues for
default-public discussion; email for security-disclosure issues or
anything you'd rather not raise in public.
