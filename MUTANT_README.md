# Mutant C11

Hand-reintroduced in the same function (a clean revert of fix `0e5cd4b` conflicts with code that moved on).

**What:** the Python Rego mirror answers under an OPA/real label.
**Wrong number:** every L2 verdict in a corpus labelled real came from the mirror; the P16 OPA/mirror divergence is invisible.
**Right number:** OPA is the backend when present; the mirror is a test oracle and is labelled representative.
**Fix commit:** `0e5cd4b`.
**Diff size:**  1 file changed, 3 insertions(+), 5 deletions(-).
