# Incident mapping — autonomy tells vs. SASTER patterns (stub)

> **Status: stub.** This maps *autonomy indicators* from a public incident
> post-mortem to SASTER patterns. Autonomy tells are behavioral
> **symptoms of an agent acting on its own**, not attack **mechanisms**.
> They are deliberately kept out of the SASTER taxonomy and out of the
> [coverage table](../README.md#coverage-across-the-saster-taxonomy):
> a tell is not a pattern and must not inflate the "9 of 32" figure.

## Source

CSA Hugging Face CISO Post-Mortem — Knostic / CSA / SANS et al.,
**DRAFT v0.8, 27 Jul 2026, CC BY-NC 4.0**.
<https://cloudsecurityalliance.org/artifacts/hugging-face-ciso-post-mortem>

Cite the version and date; this is a draft, not a final publication.

## Section IV autonomy tells → nearest SASTER pattern(s)

These are the post-mortem's "how you could tell it was an autonomous
agent, not a human" indicators. The mapping is *associative* — which
SASTER pattern's detection surface an operator might correlate a tell
with — not a claim that the tell *is* the pattern.

| Autonomy tell (post-mortem §IV) | Associated SASTER surface (not equivalence) |
|---|---|
| Repeat-successful-attempts bias (retries a working action far past a human's patience) | Behavioral-anomaly / drift-composite signal; no single pattern |
| Brilliant-then-basic actions (expert exploitation interleaved with naive mistakes) | No SASTER pattern — capability-profile tell only |
| Paths no human would take (action sequences off any human workflow) | Correlates with SASTER-11 / SASTER-14 trajectory drift as an *indicator*, not the mechanism |
| Superhuman speed / cadence | Out of taxonomy scope — infrastructure/telemetry signal |

## Why this is a stub

Section IV is summarized from the draft, not reproduced. When the
post-mortem finalizes, replace the paraphrased tells with the published
wording and revisit the associations. Do not promote any row here into a
SASTER pattern or a detector coverage claim without a distinct attack
mechanism and detection signal.
