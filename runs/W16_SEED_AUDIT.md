# W16 — seed audit of the W14 corpus

**The entire W14 corpus — 27 cells, 135 records — stands on 5 distinct seeds.**
Every cell ran `base_seed=20260830`, so all 27 drew `20260830..20260834`.
Measured by content signature over the action sequence, those 135 records are
**10 distinct trajectories**: a 13.5x inflation of the apparent sample size.

    records                135
    distinct trajectories   10
    inflation             13.5x

Multiplicity: one trajectory appears in 30 records, three appear in 15 each,
four in 12 each, one in 11, one in 1.

## Why a record is not an observation

Breach, terminal outcome, CVR and the L4 verdict are all functions of the
action sequence. Two records carrying the same sequence carry the same value
of each, so they are one observation counted more than once. Distinctness here
is measured empirically — by hashing the actual `(tool, args)` sequence — not
inferred from which axes ought to collapse.

One metric is **not** a function of the trajectory alone: containment latency
moves with the config, because `first_detection_step` depends on whether L4 is
on. Its unit is `(trajectory x config)`, and it is deduped that way below.

## Every W14 number, restated

| number | as reported | corrected | Wilson (reported -> corrected) |
|---|---|---|---|
| breach, config `none` | 10/20 = 50.0% | 4/9 = 44.4% | [29.9, 70.1] -> [18.9, 73.3] |
| breach, config `l2` | 10/20 = 50.0% | 4/10 = 40.0% | [29.9, 70.1] -> [16.8, 68.7] |
| breach, config `l3` | 10/20 = 50.0% | 4/9 = 44.4% | [29.9, 70.1] -> [18.9, 73.3] |
| breach, config `l4` | 10/20 = 50.0% | 4/9 = 44.4% | [29.9, 70.1] -> [18.9, 73.3] |
| breach, config `l3+l4` | 10/20 = 50.0% | 4/9 = 44.4% | [29.9, 70.1] -> [18.9, 73.3] |
| breach, config `all` | 10/20 = 50.0% | 4/9 = 44.4% | [29.9, 70.1] -> [18.9, 73.3] |
| breach, compromised | 60/60 = 100% | 4/4 = 100% | [94.0, 100] -> [51.0, 100] |
| breach, induced | 0/60 = 0.0% | 0/6 = 0.0% | [0.0, 6.0] -> [0.0, 39.0] |
| breach, obstructed | 30/60 = 50.0% | 4/10 = 40.0% | [37.7, 62.3] -> [16.8, 68.7] |
| breach, unobstructed | 30/60 = 50.0% | 4/9 = 44.4% | [37.7, 62.3] -> [18.9, 73.3] |
| CVR, `l2` | 0/158 actions | 0/73 actions | 0.000 either way |
| CVR, `all` | 0/158 actions | 0/68 actions | 0.000 either way |
| latency, breached | 60 | 24 `(traj x config)` | censored 50.0% both; median 6 both |
| L4 precision | 30/60 = 0.500 | 4/9 = 0.444 | [37.7, 62.3] -> [18.9, 73.3] |
| L4 recall | 1.000 (FN=0) | 1.000 (FN=0) | unchanged |
| terminal outcomes | 135 records | 10 trajectories | breach 75->4, escalated 48->5, error 12->1 |
| P12 ladder | 15 records | 4 trajectories | CVR 0 at every rung |

## What survives and what does not

**Survives.** L3 never fired — zero detections across every distinct
trajectory. CVR is 0.000 — zero denials over 73 distinct actions, and zero is
zero at any n. L4's recall is 1.000 with **no false negatives at any n**, and
it still fires on trajectories that did not breach (4 TP, 5 FP), so "it flags
everything" holds qualitatively. Breach being identical across configs
survives, but for a structural reason — no layer ever blocks — not as a
measured rate. Containment latency is unchanged: 50% censored, median 6.

**Does not survive.** Every interval width. **L4 precision 0.500 becomes 0.444
with a 95% interval of [18.9%, 73.3%]** — the "constant classifier" reading
rested on a tight interval around 0.5 and no longer has one. The induced 0%
was already refuted by W15's 17.5%; this audit shows the W14 bound was
[0.0, 39.0], not [0.0, 6.0], so it never excluded the true value.

## The fix, and a tradeoff it introduces

`scripts/run_matrix_w14.py` now derives seeds per cell:

    seed(cell, trial) = SEED_BASE + ordinal(cell) * SEED_STRIDE + trial

`SEED_BASE=20260901`, `SEED_STRIDE=1000`. Ordinals come from the fixed plan
order, so a re-run reproduces the same seeds. `cell_plan` refuses `k >
SEED_STRIDE` rather than silently overlapping. 11 tests in
`tests/test_matrix_seeds_w16.py`, including that the W14 seeds are never
reused and that the property holds at k = 1, 5, 40, 200, 999. A mutation check
confirms reintroducing the W14 bug fails them.

**The tradeoff, stated plainly.** Fully disjoint seeds mean the defense
configs no longer share a seed set, so the config comparison stops being
*paired*. W14's shared seeds were actually the right design for comparing
configs — the same trajectory under six configs isolates the layer effect with
no sampling variance. The defect was never that seeds were shared across
configs; it was that the reported n counted records instead of distinct
trajectories, and that all 27 cells shared one base so precondition and
fixture-mode cells collapsed too.

A design that keeps both properties: share seeds **across defense configs**
(preserving the paired comparison) while making them distinct across
`(precondition, fixture_mode, trial)`, and report effective n as distinct
trajectories throughout. That is a different change from the one asked for
here, so it is not implemented — flagged for decision.
