# Mutant C5

Hand-reintroduced in the same function (a clean revert of fix `385329e` conflicts with code that moved on).

**What:** every cell of every stratum replays the same base seed.
**Wrong number:** 0/60 induced divergence reported where the corpus held 5 distinct trajectories: really 0/5 (W15/W16).
**Right number:** paired seeds per stratum, disjoint across strata.
**Fix commit:** `385329e`.
**Diff size:**  1 file changed, 2 insertions(+), 2 deletions(-).
