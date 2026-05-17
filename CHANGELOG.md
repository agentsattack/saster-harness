# Changelog

All notable changes to `saster-harness` are recorded here. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Planned for v0.2

- **Split `InductionDetector` into `SingleTurnInductionDetector` and
  `ScenarioInductionDetector`** with distinct contracts. v0.1's
  `InductionDetector` was designed around SASTER-18-induced's
  single-turn baseline + reframings shape; SASTER-24-induced needed
  multi-turn scenarios (baseline + redefinition + follow-up) and
  ships in v0.1 with compat-shim placeholders for the abstract
  methods (`baseline_prompt` / `induction_strategy` /
  `divergence_score`) it doesn't really use. The type signature is
  currently lying about the contract — future contributors extending
  `InductionDetector` for a new pattern will hit a footgun. The v0.2
  split makes the two shapes first-class and the signatures honest.

## [0.1.0] — 2026-05-23

Initial public release accompanying the LayerOne 2026 talk on Agentic
Detection and Response (ADR).

### Added

#### Core framework
- `MonitoringHarness` orchestrator with three operating modes: `OBSERVE`
  (passive wire capture, default), `PROBE` (logged no-op in v0.1; full
  implementation is roadmap work), and `INDUCE` (active adversarial
  testing, gated behind `allow_induce=True`).
- Wire-level HTTP/HTTPS capture via embedded mitmproxy `DumpMaster`.
- Per-session embedding baseline using
  `sentence-transformers/all-MiniLM-L6-v2` (~90 MB, lazy-loaded).
- `HttpJsonAdapter` for OpenAI-style chat completion traffic, with
  fallback shapes for `prompt`/`response`, `question`/`answer`, and
  generic JSON content fields.
- `DetectionEvent` schema with JSON serialisation and webhook
  dispatch (httpx-based, fire-and-forget).
- `SasterDetector` abstract base class with `__init_subclass__`
  metadata enforcement and `_build_event()` helper.

#### Detectors — seven SASTER pattern detectors

Tier 3 (Epistemic Exploitation):
- **SASTER-18** — Semantic Recasting (distinctive-term retention
  heuristic, 20% threshold).
- **SASTER-24** — Just-in-Time Ontological Reframing / JiTOR (three
  orthogonal regex sub-patterns: reject-then-pivot, equivalence-as-
  pivot, mathematical-identity-pivot).
- **SASTER-31** — Compositional Capability Emergence / CCE (wire-
  format signature: record-list shape + sensitive-field-name
  intersection on POST/PUT/PATCH bodies).

Tier 4 (Infrastructure and Reconnaissance):
- **SASTER-26** — Recon-Gated Injection / RGI (regex over four recon
  surfaces: compute, identity, pipeline, observability).
- **SASTER-27** — Detection Layer Injection / DLI (three signatures:
  zero-width Unicode, fake verdict strings, fake reasoning blocks
  with classifier-targeting vocabulary).
- **SASTER-28** — Salience Suppression Exfiltration / SSE (co-
  occurrence: creative-frame anchor + retrieval-target reference).
- **SASTER-33** — Context Stripping (per-session structural baseline
  on `role:system` message presence).

Each detector module quotes its canonical SASTER.md definition
verbatim, documents operational shape at the wire level, lists
tunables, and enumerates known false-positive cases.

#### Reference scenarios
- `carl/run_recon.py` — Carl 2a simulation. Twenty-three captured
  events with three recon side-channels at turns 5, 11, 17 firing
  SASTER-26 and SASTER-33 in canonical co-fire.
- `carl/run_exfil.py` — Carl 2b simulation. Twenty-one captured
  events with one exfil POST at turn 8 firing SASTER-31.
- `carl/carl_agent.py` — canned twenty-turn support-conversation
  data with synthetic test records (fake email/password/SSN values
  on localhost-only endpoints).
- Both scenarios drive the detector pipeline directly without
  requiring a running proxy; exit code 0 on expected outcome,
  exit code 1 on regression.

