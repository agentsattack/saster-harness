# Mutant D18

Clean revert of the CODE side of fix `b26e2cd`; conflicts confined to docs/tests/runs were resolved to HEAD. Reported in the D table only — a defect the new suite found is killed by it tautologically.

Files: carl_ops_agent/capabilities.py saster_defense/l1_classifier.py saster_defense/manifest.py saster_instrument/registry.py scripts/run_cell_w9.py scripts/run_sweep_w24.py
Diff size:  6 files changed, 5 insertions(+), 59 deletions(-)

Direction and false assumption: docs/defect-log.md row D18.
