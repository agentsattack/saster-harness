# Mutant D14

Clean revert of the CODE side of fix `c243332`; conflicts confined to docs/tests/runs were resolved to HEAD. Reported in the D table only — a defect the new suite found is killed by it tautologically.

Files: carl_ops_agent/widening.py carl_ops_assembly/assembler.py carl_ops_trajectory/schema.py scripts/run_sweep_w24.py
Diff size:  4 files changed, 16 insertions(+), 23 deletions(-)

Direction and false assumption: docs/defect-log.md row D14.
