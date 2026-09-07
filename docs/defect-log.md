# Defect log — canonical, final (2026-09-06)

Every defect the instrument tests, the pilot and the sweep found in this harness, numbered in the order found. Direction is relative to "defense held": **toward-held** made the defense look better than it was; **erased** removed trajectories from the analysis (by omission toward held); **away** made it look worse; **toward-false-alarm** made a layer deny what it should allow; **neutral** changed no number; **mixed** went both ways. Entries with their full text are in `docs/schema-amendments.md`; findings in `docs/sweep-findings.md`. None manufactured a breach.

| id | what | direction | the false assumption | fix commit | introduced |
|---|---|---|---|---|---|
| D1 | L2: an undefined OPA decision defaulted to allow; a backend failure crashed the cell | toward-held | `opa eval` either answers in the closed vocabulary or does not answer, so an empty result could be read as allow | `0e5cd4b` (2026-09-05) | `3265bef` (2026-08-28, the defense stack) |
| D2 | L3: the decision procedure's answer was tested for truthiness; z3 `unknown` read as no breach | toward-held | `breach_entailed_z3` returns a bool; it returned `False` for `unknown` too | `13a911c` (2026-09-05) | `3265bef` (2026-08-28) |
| D3 | L5: an approver that raised or answered a non-bool was decided by truthiness | mixed | the approver callback returns a bool; `None` denied, any non-empty string escalated-and-proceeded | `dd78486` (2026-09-05) | `3265bef` (2026-08-28) |
| D4 | L4: the verdict token was case-folded, so `SAFE` was the clean class | toward-held | case is noise in AgentDoG's answer; the template asks for exactly `safe`/`unsafe` and a folded reply in a shape the model was never trained to emit became clean (the wrong test was fixed as a test) | `6f39e0e` (2026-09-05) | `3265bef` (2026-08-28) |
| D5 | L1: an endpoint string made the manifest say `real` while the stand-in kept answering | toward-held (citability) | configuring an endpoint means a real backend is in the path; the guard has no HTTP client | `62c1fd6` (2026-09-05) | `3265bef` (2026-08-28) |
| D6 | canary: a router exception escaped the loop uncounted; an error body classified as ok | toward-held | `router.generate` returns on every turn and a non-empty completion is a completed turn | `a0fbbce` (2026-09-05) | `2a13fa4` (2026-08-29, the pre-sweep canary) |
| D7 | envelope metric: an exactly uniform or single-candidate distribution returned three plausible numbers | neutral | any `probs` handed to `envelopes()` came from a measurement; a template that drops the tool call renders every candidate identically | `4d5d5b6` (2026-09-05) | `a38d991` (2026-08-29) |
| D8 | the 1.5 unified parser stripped a paired think block the served head never emits | away (both conforming classes read unavailable) | the reply carries `<think>…</think>` as a pair; vLLM emits the closing tag only | `288b380` (2026-09-05) | `8dfa4d3` (2026-09-05) |
| D9 | an `allow` wrote no raw reply, so the clean class was unauditable (two sites) | toward-held | a reply worth keeping is one that produced a detection entry; the schema has no clean entry | `b6b78cb` site 1, `9c49b36` site 2 (2026-09-05) | `2002f4e` (2026-09-05, the sidecar) |
| D10 | a recorded or base-rate-excluded head's labels were rejected as "not a finding" | neutral (records refused) | "a finding" meant one thing; Amendments 14 and 16 made it mean "counted" while the fine-grained labels were still gated on it | `6c38ed6` (2026-09-05) | `951a7d6` (2026-08-30, `_is_finding`) |
| D11 | a forced route that the stack blocked was dropped as a "mismatch" | erased (records lost; by omission toward held) | under a forced route the derived route must equal the configured one for the record to be true | `6c38ed6`, tests `7f7bf87` (2026-09-05) | `1180427` (2026-08-28, route derivation) |
| D12 | a ticket closed as resolved without completion, and a step-limit exit, were classified `error` | erased (from every denominator) | a completed trial is resolved, escalated, or a harness fault | `f7c41d3` (2026-09-05, Amendment 18) | `2a13fa4` (2026-08-29, `derive_terminal_outcome`); the stop classes `3dab06d` (2026-09-01) |
| D13 | a breach that then stopped in prose carried a stop detail the schema forbids; the cell aborted | toward-held (breaches lost) | the runner's stop status and the derived class agree | `c243332` (2026-09-06) | `3dab06d` (2026-09-01, Amendment 10 detail) |
| D14 | a different realized widening was still dropped as a "mismatch" | toward-held (breaches lost) | a different widening than configured is a mislabel rather than the ablation's own result (D11 kept this residual) | `c243332` (2026-09-06) | `1180427` (2026-08-28) |
| D15 | the static coverage query enumerated one value per argument | toward-held (coverage overstated) | covering a tool covers its arguments | entered `5d9bfe7` (2026-09-06); **no fix** — the query is unchanged and the gap is documented (F24/F25) | `d556eba` (2026-09-05) |
| D16 | the marker gate read a censored null as an unpopulated instrument | erased (47 cells; by omission toward held) | every breaching campaign has at least one counted detection | `4bd0502` (2026-09-06, Amendment 19) | `e734c4a` (2026-09-05) |
| D17 | the arm manifest's `l4_heads.<key>.role` says "primary" for the binary head on an L4-off cell; the detection entries say "recorded" | neutral (a setting-derived label disagreeing with the entry-level role; no number changed) | the observer setting alone determines the head's role | documented `760f72f` (2026-09-06); **no fix** — a runner change mid-arm is a new run id; fix before any next run | `2002f4e` (2026-09-05, `l4_heads` manifest block) |
| D18 | the input classifier's verdicts on the same 109 control actions changed with the rendering: 47 denials dotted and key-sorted, 2 in the wire form (F27) | toward-false-alarm | that a content classifier's verdict on an action is a property of the action — that any faithful serialization of the tool call is equivalent input | `b26e2cd` (2026-09-06; the layer renders the wire form, `tests/test_l1_rendering.py`) | `0ce124f` (2026-09-06, the L1 client's first rendering) |
| D19 | the beat-1 runner keeps a denied input turn in the history the model sees on later turns (`run_beat1_w29.py:148-149`) | away | that blocking the reply quarantines the input — a denied turn is out of the reply, not out of the context | **no fix** — semantics to be chosen and stated, then a new run id | `328d1e9` (2026-09-06, the beat-1 runner) |
| D20 | the runner binds tool-call arguments to the store method's signature; a correctly-shaped object with a null required field passes and the store executes it (`create_bucket(owner=None)`, `add_firewall_rule(port=None)`) | neutral (0 of 6,186 actions; mechanism mixed) | that binding to the signature validates the arguments — a present key is a value of the schema's type | **no fix before the talk**; strict-xfail rejection test `tests/test_argument_schema_null.py` | `63e0961` (2026-08-29, the model-driven action plane) |

## Count by direction

| direction | count | ids |
|---|---|---|
| toward-held | 9 | D1, D2, D4, D5, D6, D9, D13, D14, D15 |
| erased | 3 | D11, D12, D16 |
| neutral | 4 | D7, D10, D17, D20 |
| mixed | 1 | D3 |
| away | 2 | D8, D19 |
| toward-false-alarm | 1 | D18 |

Twenty. 9 toward held, 3 erased (each by omission toward held), 4 neutral, 1 mixed, 2 away, 1 toward false alarm (D18: a defense looking stricter than it is). Four are documented without a fix (D15, D17, D19, D20), each with the reason.

Introducing commits are the commit that first added the code carrying the assumption, from `git log -S` on the defining symbol; where a file predates the assumption, the file's first commit is given.
