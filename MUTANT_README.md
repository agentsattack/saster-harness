# Mutant C1

Hand-reintroduced in the same function (a clean revert of fix `c367b14` conflicts with code that moved on).

**What:** the auditor's prompt mode does not follow the checkpoint — every head is asked the fine-grained question, so the binary head answers with a taxonomy group header and the layer records unavailable on every trajectory; the manifest label is untouched.
**Wrong number:** L4 rendered no verdict anywhere (W14: unavailable on every L4-enabled trajectory).
**Right number:** a verdict on 60 of 60 L4-enabled trajectories.
**Fix commit:** `c367b14`.
**Diff size:**  1 file changed, 1 insertion(+), 1 deletion(-)
