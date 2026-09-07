# Mutation score (A2, Protocol A)

HEAD `30c27a7` on `evidence/unprompted`; `tests-baseline` = `68a3085` (68a3085, W21, 2026-09-01), the last commit before any instrument test existed — 56 test files there, 0 of them `test_instrument_*`, and no `tests/instrument/` directory (the rejection suite lives as `tests/test_instrument_*.py`; `tests/instrument/` holds only the Protocol B xfail). Scorer: `scripts/mutation_score.py` — a worktree per mutant; the tests-baseline tree, then the current tree; a mutant is killed by a suite when a test passing on unmutated HEAD fails on it; 72 baseline tests already failing on HEAD (API drift) and one collection error are excluded. A third column, **suite before fix**, runs the tests as they stood at `<fix>^` — the suite that was green with the defect present — controlled the same way.

## C table — the headline (C1–C11, read-caught)

| row | mutant | how | suite before fix | tests-baseline | current suite | killing tests (current) |
|---|---|---|---|---|---|---|
| C1 | `47a9b56` | hand-reintroduced | survived | survived | survived (0) |  |
| C2 | `16b8157` | hand-reintroduced | survived | survived | survived (0) |  |
| C3 | `ce53225` | hand-reintroduced | survived | survived | survived (0) |  |
| C4 | `d04c68a` | clean revert | survived | survived | **killed** (9) | test_no_template_kwargs_sends_the_byte_identical_body_as_before, test_template_kwargs_reach_every_render |
| C5 | `27978c2` | hand-reintroduced | survived | survived | **killed** (1) | test_plan_shape_and_pairing |
| C6 | `5b7968f` | hand-reintroduced | survived | **killed** | **killed** (6) | test_assembled_golden_record_carries_latency_6_and_units, test_assembler_sets_detected_at_breach_from_marker_equality |
| C7 | `e36dadd` | hand-reintroduced | survived | survived | **killed** (7) | test_the_tools_array_is_sent_on_every_render, test_tool_call_round_trips_through_the_family_template |
| C8 | `8643fd9` | hand-reintroduced | survived | survived | survived (0) |  |
| C9 | `f31dc52` | clean revert | survived | survived | survived (0) |  |
| C10 | `7d2c03e` | hand-reintroduced | survived | **killed** | **killed** (5) | test_base_rate_exclusion_carries_its_provenance_on_the_entry, test_assembler_marks_non_discriminating_layers |
| C11 | `0aed9fd` | hand-reintroduced | **killed** | survived | **killed** (13) | test_degenerate_input_never_clean, test_degenerate_input_never_clean |

**Reported prominently.** The tests-baseline tree kills **C6, C10**. Both kills come from `tests/test_trajectory_assembly.py` tests that were added in the rows' own fix commit `951a7d6` (W10), which predates the baseline tag; per the protocol those two rows leave the catalogue's mutation headline — they were regression-tested at fix time, not caught by an independent suite. The *suite before fix* column shows every C row surviving the suite that was green when its number was wrong, except C11, whose fix (`0e5cd4b`, S1 D1) post-dates the Class 1 rows that kill it — which is the case for treating C11 as D1's neighbour, and why it is in or out per the CFP as submitted.

**Headline, C1–C11 minus the two baseline-killed rows (n=9):** suite before fix **0/9**, tests-baseline **0/9**, current suite **4/9** (C4, C5, C7, C11). Over all eleven: current 6/11, tests-baseline 2/11.

## Survivors — what would catch each and why it was not written

