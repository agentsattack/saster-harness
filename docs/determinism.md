# Determinism: reproducibility vs. timeliness

`saster-harness` is often described as "deterministic." That word bundles
two *independent* properties that must not be collapsed into one, because
they have different truth values across the detector set and one of them
is not yet measured at all.

- **Reproducibility** — does the harness produce bit-identical output
  across runs given pinned inputs? A correctness / auditability property.
- **Timeliness** — how early and how reliably does a detector catch a
  pattern? A measurable performance property (detection latency, TPR/FPR
  at a stated base rate, tokens-saved-style metrics).

Reproducibility says nothing about timeliness. A perfectly reproducible
detector can be slow, late, or miss the pattern entirely. **Do not read
the reproducibility guarantee below as an implicit timeliness claim.**

## Axis 1 — Reproducibility

*Bit-identical output across runs, given pinned inputs* (fixed detector
version, fixed `all-MiniLM-L6-v2` embedder, fixed configuration).

### Passive detectors (7) — reproducible, bit-level

Given identical `TurnData`, each passive detector produces byte-identical
output on every run. The scoring path is pure code plus a deterministic
embedding of fixed input text; no live model is consulted to reach the
verdict.

`SASTER-18`, `SASTER-24`, `SASTER-26`, `SASTER-27`, `SASTER-28`,
`SASTER-31`, `SASTER-33`.

### Induced detectors (6) — NOT reproducible in the same sense

The induced detectors inject probe turns into a **live agent** and score
the agent's *responses*. Those responses vary between runs — sampling
temperature, provider nondeterminism, and silent model rotation behind an
alias all move the elicited text — so the end-to-end verdict is **not**
bit-reproducible.

Their guarantee is **procedural, not bit-level**:

- The probe sequence (baseline prompt, reframings / scenario turns) is
  fixed and the transcript is recorded.
- Re-scoring a *recorded* transcript is bit-reproducible — the scoring
  function itself is pure code.
- But re-running against a live agent can yield a different transcript,
  and therefore a different verdict.

`SASTER-11-induced`, `SASTER-14-induced`, `SASTER-18-induced`,
`SASTER-18-multiturn`, `SASTER-24-induced`, `SASTER-26-induced`.

### The narrower "no LLM decides" claim

"No shipped detector calls an LLM to decide whether a pattern fired"
(`docs/detectors.md`) is true and worth stating — but it is a **weaker**
claim than bit-reproducibility, not a synonym for it. It guarantees the
*scoring function* is deterministic given its inputs. For a passive
detector the input (a captured turn) is fixed, so the whole result is
reproducible. For an induced detector the input (a live agent response)
is not fixed, so the scoring being pure code does not make the result
reproducible.

Reproducibility is a correctness and auditability property. It is not, by
itself, evidence that the harness detects attacks well or early — that is
Axis 2, and it is measured separately.

## Axis 2 — Timeliness

*How early and how reliably a pattern is caught* — detection latency,
true/false-positive rates at a stated base rate, and tokens-saved-style
efficiency metrics.

Timeliness is a **measured** property, reported separately against public
third-party corpora, not asserted here. **No such measurement exists yet
for saster-harness.** This document makes no timeliness claim, and none
should be inferred from the reproducibility guarantee above. When
timeliness numbers are produced, they will cite the corpus, the base
rate, and confidence intervals.

## Summary

| Detector | Mode | Reproducibility |
|---|---|---|
| SASTER-18 | passive | bit-level |
| SASTER-24 | passive | bit-level |
| SASTER-26 | passive | bit-level |
| SASTER-27 | passive | bit-level |
| SASTER-28 | passive | bit-level |
| SASTER-31 | passive | bit-level |
| SASTER-33 | passive | bit-level |
| SASTER-11-induced | induced | procedural (transcript-scoped) |
| SASTER-14-induced | induced | procedural (transcript-scoped) |
| SASTER-18-induced | induced | procedural (transcript-scoped) |
| SASTER-18-multiturn | induced | procedural (transcript-scoped) |
| SASTER-24-induced | induced | procedural (transcript-scoped) |
| SASTER-26-induced | induced | procedural (transcript-scoped) |

Timeliness: not yet measured for any of the above.
