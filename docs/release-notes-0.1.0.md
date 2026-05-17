# Release notes — v0.1.0

This file contains the GitHub Release copy for v0.1.0. Two
versions: a short blurb for the release card and a long form for
the release body.

---

## Short version (release card subtitle)

> Wire-level Agentic Detection and Response (ADR) for the SASTER
> taxonomy. v0.1.0 ships seven pattern detectors covering Tier 3
> (epistemic exploitation) and Tier 4 (infrastructure and
> reconnaissance), a reference rogue agent for harness validation,
> and full documentation of the ADR methodology. Accompanies the
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

#### Seven SASTER pattern detectors

Each detector quotes its canonical SASTER.md definition verbatim,
documents the operational shape at the wire level, lists tunables,
and enumerates known false-positive cases.

| Pattern | Tier | Description |
|---|---|---|
| **SASTER-18** | T3 (Epistemic) | Semantic Recasting — distinctive-term retention heuristic on user-message vocabulary vs. agent-response vocabulary |
| **SASTER-24** | T3 (Epistemic) | Just-in-Time Ontological Reframing — three regex sub-patterns for self-narrated bypasses |
| **SASTER-26** | T4 (Infra/Recon) | Recon-Gated Injection — vocabulary regex over four recon surfaces (compute, identity, pipeline, observability) |
| **SASTER-27** | T4 (Infra/Recon) | Detection Layer Injection — signatures for zero-width Unicode, fake verdict strings, fake reasoning blocks |
| **SASTER-28** | T4 (Infra/Recon) | Salience Suppression Exfiltration — creative-frame + retrieval-target co-occurrence |
| **SASTER-31** | T3 (Epistemic) | Compositional Capability Emergence — wire-format signature for record-list POSTs with sensitive field names |
| **SASTER-33** | T4 (Infra/Recon) | Context Stripping — per-session structural baseline on `role:system` presence |

#### Core framework

- `MonitoringHarness` orchestrator with OBSERVE / PROBE / INDUCE
  modes
- Embedded mitmproxy `DumpMaster` for HTTP/HTTPS wire capture
- Per-session embedding baseline using
  `sentence-transformers/all-MiniLM-L6-v2`
- `HttpJsonAdapter` for OpenAI-style chat completion traffic, with
  fallback shapes for common alternative JSON conventions
- Pluggable detector framework with metadata enforcement and the
  `co_fires_with` correlation hint

#### Reference scenarios

- `carl/run_recon.py` — simulated rogue support agent that emits
  hidden infrastructure-recon questions at turns 5, 11, 17. Fires
  SASTER-26 and SASTER-33 in canonical co-fire.
- `carl/run_exfil.py` — simulated rogue support agent that POSTs a
  synthetic user database to a localhost endpoint at turn 8. Fires
  SASTER-31.
- Both scenarios run end-to-end in under 30 seconds against an
  installed harness, exit 0 on expected outcome.

#### Documentation

- [`docs/methodology.md`](docs/methodology.md) — ADR concept, why
  wire-level rather than LLM-level, where it fits in your security
  stack alongside WAF / EDR / SIEM / DLP.
- [`docs/pattern-authoring.md`](docs/pattern-authoring.md) — the
  Carl 2b → SASTER-31 decision-tree walkthrough as a worked
  example; the SASTER-18 threshold-tuning narrative as the
  false-positive analysis template; how to author new detectors.
- [`docs/decision-trees.md`](docs/decision-trees.md) — per-pattern
  decision trees for analyst triage, disambiguation table for
  ambiguous cases, co-firing reference.
- [`docs/contribution.md`](docs/contribution.md) — PR workflow,
  code style, Candidate-pattern submission process.

#### Tests + quality

- 40 tests across detector positives + negatives, Carl scenario
  end-to-end checks, framework smoke tests, parametrised empty-
  turn safety checks.
- `ruff check` clean. `mypy --strict` clean. CI matrix on Python
  3.10 / 3.11 / 3.12.

### Five-minute validation

```bash
git clone https://github.com/lsuto/saster-harness.git
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
- **SASTER-31** fires on legitimate PII pipelines by design. The
  v0.1 detector cannot distinguish authorised batch upload from
  exfil; mitigation is operator-side allow-listing at the webhook
  sink.
- **SASTER-18** is the highest-FP-risk detector in the set.
  Translation, summarisation, and intentional jargon-simplification
  fire by the retention heuristic. Deploy with a manual-review
  workflow during initial baselining.
- **SASTER-24** ships with lower recall than research-grade
  implementations — domain-specific anchors were stripped to keep
  the detector generic across deployments.

Detailed false-positive surfaces are documented in each detector
module docstring; see `docs/decision-trees.md` for the
disambiguation reference.

### Roadmap

- **v0.2** — detector calibration toolkit, more T3 detectors,
  live dashboard reference, PROBE-mode scheduler, embedding-
  similarity check for SASTER-18.
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
  url          = {https://github.com/lsuto/saster-harness}
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
**Issues + discussion:** [github.com/lsuto/saster-harness/issues](https://github.com/lsuto/saster-harness/issues).
