# Handoff — novel mutants (Protocol A, step 5), under the exclusion discipline

Written 2026-09-06; rewritten 2026-09-14 (third pass, below). For a separate
session that seeds 5–10 NEW defects into this harness, blind: it has not
seen the catalogue, the defect log, the rejection suite, or any report. The
kill rate on those mutants is the generalization claim for the checklist; a
mutant that reproduces a class named below is not novel and is excluded
when scored.

## What you receive

This file and a copy of the surface under `surface/`, with the repository's
own paths (`surface/saster_defense/...`). Nothing else. You do not have the
repository, its tests, its branches or its data, and you must not look for
them.

## The surface you may read (all of it is under `surface/`)

- `saster_defense/` — the five layers, the OPA and z3 clients, the L1 and
  L4 parsers, the judge, the scope lock, the manifest.
- `carl_ops_envelope/` — the envelope scorers.
- `carl_ops_assembly/assembler.py`, `carl_ops_trajectory/schema.py` — the
  record and its assembly.
- `carl_ops_agent/` — the action plane.
- `saster_instrument/metrics.py` — the metrics.
- `scripts/run_cell_w9.py`, `scripts/run_sweep_w24.py` — the cell runner
  and the sweep driver.
- Spec docs: `docs/grrcon-test-matrix.md`, `docs/envelope-preregistration.md`,
  `docs/instrumentation.md`.

## What you must produce, in this directory

- `mutant_1.patch` … `mutant_N.patch`, N between 5 and 10. Each is a
  unified diff that applies from the repository root with `patch -p1`
  (make it as `diff -ruN surface work_N` after editing a fresh copy of
  `surface/` as `work_N/`). Each is a minimal code change — no test
  edits, no new files — that makes a **wrong number plausible rather than
  an error**: a silent default, a degenerate metric, a denominator, a unit,
  a wrong surface, a label, a scope, a serialization. Keep each mutant to
  one mechanism.
- `NOVEL_README.md`: one paragraph per mutant — the change, the number it
  corrupts, the direction it leans (toward "defense held", away, neutral).
- `HASHES.txt`: `sha256sum` of every patch and the README.
- You do not run any test suite; there is none here. You may run
  `python3 -m py_compile` on edited files.

## What not to reinvent (the exclusion, as classes; do not read further)

The catalogue already holds these classes. A mutant of one of them is not
novel. Named by class and component only:

- Detector wrapper silent default (a head asked the wrong question,
  recorded as clean).
- Truncated verdict (a reply capped before its answer token).
- Length-biased normalization in the envelope scorer.
- Scoring a prefix the agent never held (template kwargs not threaded).
- Denominator inflation by replayed seeds.
- Unit mismatch between action and snapshot index spaces (latency).
- Wrong serving surface (completions where the agent used chat + tools).
- Wrong object reported as a distribution (closed-set ranking).
- A stale label nothing reads.
- A detection entry for nothing real (scope of first detection).
- A stand-in under a real backend's label.
- Undefined or failed backend decision defaulting to allow.
- Truthiness of a non-bool verdict or approver answer.
- Case-folded verdict tokens.
- Endpoint string on the manifest without a real backend behind it.
- Uncounted exceptions in the canary.
- Degenerate distributions returning plausible numbers.
- Parser stripping content the served head never emits.
- An `allow` with no raw reply (unauditable clean class).
- Recorded or excluded heads' labels rejected as non-findings.
- A forced or different realized route dropped as a mismatch.
- Terminal outcome misclassified as error.
- A schema-forbidden detail aborting a cell.
- Static coverage enumerating one value per argument.
- A censored null read as an unpopulated instrument.
- Head-role label disagreeing with the entries.
- Classifier verdicts that change with the rendering of the same action.
- A denied input turn kept in the model's context.
- Argument binding to a signature instead of the schema (null passes).
- Two tables naming one endpoint, one relocated.
- End-of-cell persistence losing completed trials on a transport error.
- A skip condition that tests the router, not the upstream.
- A handoff that over-promises a field's presence.

Also excluded: every file under `tests/`, every `docs/*report*`, `docs/*log*`,
`docs/*findings*`, `docs/*amendments*`, `docs/*catalogue*`, `docs/*mutation*`,
`docs/*survey*`, `docs/*plan*`, `docs/*suite*`, every `runs/`, every
`mutant/*` branch. You have none of them; do not go looking.

## Second pass (2026-09-06)

Re-read against the discipline: the surface list names modules, not the
assumptions inside them; the classes are listed as exclusions, not as
hints; no wrong number appears above; the author is told the *classes*
only through the eight nouns in the deliverable and the class list. One
leak removed: the first draft named a function as a place to look.

## Third pass (2026-09-14)

The first blind session produced nothing. Two causes in the brief: the
exclusion list enumerated 1,243 test ids (a wall the author could neither
use nor check), and the deliverable asked for branches off a repository
branch the author must not have. The exclusion is now the class list
above, under 60 lines, and the deliverable is patch files against an
exported surface. Re-read against the discipline: no test is named; the
classes carry no number and no location; the surface list is unchanged.
