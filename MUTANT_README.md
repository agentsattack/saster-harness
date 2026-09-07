# Mutant C9 — W21: carl-ops is SASTER-31, not SASTER-24 — corrected at the source, records a

Reintroduces the defect of catalogue row C9 by reverting ONLY the code side of fix commit `68a3085` (tests, docs and runs left at HEAD).

Files: scripts/run_cell_w9.py scripts/run_pilot_w6c.py 
Diff size:  2 files changed, 3 insertions(+), 30 deletions(-)

Wrong number, right number and direction: docs/catalogue-provenance.md row C9.
