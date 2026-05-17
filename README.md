# saster-harness

[![CI](https://github.com/agentsattack/saster-harness/actions/workflows/test.yml/badge.svg)](https://github.com/agentsattack/saster-harness/actions/workflows/test.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python: 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

**Wire-level Agentic Detection and Response (ADR).** 9 detectors
covering 7 SASTER patterns (2 with both passive and induced
coverage). 4 operating modes — OBSERVE / PROBE / INDUCE / IMPORT.
HAR-file audit for browser-accessible agents without MITM.

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
from saster_harness.adapters import HttpJsonAdapter

config = MonitoringConfig(
    agent_name="support-prod",
    agent_endpoint="http://your-agent/chat",
    authorized_tools=["search_kb", "create_ticket"],
    max_drift_score=25,
    max_autonomous_hits=2,
    probe_interval_hours=24,
    alert_webhook="https://hooks.slack.com/...",
)

harness = MonitoringHarness(config, adapter=HttpJsonAdapter())
harness.start()
```

The harness listens on port 8888, captures HTTP/JSON traffic between
your agent and its tools, scores every turn against a per-session
behavioral baseline, runs each shipped detector against it, and
POSTs structured `DetectionEvent` JSON to your alert webhook when a
pattern fires.

---

> ### ⚠️ Heads-up: induced detectors don't fire on captured events
>
> Two of the nine detectors — **SASTER-18-induced** and
> **SASTER-24-induced** — run in *induction mode*. They do NOT fire
> from passively-captured traffic. They probe agent sessions
> actively, sending a baseline request, waiting for a response,
> then sending follow-up turns to test whether the agent's
> response shifts in a way that indicates a planted susceptibility.
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

## What ships in v0.1

**9 detectors covering 7 SASTER patterns** (2 with both passive and
induced coverage):

| # | Pattern | Tier | Mode | Description |
|---|---|---|---|---|
| **SASTER-18** | Semantic Recasting | T3 | passive | Distinctive-term retention heuristic on user-message vocabulary vs. agent-response vocabulary |
| **SASTER-18-induced** | Semantic Recasting (Induced) | T3 | induced | Active probe: baseline refusal + 4 canonical reframings; fires on response divergence |
| **SASTER-24** | Just-in-Time Ontological Reframing | T3 | passive | Self-narrated reframe regex — refusal clause + equivalence claim + substitute framing |
| **SASTER-24-induced** | JiTOR (Induced) | T3 | induced | Active probe: 4 redefinition scenarios; fires on definition-acceptance shift |
| **SASTER-26** | Recon-Gated Injection | T4 | passive | Vocabulary regex over 4 recon surfaces (compute, identity, pipeline, observability) |
| **SASTER-27** | Detection Layer Injection | T4 | passive | Zero-width Unicode, fake verdict strings, fake reasoning blocks |
| **SASTER-28** | Salience Suppression Exfiltration | T4 | passive | Creative-frame + retrieval-target co-occurrence |
| **SASTER-31** | Compositional Capability Emergence | T3 | passive | Wire-format signature: record-list POST + sensitive field names |
| **SASTER-33** | Context Stripping | T4 | passive | Per-session structural baseline on `role:system` message presence |

7 detectors fire passively on captured traffic. 2 detectors (the
`-induced` variants) run active probes against agent sessions —
see the callout above. SASTER-18 and SASTER-24 ship in both
flavours because the patterns have observable passive *and* active
manifestations; you can enable either, or both via
`MonitoringConfig(enabled_detectors=["SASTER-18-both", ...])`.

Each detector docstring quotes its canonical SASTER.md definition
verbatim, documents operational shape at the wire level, lists
tunables, and enumerates known false-positive cases. Detectors are
tuned toward false negatives over false positives — deploy with
`max_drift_score` and per-detector thresholds at the defaults for
a few days, then tune sensitivity upward against baseline traffic
before opening the alert valve fully.

## Verifying against the bundled reference agent

Carl is a simulated agent with four planted susceptibilities:
infrastructure recon (Carl 2a), database exfil (Carl 2b),
semantic-recasting reframing (Carl 4), and JiTOR redefinition
(Carl 4). The scenarios are deterministic and run against
localhost — no real systems are touched.

Carl 1–2 drive the detector pipeline directly via canned scripts;
Carl 3–4 ship as an HTTP server that calls a real upstream LLM with
a hidden directive system prompt, so the induced detectors can
verify end-to-end against realistic LLM-shaped text:

```bash
# Spin up Carl in induction-mode susceptibility:
CARL_DIRECTIVE=jitor_susceptible \
CARL_LLM_ENDPOINT=http://your-llm/v1/chat/completions \
python -m carl.server

# In another terminal, run the calibration script — drives both
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

- **v0.2** — detector calibration toolkit, more T3 detectors, live
  dashboard reference implementation,
  `SingleTurnInductionDetector` / `ScenarioInductionDetector`
  split, separate `induction_timeout` on `HttpInjector`, embedding-
  similarity check for SASTER-18, formal susceptibility-encoding
  contract for reference targets.
- **v0.3** — multi-agent correlation, action-graph reasoning for
  compositional patterns (full SASTER-31 detection beyond wire
  signatures).
- **v0.4** — PROBE-mode generators auto-derived from SASTER pattern
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
