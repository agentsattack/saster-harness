# Schema amendments — `saster.trajectory.v1`

Amendments to the frozen record contract in `carl_ops_trajectory/schema.py`,
in order. Every amendment here was made **before any corpus existed**, and
each entry says so explicitly, because "the schema changed" and "the schema
changed after we saw results" are very different claims and a public corpus
has to let a reader tell them apart.

The bar for an amendment is that the *original rule encoded a false
assumption*, not that the rule was inconvenient. Each entry states the
assumption, why it is false, and what replaced it. An amendment that merely
relaxed a constraint to make records validate would be a finding about the
sweep, not a fix to the schema.

Sibling document. `envelope-preregistration.md` is scoped to the
envelope-mass metric — scoring method, candidate set, the three envelopes,
thresholds. It is the pre-registration of one *metric*. This file is the
change log of the *record contract*, which is a different artifact with a
different audience, so amendments live here rather than being appended there.

---

## Amendment 1 — `point_of_no_return` may be 0

**Status:** pre-corpus. Commit `8a4b45a`, 2026-08-29.

**Original rule.** `point_of_no_return` shared the breach-step-index
validator: null, or an integer >= 1. Zero was rejected on the grounds that
index 0 is t0, the pre-action baseline, which cannot itself be a breach.

**The false assumption.** That PONR and a breach index measure the same kind
of thing. They do not. A breach *happens at* a step, so it cannot have
happened at t0. PONR asks a counterfactual question — from which index is the
objective no longer reachable — and the answer can legitimately be "from the
very beginning". Under the obstructed arm the audit endpoint is unavailable,
so the sanctioned completion is never admissibly reachable from t0 and PONR
is 0 for every trajectory in that arm.

**The amendment.** A dedicated `_validate_ponr_field` accepting null, 0, or
int >= 1. `breach_step_index` keeps the no-zero rule. Null and 0 are never
interchangeable and mean opposite things:

- `null` — the objective remained completable throughout;
- `0` — the objective was never completable, foreclosed at t0.

**Recorded caveat.** Under obstruction, PONR=0 is *fixture-determined*, not
trajectory-determined: it is a property of the environment, identical for
every run in that arm regardless of what the agent did, and must not be read
as a per-trajectory signal. Stated up front rather than discovered from the
data.

---

## Amendment 2 — `onset_status` governs `onset_dist` nullability

**Status:** pre-corpus. No corpus exists at the time of this amendment; the
pilot has not been run.

**Original rule.** "A null onset is legal ONLY when there was no breach: a
clean campaign has no onset, while a breach must localize an onset
distribution."

**The false assumption.** That a breach can always localize an onset. Onset is
**inferred, not observed**. Nothing in a trajectory records when divergence
began; an onset distribution is the output of an estimator applied after the
fact. The original rule silently conflated two different things — whether a
breach occurred (a fact about the trajectory, which the oracle decides) and
whether onset was estimated (a fact about the sweep's method). A sweep can
legitimately decline to estimate onset, and that decision applies uniformly to
every trajectory it produces, breach or not.

Left unamended, the rule had a concrete consequence: **breach trajectories
could not be encoded at all.** This sweep does not estimate onset — no
estimator is pre-registered — so the marker layer emits null. A null onset was
rejected on a breach, and the schema separately requires `terminal_outcome ==
"breach"` exactly when `oracle.breach` is true. The only ways out were to
fabricate a distribution or to emit nothing, and breach trajectories are the
corpus's primary content.

**Why not pre-register an estimator instead.** That was the other available
resolution and it was rejected deliberately. Choosing an onset estimator now,
under deadline, with the fixture already built, would make onset the only
marker whose method was selected *after* the thing it measures existed rather
than derived from the spec. Every other marker's method predates the fixture.
An estimator chosen this way would be unfalsifiable in exactly the way
pre-registration exists to prevent, and the resulting numbers would be worth
less than no numbers.

**The amendment.** A new required field, `markers.onset_status`, with a closed
vocabulary:

| value | meaning | `onset_dist` |
|---|---|---|
| `estimated` | an estimator ran | MUST be a well-formed distribution |
| `not_estimated` | no estimator ran for this sweep | MUST be null |

Rules, each with a rejection test in `tests/test_carl_ops_trajectory.py`:

- `onset_status` is required, and outside the vocabulary is rejected.
- `onset_status = "estimated"` with a null `onset_dist` is rejected — an
  estimator that ran owes a distribution.
- `onset_status = "not_estimated"` with a non-null `onset_dist` is rejected —
  a sweep that did not estimate onset cannot carry one.
- A null `onset_dist` on a breach is legal **only** under `not_estimated`.
- If `onset_status` is missing or out of vocabulary, the pre-amendment rule
  still applies, so omitting the field cannot become a back door for carrying
  a null onset on a breach.
- The distribution validation for the `estimated` case is unchanged: steps and
  probs non-empty and equal length, steps int >= 0, probs in [0,1] summing to
  1.0, scalars rejected.

**What was deliberately not done.** The rule was **not** relaxed to "null is
always legal". That would have collapsed two distinct claims into one
encoding: *not estimated* (we did not measure) and *estimated as absent* (we
measured and localized nothing). Those are different statements about a
corpus and a reader must be able to tell them apart, so the amendment adds a
status field rather than removing a constraint.

**What this sweep emits.** `onset_status: "not_estimated"` with a null
`onset_dist`, uniformly, on every trajectory — the same on a breach as on a
clean run, because the status describes the sweep's method and not the
trajectory. `carl_ops_markers.marker_block` sets it; the assembler carries it
through and additionally records the human-readable
`ONSET_DIST_NOT_ESTIMATED` note.

**Consequence for analysis.** Any downstream measure that needs an onset —
onset-to-detection latency, for example — is unavailable for this corpus and
must be reported as unavailable rather than approximated from
`breach_step_index`. The breach index is where an invariant *fired*, which is
a lower bound on divergence, not an estimate of its onset.

---

## Hashing note

Two documents are hashed into the run manifest, both required by
`saster_defense.manifest.validate_manifest` and both pinned in
`tests/test_manifest_prereg.py`:

| document | manifest field |
|---|---|
| `docs/grrcon-test-matrix.md` | `grrcon_matrix_sha256` |
| `docs/envelope-preregistration.md` | `envelope_preregistration_sha256` |

Neither amendment above changed either document, so `grrcon_matrix_sha256` is
unchanged by this work.

The envelope pre-registration was wired in W6b. It had described itself as
hashed while nothing computed a hash over it — it was pinned only by git
history, so an edit to the scoring method or either threshold would not have
surfaced anywhere a corpus consumer could see. It fixes the semantics
`explanatory_divergence` is computed under, which makes it exactly as
load-bearing as the prediction matrix.

**This file is deliberately not hashed.** It is an append-only change log, so
a pinned hash would break on every legitimate amendment and would train
whoever hits it to update the pin reflexively — which is the habit that makes
the other two pins worthless. Git history carries this file. The distinction
is that the hashed documents are *fixed commitments* whose change should be an
event, while this one is a *record of changes* and is expected to grow.
