# Mutant C8

Hand-reintroduced in the same function (a clean revert of fix `479fe5a` conflicts with code that moved on).

**What:** the not-computed envelope block reports numbers under status computed: a near-uniform teacher-forced ranking presented as the agent's action distribution.
**Wrong number:** declared_in/out and scored carried numbers describing a distribution the agent does not draw from (W13, 99.0% of uniform entropy vs the agent's 1.3%).
**Right number:** three nulls under envelope_status not_computed (Amendment 9).
**Fix commit:** `479fe5a`.
**Diff size:**  1 file changed, 4 insertions(+), 23 deletions(-).
