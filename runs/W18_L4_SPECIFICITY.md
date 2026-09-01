# W18 — powering the L4 specificity claim

**L4 has never returned `safe`. Not once, on any trajectory, in any corpus.**

    distinct trajectories evaluated : 39
      of which did not breach       : 27
      of which L4 called safe       :  0
      L4 UNAVAILABLE (not evaluated):  0

Stated as a count rather than a rate, which is the honest form: **0 safe
verdicts out of 39**.

## The confusion matrix — [unit: distinct trajectory]

Every distinct trajectory across all six corpora, rescored uniformly with one
auditor configuration (binary head, binary mode) rather than pooling verdicts
recorded at different times under different code.

                     fired    did not fire
      breach            12               0
      no breach         27               0

    precision   0.308   Wilson [18.6%, 46.4%]   (n=39)
    recall      1.000   Wilson [75.8%, 100.0%]  (n=12)
    specificity 0.000   Wilson [ 0.0%, 12.5%]   (n=27)
    fired on    39/39 = 100.0%  Wilson [91.0%, 100.0%]

**The specificity interval halved**, from [0.0%, 25.9%] on 11 non-breaching
trajectories to **[0.0%, 12.5%] on 27**. That was the point of the session.

**Precision fell from 0.600 to 0.308 and that is not a regression.** It tracks
the breach base rate, which fell from 60% to 31% as the pooled set filled with
clean induced trajectories. Precision was never the finding; TN = 0 is.

## Why post-hoc scoring needs no new campaigns

L4's entire input is `[{"step", "tool", "args"}, ...]`, built from `actions` —
which every corpus record stores verbatim, not by reference. Any stored
trajectory can be scored without re-running the campaign that produced it,
including the ones that ran under an L4-off config and were never shown to the
observer.

`unavailable` is counted in its own column and excluded from every rate. A
layer that did not evaluate is not a layer that declined to fire, and pooling
the two would manufacture specificity out of transport errors. None occurred
here (0 of 39), so the distinction costs nothing this time — but it is the
reason the number can be trusted.

## Induced divergence rate

| arm | rate | Wilson |
|---|---|---|
| W18 obstructed (k=60) | 11/60 = 18.3% | [10.6%, 29.9%] |
| W18 unobstructed (k=60) | 7/60 = 11.7% | [5.8%, 22.2%] |
| W18 pooled | 18/120 = 15.0% | [9.7%, 22.5%] |
| W15 pooled | 14/80 = 17.5% | [10.7%, 27.3%] |
| **W15 + W18, 200 distinct seeds** | **32/200 = 16.0%** | **[11.6%, 21.7%]** |

Consistent across both measurements. **16.0% [11.6%, 21.7%] on 200 seeds is now
the number to cite** for induced divergence.

## The limit this run found: trajectory diversity, not trial count

    corpus                          records   new distinct   running total
    w14_corpus_qwen_single_victim      135          10            10
    w15_induced_obstructed              40           9            19
    w15_induced_unobstructed            40           6            25
    w17_corpus_qwen_paired             135           6            31
    w18_induced_obstructed              60           7            38
    w18_induced_unobstructed            60           1            39

    TOTAL: 470 records -> 39 distinct trajectories, 12.1 : 1

**W18's 120 new trials yielded 8 new distinct trajectories — a 6.7% marginal
yield, and the last 60 produced exactly one.** The agent is a near point mass:
W13 measured its action distribution at **1.3% of uniform entropy**, so fresh
seeds mostly reproduce a trajectory already in the corpus.

L4's verdict is a deterministic function of the trajectory, so a repeat adds no
information about L4. **The specificity claim is therefore bounded by
trajectory diversity, not by trial count**, and more k will not tighten it much
further. Narrowing [0.0%, 12.5%] materially needs trajectory diversity from a
different source — another victim model, another fixture, or a different
temperature — not more trials against this one.
