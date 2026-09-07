# [un]prompted — Part A evidence (git-only)

Branch `evidence/unprompted` at `30c27a7`, a separate clone; the cluster, the sweep branch and the GrrCON deck were not touched. Corpus read-only.

## A1 — survival time (`docs/catalogue-provenance.md`)

| direction | median hours to fix | n |
|---|---|---|
| flattering (toward-held, erased-toward-held) | **170.2** | 17 |
| unflattering (away, toward-false-alarm) | **0.7** | 3 |
| neutral or mixed | 72.6 | 9 |

Flattering errors survived longer, by two orders of magnitude at the medians, on 29 rows; the unflattering side is three rows. C1–C11 are reconstructed from the plan's class↔row mapping because the CFP document is not in the repository; row C11 is in or out per the CFP as submitted.

## A2 — mutation score (`docs/mutation-score.md`)

C table, headline over the nine rows not killed by their own fix's regression tests: suite-before-fix **0/9**, tests-baseline **0/9**, current suite **4/9**. Over all eleven: 6/11 current, 2/11 baseline (C6, C10 — killed by tests their fix commit added). Survivors C1, C2, C3, C8, C9, each with the test that would catch it and why it was not written.

D table (separate, never pooled): 9/9 current, 0/9 baseline; seven rows excluded for code-side conflicts, two without a fix.

## A3 — public-harness survey (`docs/harness-survey.md`)

**1 of 4** with at least one confirmed instance after reading (garak: an empty judge reply returns the clean class; the unsafe token is matched by lowercase substring), **1 of 4** with a documented counter-example (inspect_ai's model grader returns unscored on no match), 2 with nothing confirmed. Most transferable finding: a judge path with no unavailable state — D1 and D4 of this harness's own log, in a harness with far more users, fixable in two lines. Nothing filed upstream; two candidates listed.

## A4 — handoffs written under the exclusion discipline

- `docs/handoff-reference-scorer.md` (+ values-free field list): three quoted definitions, exclusion list, what it does not establish; `tests/instrument/test_second_opinion.py` is `xfail(strict=True)`.
- `docs/handoff-novel-mutants.md`: the surface, 29 catalogue rows and 1,243 test names on the exclusion list.
- Not authored here, by design: judge-prompt paraphrases, novel mutants, the reference scorer.

## Five lines for the slides

1. Twenty-nine measurement errors in one harness, dated: the ones that flattered the defense took a median 170.2 hours to fix; the ones that did not, 0.7.
2. Every wrong number passed a green suite: 0 of 9 catalogued defects are caught by the tests that existed when they were live.
3. The rejection suite written afterwards catches 4 of those 9; the 5 it misses each have a named test that was not written, and a reason.
4. The same defect class is live in a public harness today: garak's judge returns the clean class on an empty reply and matches 'unsafe' by lowercase substring; inspect_ai gets it right.
5. The cheapest second opinion is a hundred-line scorer someone else writes from the definitions; its handoff is written and its agreement test is a strict xfail until it exists.

## Not done here

Part B (cluster) waits for the window after Sep 25. The novel mutants and the reference scorer wait on separate sessions. `docs/catalogue-provenance.md` row assignments for C1–C11 await confirmation against the CFP as submitted.
