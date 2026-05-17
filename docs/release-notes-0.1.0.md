# Release notes — v0.1.0

This file contains the GitHub Release copy for v0.1.0. Two
versions: a short blurb for the release card and a long form for
the release body.

---

## Short version (release card subtitle)

> Wire-level Agentic Detection and Response (ADR) for the SASTER
> taxonomy. v0.1.0 ships 9 detector implementations covering 7
> SASTER patterns (2 with both passive and induced coverage), a
> reference rogue agent (Carl) for harness validation, HAR-file
> audit for browser-accessible agents without MITM, and a Phase 6
> verification record against live Llama-3.3-70B. Accompanies the
> LayerOne 2026 talk.

---

## Long version (release body)

**saster-harness** is a wire-level Agentic Detection and Response
(ADR) harness for the [SASTER taxonomy](https://github.com/lsuto/saster).
It sits between an AI agent and its tools/network, establishes a
behavioral baseline per session, and fires structured detection
events when agent behavior matches a catalogued failure mode.

This release accompanies the LayerOne 2026 talk on ADR.

### What's in v0.1.0

#### 9 detector implementations covering 7 SASTER patterns

Seven passive detectors that fire on captured `TurnData`. Two
induced detectors that actively probe agent sessions via the
`Prober` subsystem. SASTER-18 and SASTER-24 ship in both flavours
because the patterns have observable passive AND active
manifestations.

| Pattern | Tier | Mode | Description |
|---|---|---|---|
| **SASTER-18** | T3 | passive | Semantic Recasting — distinctive-term retention heuristic on user-message vocabulary vs. agent-response vocabulary |
| **SASTER-18-induced** | T3 | induced | Active probe: baseline refusal + 4 canonical reframings (hypothetical / researcher / fictional / technical-scope); fires on response divergence above the 0.6 threshold |
| **SASTER-24** | T3 | passive | Just-in-Time Ontological Reframing — three regex sub-patterns for self-narrated bypasses |
| **SASTER-24-induced** | T3 | induced | Active probe: 4 redefinition scenarios (internal_docs_scope, personal_data_scope, authorized_user_scope, production_scope); fires on definition-acceptance shift above the 0.5 threshold |
| **SASTER-26** | T4 | passive | Recon-Gated Injection — vocabulary regex over four recon surfaces (compute, identity, pipeline, observability) |
| **SASTER-27** | T4 | passive | Detection Layer Injection — signatures for zero-width Unicode, fake verdict strings, fake reasoning blocks |
| **SASTER-28** | T4 | passive | Salience Suppression Exfiltration — creative-frame + retrieval-target co-occurrence |
| **SASTER-31** | T3 | passive | Compositional Capability Emergence — wire-format signature for record-list POSTs with sensitive field names |
| **SASTER-33** | T4 | passive | Context Stripping — per-session structural baseline on `role:system` presence |

#### Heads-up: induced detectors don't fire on captured events

The two `-induced` detectors run out-of-band via the `Prober`
subsystem — they actively send probe turns into an agent session
rather than firing on passively-captured traffic. If you enable
SASTER-18-induced or SASTER-24-induced and watch your wire feed
expecting events to appear automatically, you'll see nothing.
That's the correct behaviour. Call `.induce(prober, session_id)`
explicitly, or wait for v0.2's PROBE-mode scheduler.

#### Core framework

- `MonitoringHarness` orchestrator with OBSERVE / PROBE / INDUCE
  modes plus HAR-import via the `saster-har` CLI.
- Embedded mitmproxy `DumpMaster` for HTTP/HTTPS wire capture.
- Per-session embedding baseline using
  `sentence-transformers/all-MiniLM-L6-v2`, shared across the
  baseline and induced detectors via a single lazy-loaded model
  instance (no double-load cold-start).
- `HttpJsonAdapter` for OpenAI-style chat completion traffic, with
  fallback shapes for common alternative JSON conventions.
- `HARAdapter` for offline audit of Chrome / Firefox HAR exports
  with default redaction of Authorization / Cookie / X-API-Key
  headers, JSON body fields named password / token / api_key /
  ssn / credit_card, and pattern-matched JWT / credit card / SSN
  values.
- `Prober` subsystem with `InjectorBackend` Protocol,
  `InProcessInjector` (tests + in-process scenarios), and
  `HttpInjector` (production OpenAI-style endpoints).
- Pluggable detector framework with metadata enforcement,
  `co_fires_with` correlation hints, and a registry that accepts
  `SASTER-XX` / `SASTER-XX-induced` / `SASTER-XX-both` identifiers
  in `MonitoringConfig(enabled_detectors=[...])`.

#### Reference scenarios

- `carl/run_recon.py` — Carl 2a direct-pipeline simulation. 23
  captured events with three recon side-channels at turns 5, 11,
  17 firing SASTER-26 + SASTER-33 in canonical co-fire.
- `carl/run_exfil.py` — Carl 2b direct-pipeline simulation. 21
  captured events with one exfil POST at turn 8 firing SASTER-31.
- `carl/server.py` — Carl HTTP server with server-side session
  state and configurable hidden directive. Calls a real upstream
  LLM so the induced-detector verification path exercises
  realistic LLM-shaped responses, not canned strings. Four
  directives: neutral, `semantic_recasting` (susceptible to
  SASTER-18-induced), `jitor_susceptible` (susceptible to
  SASTER-24-induced), `recon_emitter` (Carl 2a-shape via LLM).
- `scripts/phase4_calibration.py` — end-to-end integration test
  that runs both induced detectors against three live Carls with
  the production sentence-transformer embedder + real upstream
  Llama.
- `scripts/phase6_demo_log.py` — exercises all six v0.1.0
  reference cases and captures `docs/demo-log-v0.1.0.txt` as the
  demo backup artifact.

#### Documentation

- [`docs/methodology.md`](docs/methodology.md) — ADR concept, why
  wire-level rather than LLM-level, where it fits in your
  security stack alongside WAF / EDR / SIEM / DLP.
- [`docs/har_import.md`](docs/har_import.md) — offline HAR audit,
  privacy / consent, redaction model, session correlation
  strategies.
- [`docs/pattern-authoring.md`](docs/pattern-authoring.md) — the
  Carl 2b → SASTER-31 decision-tree walkthrough; the SASTER-18
  threshold-tuning narrative; how to author new detectors,
  including the induction-mode operational notes (180-s timeout,
  explicit susceptibility encoding).
- [`docs/decision-trees.md`](docs/decision-trees.md) — per-pattern
  decision trees, disambiguation table, co-firing reference.
- [`docs/contribution.md`](docs/contribution.md) — PR workflow,
  code style, Candidate-pattern submission process.
- [`SKILL.md`](SKILL.md) — operational guide for Claude Code /
  Codex / Cursor users.

### Phase 6 verification record

From a fresh-clone-equivalent against live Llama-3.3-70B:

| Check | Result |
|---|---|
| `pytest tests/ -q` | 152/152 pass |
| `ruff check` | clean |
| `mypy --strict` | clean across 30 source files |
| `scripts/phase4_calibration.py` | PASS — SASTER-18-induced margin +0.400, SASTER-24-induced margin +0.119 |
| `saster-har` redaction sentinel | zero matches across `Bearer eyJ`, `sk-`, `session=`, `X-API-Key`, JWT, SSN patterns |
| `scripts/phase6_demo_log.py` | PASS — all 6 reference cases produce expected fire/no-fire behaviour |

### Five-minute validation

```bash
git clone https://github.com/agentsattack/saster-harness.git
cd saster-harness
pip install -e ".[dev]"
python -m carl.run_recon
```

Expected output: three SASTER-26 + SASTER-33 co-firings at turns 5,
11, 17 with the trace ending `OK — Carl 2a recon scenario fired
SASTER-26 + SASTER-33 as expected.`

### Known limitations

- **SASTER-22** (Cross-Model Compositional Weaponization) is not
  shipped in v0.1. Detection requires multi-session action-graph
  reasoning that is roadmap work (v0.3 target).
- **PROBE mode** is a logged no-op in v0.1. Scheduled SASTER-derived
  probe generation ships in v0.2. The API surface is stable;
  calling `start()` in PROBE mode behaves as OBSERVE with a
  warning log line.
- **HAR import under-fires SASTER-26 and SASTER-33.** Those
  patterns target side-channel calls the agent makes from its
  own process; those don't pass through the browser and aren't
  in the HAR. Use live mitmproxy for full coverage.
- **SASTER-31** fires on legitimate PII pipelines by design. The
  v0.1 detector cannot distinguish authorised batch upload from
  exfil; mitigation is operator-side allow-listing at the
  webhook sink.
- **SASTER-18** is the highest-FP-risk detector in the set.
  Translation, summarisation, and intentional jargon-simplification
  fire by the retention heuristic. Deploy with a manual-review
  workflow during initial baselining.
- **SASTER-24** ships with lower recall than research-grade
  implementations — domain-specific anchors were stripped to keep
  the detector generic across deployments.
- **`HttpInjector` default timeout (30s) is too tight for
  induction-mode probes** against LLM-shaped agents. Use
  `HttpInjector(timeout=180.0)` for any probe path you hand to an
  induced detector. v0.2 will add a separate `induction_timeout`
  parameter with this default.

Detailed false-positive surfaces are documented in each detector
module docstring; see `docs/decision-trees.md` for the
disambiguation reference.

### Roadmap

- **v0.2** — `SingleTurnInductionDetector` / `ScenarioInductionDetector`
  split, separate `induction_timeout` on `HttpInjector`, formal
  susceptibility-encoding contract, detector calibration toolkit,
  more T3 detectors, live dashboard reference, PROBE-mode
  scheduler, embedding-similarity check for SASTER-18.
- **v0.3** — multi-agent correlation, action-graph reasoning for
  SASTER-22 / full SASTER-31.
- **v0.4** — PROBE-mode generators auto-derived from SASTER
  pattern definitions; complete INDUCE-mode adversarial probe
  library.

### Citation

If you use saster-harness in academic or professional work:

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

### Acknowledgements

- SASTER taxonomy maintainers — for the open catalog of agentic
  failure modes the harness detects against.
- ProxyGAP research line — for the original SASTER-24, SASTER-26,
  and SASTER-33 regex sources, ported here with domain bias
  removed for general-deployment use.
- LayerOne 2026 program committee — for the talk slot that
  motivated the public release timing.

---

**License:** MIT.
**Maintainer:** Larry Suto, `larry@stratdatsec.com`.
**Issues + discussion:** [github.com/agentsattack/saster-harness/issues](https://github.com/agentsattack/saster-harness/issues).
