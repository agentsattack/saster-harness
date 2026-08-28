# Per-trial trajectory-record assembly — W6, not yet built

This note records a deliberate gap between components. It is not a bug and not
an oversight; it is unbuilt work with a clear owner.

## The gap

The frozen public record has two shapes (`saster.trajectory.v1`, see
`carl_ops_trajectory/schema.py`):

- **event records** — one per event on one plane. The victim deployments
  emit these today: `saster_harness.victim_agent.VictimAgent.records()`
  returns model-plane completions, tool-plane steps, and integrity events,
  each a valid event record.
- the **per-trial trajectory record** — one per trial, carrying budget, the
  detection list, the oracle block, the five markers, the terminal-outcome
  class, and the scoring keys.

Nothing currently assembles the second from its inputs. The trajectory record
is a *join* across three components that do not know about each other:

1. the **event records** emitted by the victim deployment (this branch);
2. the **oracle verdict** — `carl_ops_oracle` emits `breach`,
   `breach_step_index`, the primary invariant, `invariants_fired`, and
   snapshot hashes (the oracle block takes the hashes and verdict fields
   only, never the reasons);
3. the **marker layer** — `onset_dist`, `explanatory_divergence`,
   `point_of_no_return`, `breach_step_index`, and first-detection step, none
   of which the victim or the oracle computes on its own.

Joining these into one validated trajectory record — reconciling
`markers.breach_step_index` with the oracle's, deriving the terminal-outcome
class, computing containment latency with right-censoring, and populating the
budget and detection blocks — is **W6's responsibility**. It is not built on
this branch, and no component here should grow it implicitly.

## Why it is parked, not stubbed

A half-built assembler that silently emitted partial trajectory records would
be worse than none: the corpus is public and consumers key on validity, so a
record must be assembled with all three inputs present or not at all. Until
W6, the pieces stay separate and individually valid.

## What exists to build on

- Event records: `VictimAgent.records()` (schema-valid, one clock kind per
  record).
- Snapshot hashes for the oracle block: `CarlOps.snapshot_hashes()`.
- Oracle verdict fields: `carl_ops_oracle` (see that package's report).
- The record contract and every semantic rule the assembler must satisfy:
  `carl_ops_trajectory/schema.py` plus `tests/test_carl_ops_trajectory.py`.
