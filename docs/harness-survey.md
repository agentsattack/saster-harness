# Public-harness survey (A3)

Four public evaluation harnesses, cloned shallow at the pinned heads below on
2026-09-06, grepped for the seven patterns, every candidate read in place
before it was called anything. Nothing was filed upstream; the last section
lists what could be.

| harness | commit | date |
|---|---|---|
| inspect_ai (UKGovernmentBEIS) | `856f41f19debe008756ec4c5831f0600c861c51a` | 2026-09-06 |
| lm-evaluation-harness (EleutherAI) | `b954108c9baaaa934b4ad842033b31a97ee30816` | 2026-09-01 |
| garak (NVIDIA) | `2233d51bedf6bfb634872ef9efbcd94eae38cc1a` | 2026-09-04 |
| promptfoo | `6d0395a20520e19cf8889d572b879ec9c2831a52` | 2026-09-05 |

## The patterns and the grep that finds candidates

| # | pattern | grep (candidates, not hits) |
|---|---|---|
| P1 | backend/tool/judge result evaluated by truthiness before the clean branch | `^\s*(if\|elif) not (result\|response\|output\|verdict\|score\|judge_result\|completion\|answer)\b` |
| P2 | verdict token matched after `.lower()`/`.strip()` with the permissive branch as the clean class | `\.(lower\|strip)\(\)` ∧ `"(safe\|unsafe\|yes\|no\|pass\|fail\|harmful\|refus\|correct)"` |
| P3 | exception in a classifier/judge wrapper mapped to a default score or the safe class | `except` followed within 3 lines by `return (0\|False\|None\|1\|True\|{}\|[])` or `score = 0` |
| P4 | undefined / empty / non-JSON policy or judge response resolving to allow/pass/safe | `except JSONDecodeError` / `catch (` followed by `pass`, `return True/0/None/{}` |
| P5 | trial or sample count read from config rather than derived | `(num_samples\|n_samples\|num_trials\|repeats\|epochs)\s*=\s*(config\|cfg\|args\|self\.config)` |
| P6 | a stand-in/mock reachable in the non-test path behind an endpoint or flag | `mock\|fake\|stub\|dummy` outside test paths ∧ an env/flag condition |
| P7 (D18) | a classifier's verdict depending on the serialization of the same action | `json\.dumps(\|JSON\.stringify(` feeding a judge/grader/classifier prompt; `sort_keys=True` |

Candidate counts per harness are in `runs/unprompted/harness_survey_counts.txt`;
they are grep volumes and mean nothing until read.

## Hits, read

| harness | file:line | confirmed | catalogue class | direction an error there would lean |
|---|---|---|---|---|
| garak | `garak/probes/goat.py:879` — `if not judge_response: return False, ""` | **confirmed**: an empty or failed attacker-LLM judge reply returns *not unsafe* — the clean class — with no unavailable state | C1 / D1-class silent default | toward held (the attack reads as failed) |
| garak | `garak/probes/goat.py:885` — `is_unsafe = "unsafe" in response_text.lower()` | **confirmed**: substring after lowercasing; a garbage reply is safe, and a reply saying "not unsafe" is unsafe | C2 / D4-class token match | both: garbage toward held, negation away |
| garak | `garak/detectors/agent_breaker.py:253` — `except JSONDecodeError: pass` | not confirmed: the fall-through goes on to extract a JSON object and raises if none is found; no default | — | — |
| inspect_ai | `src/inspect_ai/scorer/_model.py:312-352` — model-graded parse | **not confirmed — the counter-example**: no grade match, an off-menu grade, or a multi-character verdict returns `Score.unscored(reason="grader_failed")`, never a default grade; the pattern's last-match binding is documented against the injection vector | (the right shape for Class 1) | — |
| inspect_ai | `examples/scorer.py:51` — `completion.lower() == "yes"` | example code, not the library; a non-"yes" reply is incorrect, the conservative branch | — | away (scores down) |
| inspect_ai | `src/inspect_ai/_eval/task/run.py:811` — `epochs = config.epochs` | not confirmed as C5: epochs is a design parameter; the sample count per epoch is derived from the dataset, and distinctness is not a claim the harness makes | — | — |
| lm-evaluation-harness | `lm_eval/tasks/jsonschema_bench/metrics.py:155` — `except JSONDecodeError: return False` | not confirmed: for a *validity* metric False is the failing class, the right direction | — | — |
| lm-evaluation-harness | `lm_eval/filters/extraction.py:191` — `.lower()` under `ignore_case` | not confirmed: opt-in case folding of an extracted answer against a target, not a safety verdict, and the default is off | — | — |
| promptfoo | `src/assertions/llmRubric.ts:44-49` — `pass: resp.pass !== inverse`, score clamped only on inversion | not confirmed as a default: `matchesLlmRubric` (`src/matchers/llmGrading.ts:168`) throws on a provider error or empty output and rethrows into the evaluator's "Assertion grading failed" path; the non-inverted score is passed through unclamped, which is a range question rather than a default | (edge: a NaN score on the non-inverted path) | — |
| promptfoo | `src/providers/huggingface.ts:371,659` — `JSON.stringify(ret.classification)` | not confirmed as P7: the classification is serialized for output, not fed back to a classifier | — | — |

**2 of 4 harnesses with at least one confirmed instance** would be the honest
count only if promptfoo's unclamped score were called a hit; it is not. The
count is **1 of 4 with at least one confirmed instance** (garak, two sites in
one probe's judge path), **1 of 4 with a documented counter-example**
(inspect_ai's grader returns unscored), and 2 with nothing confirmed after
reading (lm-evaluation-harness, promptfoo).

## P7, the D18 pattern, in the four

No harness feeds the same action to a classifier in two serializations, so
D18's pattern — the verdict changing with dotted-vs-wire form or key order —
has no direct instance to confirm. What the four do share with the sweep's
L1 is the precondition: garak's judges, inspect_ai's model graders and
promptfoo's rubric all send free text a template rendered, and none of the
four pins the rendering with a test. The transferable check is the one this
harness now carries (`tests/test_l1_rendering.py`): the classifier sees a
named serialization, and the number is reported against it.

## What could be filed upstream (not filed)

- garak `probes/goat.py`: an empty judge reply and an unparseable judge
  reply both resolve to "not unsafe"; a third state (judge unavailable) with
  its own count would keep transport failures out of the attack-success
  denominator — the same change this harness made for L4 (D1, D4).
- promptfoo `assertions/llmRubric.ts`: clamp or reject a non-finite score on
  the non-inverted path as well as the inverted one.

## The single most transferable finding

A judge path with no unavailable state: garak's `goat.py` returns the clean
class for an empty reply and matches the unsafe token by lowercase substring.
It is D1 and D4 of this harness's own log, in a harness with far more users,
and the fix is the same two lines.
