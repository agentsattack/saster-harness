# Mutant C3

Hand-reintroduced in the same function (a clean revert of fix `479fe5a` conflicts with code that moved on).

**What:** summed per-token logprob instead of the mean: short candidates win.
**Wrong number:** SUM saturates Qwen to entropy 0.000 (W13).
**Right number:** mean per-token logprob, the pre-registered method.
**Fix commit:** `479fe5a`.
**Diff size:**  1 file changed, 1 insertion(+), 1 deletion(-).
