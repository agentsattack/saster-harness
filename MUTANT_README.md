# Mutant C7

Hand-reintroduced in the same function (a clean revert of fix `eb4c84f` conflicts with code that moved on).

**What:** the scorer renders the prefix without the tools array the agent sampled with.
**Wrong number:** every envelope conditioned on a prefix the agent never held (W7b/W9).
**Right number:** the rendered prefix is the agent's, tools and template kwargs included.
**Fix commit:** `eb4c84f`.
**Diff size:**  1 file changed, 1 insertion(+), 1 deletion(-).
