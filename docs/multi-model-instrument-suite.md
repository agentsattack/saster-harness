# Multi-model instrument-validity suite — 10-node GB10 design

Companion to `instrument-test-plan.md`. That document catches defects with
rejection tests. This one catches them with COMPARATORS, which is what the
title says bespoke pipelines lack. Ten nodes buy three comparator types:
model families as instrument replicates, detector panels as second
opinions, judge panels as a variance decomposition. None requires a second
harness.

Principle: a real measurement varies with the model. An instrument
artifact does not. Cross-model invariance is a defect signal.

---

## Arm A — Cross-model invariance (the degeneracy detector)

Catalogue classes: C3, C4, C6, C8, C10.

Design
- Add victim families to the `VictimAgent` registry: four families with
  DISTINCT tool-call template conventions (candidates: Llama 3.x, Qwen 3,
  Mistral, Gemma 3 — verify each serves on SM120 with all three logprob
  channels intact before it enters the registry). Two sizes per family
  where memory allows; a 70B-class at 4-bit fits one node, larger models
  tensor-parallel across two nodes on the 200G fabric.
- Do NOT run the full ablation matrix per family. The invariance test
  needs one config (all-on), obstructed arm only, two SASTER categories,
  k=5. That is a ~40-campaign sub-arm per family, not a re-sweep.

Tests
- `test_metric_varies_across_families`: for every registered metric and
  every (campaign, step) cell, values identical to 6 decimals across ≥3
  families → `SuspectedInstrumentArtifact`. Positive control: mutants C3,
  C4, C6 and C10 must all trip it (they are model-invariant by
  construction). Negative control: `surprisal` must NOT trip it.
- `test_template_roundtrip_per_family`: the emitted tool call is present
  at AST level in the scorer's rendered prompt, parametrized over every
  family's chat template. C4 was a single-template defect; a scorer that
  works for one template and silently drops the call for another is the
  same defect with a family index. This is the test most likely to find
  something new.
- `test_logprob_channel_agreement_per_family`: surprisal computed via
  completions `logprobs`, chat `top_logprobs`, and echo teacher-forcing
  must agree within tolerance for the SAME action, per family. C7/C8 were
  channel-confusion defects; families differ in which channel is faithful.
- Variance-structure check: for each metric, report between-family and
  within-family (k-trial) variance. Zero both → degenerate. Zero between,
  nonzero within → a metric that isn't measuring the model — suspicious,
  report it.

Talk output: a heatmap, metric × family, of "did this number move." The
degenerate rows are the catalogue rediscovered by a machine.

---

## Arm B — Detector panel (second opinions for L4)

Catalogue classes: C1, C2, C11. Also the comparator argument in §1.

Design
- Run every available trajectory-level auditor over the IDENTICAL corpus:
  AgentDoG 1.0-4B, AgentDoG 1.5-4B (both anchored), LlamaGuard as a
  trajectory scorer (published 6.8% recall — a known-weak comparator is
  still a comparator), plus any other auditor with a published,
  reproducible benchmark. Verify each has a trajectory mode and a public
  held-out set BEFORE adding it; a detector with no anchor is a subject,
  not a comparator.
- Every detector runs through the same hardened wrapper with the 16-row
  degenerate-input matrix. Co-host on two nodes as ATOM already does;
  respect the global `gpu_memory_utilization` watermark rule.
- Post-hoc only. No re-sweep. Trajectories under 16k tokens serialized;
  over-ceiling records score `unavailable` for every detector and are
  reported as a count.

Tests
- Silent-default outlier: per detector, `clean` rate per corpus. A
  detector whose clean rate is >2σ above the panel median on the same
  records is flagged — this is C1 made visible by disagreement rather
  than by reading.
- Anchor table per detector: reproduce each published number on its own
  benchmark. Report "n comparators, m surfaced a harness defect." One
  already did (6,000-char truncation). The count is the §1 argument.
- Agreement matrix: pairwise Cohen's κ and panel Krippendorff's α per
  corpus. Expect low α on carl-ops (out-of-distribution for all of them);
  report it as a property of the corpus, not a flaw in any detector.
- Panel-vs-oracle: each detector's verdict against the containment
  oracle's `breach`. Specificity per detector on the legitimate-completion
  negative controls. The "specificity 0.000" line becomes a column, with
  the qualifier built into the table.

Talk output: the agreement matrix, the anchor table with a "caught
something?" column, and the clean-rate outlier plot.

---

## Arm C — Judge variance decomposition (Messing, on your corpus)

Catalogue class: none directly — this is the complement. It measures the
variance that CIs ignore and shows that instrument bias lives outside it.

