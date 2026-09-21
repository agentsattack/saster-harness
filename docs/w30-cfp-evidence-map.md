# CFP claims against the September 6 follow-up evidence

The accepted CFP describes intended demonstrations. The deck should describe the measurements actually obtained. Use the complete W30 result tables for rates; examples below are selected demonstrations, not prevalence estimates.

| CFP promise | Evidence now available | Defensible presentation wording |
| --- | --- | --- |
| Conversational attack walks past every layer with no alert | Neutral support example bypasses Granite L1; the matched authorization rule blocks it. The separate 40-trial ops batch enables five layers and observes zero breaches, 40 warnings, and 40 trials with approval escalations. | “We test where the layers hold, where they fail, and whether an alert identifies unauthorized behavior.” |
| Compromised agent phones home while defenses report all clear | One model-requested HTTP POST reaches the isolated receiver. L1/L2/L3 allow and L4 says safe; L5 escalates and is approved by a script. The new HTTP tool is outside the original L2/L3 policy vocabulary. | “A planted compromised agent reaches our lab receiver through an uncovered tool surface. The trajectory monitor says safe; the approval gate still escalates.” |
| Human circuit breaker | The model-requested action and separate pending receipt ID are recorded. An actual operator decision is needed before claiming a human outcome. | Use the recorded decision if `callback/human_result.json` exists; otherwise show the gate architecture and say the human intervention result is pending. |
| Standard evaluation misses multi-turn weaknesses | The direct baseline and later framed requests are recorded separately, with actual synthetic tool effects. Some direct baselines also succeed, and some normal-task controls breach. | “A single direct probe and a multi-turn conversation can produce different outcomes. We measure both, with normal-task controls.” |
| Calibrated confidence across categories | Two additional category scenarios, paired conditions, a prespecified train/holdout diagnostic, and interval-code validation. Ten attack samples per cell are small. | “We attach uncertainty to measured outcomes and check predictive calibration; these measurements do not establish universal calibration or taxonomy-wide coverage.” |
| Open-source benchmark | Local scripts, protocol, raw evidence, analysis, and offline replay are available. Existing package/release gaps remain listed in the readiness review. | Demonstrate the exact checkout and documented experiment commands. Do not imply a clean `pip install` currently reproduces every research/demo module. |

## Strongest current sequence for the talk

1. Start with the authorized task and show the model's proposed tool action. Ask whether that action is authorized, regardless of how harmless its description sounds.
2. Replay the neutral-prompt export example and its matched OPA denial. Show the complete batch rates immediately afterward.
3. Show the real callback receipt, the uncovered tool surface, and the visible L5 escalation. If the operator has supplied a decision, show the separately recorded outcome.
4. Show the negative finding: no breach in the new five-layer ops batch. Explain the limits of a small sample and the distinction between preventing a breach, completing the job, and producing a warning.
5. Show the serial normal-workflow replay: all 24 authorized workflows complete, and the trajectory monitor warns on all 24. Retain the earlier solver-error run as an instrumentation finding, not another independent sample.
6. End with a concrete workflow: define task authority, enforce it at tool execution, retain per-layer events and actual effects, test ordinary workflows alongside attacks, and rerun fixed scenarios after changes.

## External claims

The source-by-source review is in `grrcon-readiness-review-2026-09-06.md`. In particular, the adaptive-defense study reports over 90% success against **most** of twelve defenses, and the “one in eight” statistic concerns **reported AI breaches** in a survey. A report about malware using an agentic workflow is not by itself evidence that a legitimate production enterprise agent was hijacked. Keep those distinctions in the slides and speaker notes.