#### Examples + CLI
- `examples/runner.py` — the 49-line slide-18 quickstart example.
- `examples/carl_config.py` — wire-mode config for
  `python -m saster_harness --config …`.
- `python -m saster_harness` and `saster-harness` console script
  entry point (Click-based).

#### Documentation
- `README.md` — install, 5-minute quickstart, full detector list,
  BibTeX citation block.
- `docs/methodology.md` — ADR concept, wire-level rationale,
  session baseline, position in security stack, design philosophy
  on deployment-tuned vs generic detectors.
- `docs/pattern-authoring.md` — Carl 2b → SASTER-31 decision-tree
  walkthrough; SASTER-18 threshold-tuning narrative as FP-analysis
  methodology template; how to author new detectors.
- `docs/decision-trees.md` — per-pattern decision trees,
  disambiguation table, co-firing reference.
- `docs/contribution.md` — PR workflow, code style, test
  requirements, Candidate pattern submission process.
- `carl/README.md` — simulation disclaimer and scenario index.

#### Tooling
- `pyproject.toml` — hatchling build, declared dependencies
  (mitmproxy ≥10, sentence-transformers ≥2.5, numpy ≥1.24,
  pydantic ≥2, httpx ≥0.25, click ≥8.1), dev extras
  (pytest, mypy, ruff).
- `tests/` — 40 tests: 21 detector tests (positive + negative per
  pattern), 4 Carl scenario integration tests, 6 framework smoke
  tests, 7 parametrised empty-turn safety checks, 2 SASTER-33
  baseline edge cases.
- `.github/workflows/test.yml` — CI matrix on Python 3.10 / 3.11 /
  3.12 running ruff + mypy + pytest.

### Known limitations

- **SASTER-22 (Cross-Model Compositional Weaponization) is not
  shipped in v0.1.** Detection of this pattern requires multi-session
  action-graph reasoning that is out of scope for a wire-only
  detector. Roadmap target: v0.3. Practitioners who observe the
  pattern in production should correlate manually via the SIEM that
  receives `saster-harness` webhook events.
- **`PROBE` mode is a logged no-op in v0.1.** Scheduling synthetic
  SASTER-derived probes is roadmap work (v0.2). The mode is
  declared so the public API surface is stable; calling
  `start()` with `mode=HarnessMode.PROBE` runs OBSERVE-equivalent
  behavior with a warning log line.
- **SASTER-31 fires on legitimate PII pipelines by design.** The
  detector cannot tell authorised batch upload from unauthorised
  exfil; legitimate cohort-analytics pipelines that POST emails to
  a metrics endpoint will produce events. Mitigation is operator-
  side allow-listing at the webhook sink.
- **SASTER-18 is the highest-FP-risk detector in the set.**
  Translation agents, summarisation agents, and intentional jargon-
  simplification all fire by the distinctive-term-retention
  heuristic. Deploy with a manual-review workflow for the first
  weeks; tune the threshold against your traffic.
- **SASTER-24 has lower recall than research-grade implementations.**
  Domain-specific anchors (the ProxyGAP rocket/aerospace vocabulary)
  were stripped to keep the detector generic. Reframe attacks that
  don't carry an explicit refusal clause + equivalence claim in
  the same response will be missed by pattern 1; patterns 2 and 3
  have a higher false-positive rate on legitimate technical
  responses.
- **mitmproxy embeds PEP 695 syntax in its internals.** mypy
  follow-imports is set to `skip` for `mitmproxy.*` to keep type
  checking clean across the 3.10+ Python target. This is a build-
  configuration concern, not a runtime issue.

### Acknowledgements

- SASTER taxonomy maintainers — for the open catalog of agentic
  failure modes that the harness detects against.
- ProxyGAP research line — for the original SASTER-24, SASTER-26,
  and SASTER-33 regex sources, ported here with domain bias
  removed.
