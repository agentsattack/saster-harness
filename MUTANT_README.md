# Mutant C2

Hand-reintroduced in the same function (a clean revert of fix `6281260` conflicts with code that moved on).

**What:** a length-capped (truncated) reply is read as the clean class instead of unavailable.
**Wrong number:** FG head `safe` 5/5 on the reference breach; every truncated reply counted clean (W11/W12).
**Right number:** a truncated reply is unavailable, ran=False.
**Fix commit:** `6281260`.
**Diff size:**  1 file changed, 1 insertion(+), 1 deletion(-).
