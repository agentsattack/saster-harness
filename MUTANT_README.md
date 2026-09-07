# Mutant C4 — W9: the scorer must render the prompt the agent sampled

Reintroduces the defect of catalogue row C4 by reverting ONLY the code side of fix commit `562ac77` (tests, docs and runs left at HEAD).

Files: carl_ops_envelope/chat_scorer.py 
Diff size:  1 file changed, 12 insertions(+), 35 deletions(-)

Wrong number, right number and direction: docs/catalogue-provenance.md row C4.