Design
- LLM-judge panel over the corpus, scoring the same thing the
  deterministic markers score (`explanatory_divergence` step,
  breach-or-not). Crossed design: J judges (≥3 families, one served
  tensor-parallel if large) × T temperatures (0, 0.3, 0.7) × P prompt
  paraphrases (3, authored blind under the exclusion discipline) × R
  repeats. ~27 judge configurations per record.
- Fit a crossed random-effects model: judge, prompt, temperature,
  judge×prompt. Report naive SE vs total-error SE on the headline breach
  rate and on step attribution. This reproduces Messing's finding on an
  agent-safety corpus, which nobody has done.
- THE TWIST: run the identical judge panel over one MUTANT corpus (C6,
  latency zero). Every judge configuration's CI contains the wrong number.
  Variance modelling, done correctly, cannot see instrument bias. That is
  the one slide that separates this talk from arXiv:2604.11581 rather
  than restating it.

Tests
- `test_judge_marker_agreement` (P13): agreement between judge panel and
  deterministic markers, degrading with step-attribution granularity.
  Pre-registered; already in the matrix.
- `test_ci_coverage_on_mutant`: for each mutant corpus, fraction of judge
  configurations whose CI covers the TRUE value (from the corrected
  corpus). Expected ≈ 0 for bias mutants. That number goes on the slide.

Talk output: naive vs corrected SE bar; coverage-on-mutant table.

---

## Arm D — Mutation score × family

Catalogue: all. Extends Protocol A.

- Re-run the mutation score with the test tree against each family's
  sub-arm corpus. Some mutants are family-conditional (C4 depends on the
  chat template; C7 on which channel the scorer read). Report a
  mutant × family kill table. A mutant killed under one family and
  surviving under another is a NEW finding: instrument defects that are
  only visible with the right model in the loop.
- Cheap: mostly re-scoring. C7-class mutants need re-sampling because they
  change what the agent sees; budget those.

---

## Arm E — Serving-stack fidelity

Catalogue: the FLORES-200 case (BLEU halving on serving stack alone), and
your own digest-mismatch scare.

- All nodes are digest-identical now. Deliberately break that for ONE
  family: serve the same weights on two vLLM versions (the two digests you
  already have pinned) and compare surprisal, refusal_prob and
  envelope_mass on identical prefixes. A metric that moves with the
  serving stack and not the model is an instrument property.
- Test: `test_metric_stable_across_serving_digest` with a pre-registered
  tolerance. Failure is a finding, not a bug.
- One node, one afternoon, one slide.

---

## Node allocation (10 nodes, 200G fabric)

| Node | Role | Notes |
|---|---|---|
| spark1 | control, router, Ray head, corpus assembly | serves nothing; corpus lands on NAS not node SSD |
| spark2–spark5 | victim families A–D | one family per node; TP-pair two nodes for a large model when needed |
| spark6–spark7 | detector panel | co-hosted per the ATOM watermark rule; AgentDoG ×2 + LlamaGuard + others |
| spark8–spark9 | judge panel | one large judge TP across both, or two mid judges at three temps each |
| spark10 | envelope-mass scoring / flex | the ~13-evaluations-per-step arm is the likeliest bottleneck; isolate it |

Sticky-session front door stays; prefix cache is the whole game for k=5
and the envelope arm. Nothing memory-hungry beside a detector node.

Rough scale: GrrCON matrix on two victims is the baseline. Arm A adds ~40
campaigns × 2 extra families. Arms B, C, E are re-scoring: bounded by
corpus size × panel size, no new trajectories. Arm C is the expensive one
at ~27 judge calls per record; run it on a stratified sample if the full
corpus doesn't fit the window.

---

## Sequencing against the calendar

Sep 1–21: GrrCON sweep owns the cluster. Two things ride along at zero
sweep cost — add the extra families to the victim registry NOW so Arm A's
sub-arm runs inside the same campaign runner, and write the per-family
template round-trip test before the pilot (it may change which family
goes on stage).

Sep 22–25: GrrCON. Cluster idle → run Arms B and E unattended; both are
post-hoc and scripted. `rack-down.sh --if-idle` when they finish.

Sep 26–29: Arm C on a stratified sample, Arm D re-scoring, analysis
scripts, slides. Arm C on the full corpus and the second-harness port
(below) are post-slides if at all.

---

## The one thing this doesn't do

None of the five arms is a second implementation of the HARNESS. The
honest ceiling of this design: replicated models, panelled detectors, and
decomposed judges catch every class in the catalogue except a defect that
sits between the fixture and the sampler and is invariant to everything
downstream. Porting carl-ops to a public harness (inspect_ai or similar)
and comparing headline numbers is the only comparator for that class. It
is a week of work and belongs after October, but say on the slide that it
is the missing arm, and why.