| row | the test that would catch it | why it was not written |
|---|---|---|
| C1 | a test that the binary head is sent the binary template (assert the rendered prompt carries the binary template's marker, not the taxonomy) | the fix switched the prompt mode and added a label test (`test_the_observer_checkpoint_is_reported`); the Class 1 rows exercise the parser on replies, never the prompt selection |
| C2 | a Class 1 row whose body is length-capped WITHOUT a verdict token (`"Risk So"`, finish_reason length) | the existing `exceeds_max_tokens_length_capped` row carries a parseable `unsafe` body, so the parser returns before the finish_reason branch the mutant corrupts |
| C3 | the Class 2 length-invariance metamorphic test (pad tool names; ranking must not change) | the envelope is `not_computed` in the sweep (Amendment 9), so the scorer left the citable path before the Class 2 tests were written and the invariant was never encoded |
| C8 | a test that `envelopes_not_computed()` returns three nulls under `envelope_status: not_computed` | the block was introduced as data while the sweep already ran under it; the Class 2 uniform-exact detector guards `envelopes()`, not the not-computed constructor |
| C9 | a test importing the runner's category constant and checking it against the fixture's capability manifest | the Class 6 tests target the assembler, and nothing imports `scripts/run_cell_w9.py`; the label lives in the scripts |

C1 note: the first C1 mutant (forcing the checkpoint property) was killed at baseline by the manifest-label test; it changed the label, not the behaviour, and was rebuilt at the prompt-selection site (`fine_grained_prompt(...) if True`), which nothing kills. The rebuilt mutant is the one scored.

## D table — reported separately, never pooled (D1–D18, instrument-caught)

A defect the new suite found is killed by it tautologically. Only fixes whose code side reverts cleanly are included; conflicts confined to docs, tests or runs were resolved to HEAD. Excluded for a code-side conflict: D1, D5, D7, D9, D10, D11, D12. Excluded as standing without a fix: D15, D17.

| row | mutant | suite before fix | tests-baseline | current suite | killing tests (current) |
|---|---|---|---|---|---|
| D2 | `35e6610` | n/a | survived | **killed** (26) | test_degenerate_input_never_clean, test_degenerate_input_never_clean |
| D3 | `4041924` | n/a | survived | **killed** (13) | test_degenerate_input_never_clean, test_degenerate_input_never_clean |
| D4 | `9cbf20a` | n/a | survived | **killed** (3) | test_degenerate_input_never_clean, test_degenerate_input_never_clean |
| D6 | `e2499da` | n/a | survived | **killed** (2) | test_degenerate_input_never_clean, test_degenerate_input_never_clean |
| D8 | `5ec216d` | n/a | survived | **killed** (1) | test_v15_unified_parser_two_stage |
| D13 | `3560d76` | n/a | survived | **killed** (5) | test_assembler_derives_the_route_and_records_the_configured_one, test_a_forced_route_the_stack_blocked_is_a_record_not_a_mismatch |
| D14 | `db637be` | n/a | survived | **killed** (5) | test_assembler_derives_the_route_and_records_the_configured_one, test_a_forced_route_the_stack_blocked_is_a_record_not_a_mismatch |
| D16 | `d4d8219` | n/a | survived | **killed** (1) | test_marker_population_gate_accepts_tagged_censored_first_detection |
| D18 | `bf6b72e` | n/a | survived | **killed** (3) | test_capability_manifest_declares_carl_ops_as_saster_31_only, test_every_existing_corpus_record_carries_the_unsatisfiable_label |

D table: tests-baseline 0/9, current suite 9/9.

## Hashes

- `tests-baseline` tag: `68a3085`
- HEAD: `30c27a7`
- Mutant branches: `mutant/C1` 47a9b56, `mutant/C2` 16b8157, `mutant/C3` ce53225, `mutant/C4` d04c68a, `mutant/C5` 27978c2, `mutant/C6` 5b7968f, `mutant/C7` e36dadd, `mutant/C8` 8643fd9, `mutant/C9` f31dc52, `mutant/C10` 7d2c03e, `mutant/C11` 0aed9fd; `mutant/D2` 35e6610, `mutant/D3` 4041924, `mutant/D4` 9cbf20a, `mutant/D6` e2499da, `mutant/D8` 5ec216d, `mutant/D13` 3560d76, `mutant/D14` db637be, `mutant/D16` d4d8219, `mutant/D18` bf6b72e
- Per-mutant results with killing test ids and wall times: `runs/unprompted/mutation_score_C.json`, `runs/unprompted/mutation_score_D.json`.

Novel mutants: `docs/handoff-novel-mutants.md` — authored blind in a separate session; scored here as a third table when they arrive.
