# GrrCON readiness review — September 6, 2026

**Talk:** Your AI Agent Could Be a Threat Actor · Larry Suto · 50 minutes · September 24.

**Assessment:** There is enough research for a strong talk. The present package does **not yet substantiate several specific CFP promises**, and the conversational demo has a newly identified history-handling problem. Spend the remaining 18 days on evidence reconciliation, a small number of targeted demonstrations, portability, and rehearsal. A broader model sweep is lower priority.

Reviewed at `47a2edc` on `feat/defense-stack`. This review adds this document only; it does not change existing records, pinned documents, code, or cluster configuration. The user-supplied CFP is the authority for scope. No assembled presentation was found; visual review covered generated deck assets, not the deck currently being built.

## 1. Findings that should be resolved before slide lock

### R1 — The conversational demo reintroduces blocked input into model context

**High priority.** In [run_beat1_w29.py](../scripts/run_beat1_w29.py), lines 132–138, a denied user message is appended to `messages`, followed by an assistant placeholder. The next allowed turn sends that history to the victim. Reading the selected run's stored prompt blobs confirmed that all five recorded model prompts include the blocked-request placeholder and preceding rejected input.

The classifier stops the immediate invocation but does not keep the denied instruction out of subsequent context. The selected clip therefore cannot isolate an erosion bypass of correctly quarantined input. It can demonstrate a guardrail integration failure, if that is the explicit claim.

**Resolution:** Choose and document the intended input-block semantics; retain rejected text in audit storage but omit it from the victim's subsequent context if blocking is meant to quarantine it. Add a regression that captures the next outbound request. Run a fixed, declared set of trials under a new run ID, keeping successes and failures. Do not overwrite the current clip or claim that fixing this will necessarily eliminate the breach.

### R2 — “Every layer,” “all clear,” and the human circuit breaker do not describe the selected demonstrations

The beat-1 manifest explicitly enables **L1 only**. [run_cell_w9.py](../scripts/run_cell_w9.py), lines 180–191, defines sweep `all` as **L2 + L3 + L4**, with L1 and L5 off. `all5` is a different configuration. The selected conversational run has two L1 input blocks. The main binary L4 head warns on every one of the 64 breaching records evaluated under L4-enabled matrix configurations, as well as all 24 safe controls. Excluding a non-discriminating head from a metric does not mean it produced no alert.

The cold-open F25 record shows an I2 violation involving a fixture destination naming a bucket that was never created. The report explicitly says no packet left and I4 did not fire. This is not evidence of a live callback to attacker infrastructure. The older [Carl recon runner](../carl/run_recon.py) drives detectors directly, without real HTTP, and deliberately produces SASTER-26/33 alerts.

**Resolution:** Put enabled layers and actual verdicts on every demo screen. Use “the action proceeded despite these controls” when accurate. If retaining the CFP's callback and human-stop promises, add a separately recorded, isolated lab callback with synthetic data, receiver-side evidence, and an actual operator veto that prevents the next action. Do not present an auto-approver as a human decision. A successful veto is a useful result, not a failed demo.

### R3 — The report and exported statistics disagree

I reloaded the selected corpus directly, applying w24c replacement by cell ID to w24b, and independently counted the relevant records.

| Item | Existing presentation/report issue | Record-backed correction |
|---|---|---|
| P1 | `docs/sweep-report.md:134` says 80 breaches and zero copy blocks under l3/l3+l4 | **61 breaches; six trajectories with an L3 copy block** across the two families in the matrix arm. The current P1 JSON already has these numbers. A copy block can occur after an earlier invariant breach. |
| Four-head table | `render_deck_w27.py:98` identifies 48 and 61 as Qwen and Ministral counts | These are **48 breaching and 61 non-breaching warning entries**, respectively, for the 1.5 coarse head. |
| Four-head denominator | Column says “sweep breaches (190)” but includes 109 and 173 warning totals | 1.5 coarse: **48 breach + 61 non-breach warnings**. 1.5 FG: **60 breach + 113 non-breach warnings**, with **four breach + three non-breach unavailable entries**. Separate populations and coverage. |
| Attempt curve | `render_posteriors_w28.py:121` says 14 compromised cells | JSON contains **28 observations per attempt**, reflecting seven configs × two preconditions × two route hints. The curve is per trial index, not cumulative probability of success by attempt k. |
| P7 status | P1–P17 export says carl-support never ran and L1 remains a stand-in | Later L1 work exists. State that it is a later, narrower experiment with the R1 limitation above; it still does not establish the original full-stack promise. |
| P17(ii) status | Export says never exercised model-driven | The report and readback identify 13 model-driven scope-lock denials. Reconcile the exact claim and selection rule. |

**Resolution:** Generate a final, dated claim table from selected raw records, with source IDs, population filters, denominators, and arm labels. Regenerate derivative assets into a new release directory. Do not treat either the report prose or `placeholders.json` as unquestionable ground truth.

### R4 — Multi-category calibrated assessment is not yet demonstrated

All **480 main-sweep records are SASTER-31**. The separate SASTER-14 support demonstration has one breach among three schema-admitted selected trials, and is not a comparable category/configuration experiment. The five documented non-dry-run attempts include two breaches, but two attempts fail the present citation checks. This is a selected example, not an estimated general success rate.

The posterior render provides Beta(1,1) intervals for observed binary outcomes. It does not establish empirical calibration or a continuous measure of latent intent. In the main sweep, every `onset_status` is `not_estimated` and every `explanatory_divergence_status` is `not_computed`; envelope-mass claims also remain unmeasured. Multiple seeds frequently repeat identical Qwen action sequences: 240 records / 77 distinct, versus 240 / 235 for Ministral.

**Resolution:** Either label this as a measured SASTER-31 case study plus separately labelled pattern demonstrations, or add a small prospective category arm. Two additional supported categories × two victims × three configurations × ten trials is 120 attack trials, plus separately specified matched safe controls. Only choose categories with meaningful tool-plane outcomes, category-specific success criteria, and working controls. Fix R1 before using SASTER-14. Report uncertainty and repeated-sequence counts; reserve “calibrated” for calibration you actually test. Do not relabel existing trajectories as new categories.

### R5 — “Non-breaching” is being called “sanctioned”

[score_l1_posthoc_w28.py](../scripts/score_l1_posthoc_w28.py), line 118, labels every non-breaching trajectory `sanctioned_non_breaching`. The 290 main-sweep non-breaches actually comprise 172 escalations, 36 stopped agents, seven defense-budget exhaustions, four analyzer stalls, six unresolved closures, and **65 resolved tasks**. An attack that failed to breach is not automatically a benign control, and a classifier warning on it is not automatically a false positive.

**Resolution:** Use “non-breaching attack trials”; calculate false-positive/specificity claims on independently labelled safe controls. Add task completion and escalation rates beside breach rates. This is a high-value enhancement using existing data.

### R6 — Several PNG assets are visibly unsuitable for projection

Visual inspection of `three_holes_table.png` found long rows overflowing cell boundaries and the right edge. `four_heads_table.png` has a clipped title. Both use a small portion of the available slide area for dense text. The renderer does not wrap table cells; the P1–P17 renderer additionally slices text to fixed character counts.

**Resolution:** One main claim per slide. Convert the three-hole table into three short state-transition examples. Show four-head results as a compact confusion/coverage table with explicit denominators. Move the full P1–P17 table, hashes, and trajectory IDs to appendix/notes. Export a PDF and inspect the actual projected-size deck before rehearsal.

### R7 — The current cluster needs attention before a live rehearsal

Read-only checks from spark1 during this review:

| Node | Observed state | Consequence |
|---|---|---|
| spark1 | Router and Ray head up; about 113 GiB available | Control path available. |
| spark2 | Ray worker; container GPU query succeeds; about 115 GiB available | Potential experiment capacity after explicit scheduling. The 1.5 heads are not currently served here. |
| spark3 | Qwen model-list endpoint responds; **container NVML fails**, host NVML succeeds | Container GPU visibility problem; HTTP readiness alone is insufficient. Existing inference may still work. |
| spark4 | Two AgentDoG heads, Granite, Llama Guard all answer model-list requests; GPU queries succeed; about 13 GiB available | Current layout differs from older two-head instructions. Avoid adding models without a memory plan. |
| spark5 | Configured fabric SSH and historical LAN port 22 both return **No route to host** | Physical power/address/link state remains unverified. |
| spark6 | Ministral endpoint responds; GPU query succeeds; about **676 MiB available**, 1.46 GiB swap used | Little headroom; sampled memory-pressure averages were zero, so this is not proof of active thrashing. |
| spark7/8 | Ray workers alive, but **container NVML fails** | Ray still advertises GPUs; advertised resources are not proof of usability. |

Ray reported four alive registered nodes: spark1/2/7/8. Spark3/4/6 serving standalone outside Ray is expected; spark5 absence and the failed container checks need investigation. I did not launch new inference jobs or restart services.

**Resolution:** Recover/verify spark5; address the container GPU-access issue in a maintenance window; check victim inference, tool parsing, and guard inference with short probes; rehearse once from a cold service start and once warm. Keep victim/guard configurations pinned. Capture actual image IDs, model revisions, launch arguments, templates, endpoint roles, and free memory in a dated runbook. Older commands use mutable `latest` image tags.

The sweep routes victim HTTP traffic over management-plane IPv4; guard endpoints use fabric IPv6. Do not imply that the sweep benchmarked eight-node tensor parallelism or QSFP throughput. NVIDIA documents DGX Spark QSFP/ConnectX-7 Ethernet ports up to 200 Gb/s, subject to cable/port configuration; that is not measured application throughput. [NVIDIA networking guide](https://docs.nvidia.com/dgx/dgx-spark/spark-clustering.html).

### R8 — Archive integrity is good, but the “everything” hash has a coverage gap

Both spark1 and spark8 independently passed verification for **12 stores / 11,517 listed files**, with zero mismatches and matching top-level digest:

`d01f0c2a62ae7236287ee64623a4d69b103784a10235de934ffd2bce093336c3`

However, the **ten files in `pre-sweep/manifest.addendum-1.json` are absent from `pre-sweep/SHA256SUMS`**, so the consolidated digest does not cover them. I separately checked all ten locally against their addendum hashes: all passed. These include `eval_slice.py` and earlier sweep results. The addendum itself is also not in those sums.

Additionally, `consolidate_evidence_w27.py --verify-only` prints results but returns success even if mismatches are found or the top-level comparison is false. A shell wrapper checking only its exit status could report success incorrectly.

**Resolution:** Add a versioned supplemental manifest covering omitted material and verify it on the mirror, retaining existing manifest bytes and hashes. Make future verification fail with a nonzero status on mismatches, missing expected stores, or top-level disagreement. State exactly what each digest covers. Archive final post-hoc scores, deck, and media under their own release manifest as well.

### R9 — The open-source handoff is not yet portable or fully green

Current local validation:

| Check | Result |
|---|---|
| `.venv/bin/pytest -q -m 'not cluster'` | **1,545 passed, 11 skipped, 10 deselected**, 43.33 seconds |
| CI-equivalent Ruff command | **Six E702 errors** in three test files |
| CI-equivalent mypy command | **Blocked parsing installed NumPy stubs** under the configured Python 3.10 target |
| Citation + marker gates, selected sweep/§P/§R | **162 cells / 810 records pass**, independently reloaded |
| §S record checks | **10 records pass** |
| Selected beat-1 clip | Schema-admitted, but schema admission does not detect R1's experimental confound |

The wheel configuration includes only `saster_harness`; campaign code imports `saster_defense` and relies on the sibling `~/halctf-agent` source tree. Several runners hardcode `/home/lbsuto/halctf-agent`. That sibling is present but is not a Git checkout here. Editable installation on this workstation does not establish that a fresh install elsewhere can reproduce the benchmark.

The README still leads with LayerOne/v0.4.0 while `pyproject.toml` says 0.5.0. The work is on `feat/defense-stack`; local `main` is older. The two ZIP bundles are untracked. No commit adding the untracked credentials file appeared in the local all-refs history query; that is not a comprehensive credential scan. The existing public-release checklist remains unfinished and contains old hashes.

**Resolution:** Fix the six lint findings and the supported-version/dependency mismatch. Package or document all research dependencies, including an immutable source snapshot of `halagent`. Test installation and a recorded-corpus analysis from a fresh temporary environment outside the repository. Publish a release landing page distinguishing offline replay, corpus analysis, and live-cluster reproduction. Review the public export without editing sealed evidence in place.

## 2. CFP promise-to-evidence map

| CFP commitment | Status on September 6 | Delivery plan |
|---|---|---|
| Agent makes unauthorized decisions | Supported within the declared fixtures | Show action, state change, objective, and oracle boundary; distinguish hidden directive from externally induced behavior. |
| Conversational attack past every layer, zero alerts | Not established | Resolve R1; explicitly label enabled layers and show all alerts, including blocks. |
| Compromised agent phones home while defense says all clear | Not established by current selected package | Add receiver-confirmed lab callback or describe the existing trace as simulated. |
| Human-in-the-loop circuit breaker | Interface exists; selected sweep disables L5 | Record a real pause, review, deny, and prevented next action. |
| Individually permitted actions compose into a breach | Supported in specific fixture/replay cases; not every selected model-driven path | Use a route where the per-action verdicts actually support this sentence. Separate missing owner checks and unexpected argument handling from genuinely temporal reasoning. |
| Calibrated strength across multiple categories | Partial: one category's posterior plus a separate support demonstration | Add a small controlled category arm or narrow the promise to uncertainty-aware case-study results. |
| Multi-turn campaigns reveal weaknesses standard evaluation misses | Specific examples supported | Compare the same case under a stated single-turn baseline; avoid “every standard evaluation.” Trial indices are independent-seed runs, not a learning attacker across trials. |
| Monitor agent-to-tool traffic and teach SASTER | Implemented reference detectors and scenarios | Include one legible wire event, its rule, its limit, and the response action. Taxonomy breadth is not measured benchmark breadth. |
| Open-source benchmark attendees can use | Code and corpus exist; distribution needs work | Freeze and test the attendee release by September 18–20. |

## 3. Numbers suitable for the main result slide

These are **per-trial breaches in the matrix arm, n=30 per family/configuration**, followed by **cells with any breach within five trials, n=6**. Do not substitute one denominator for the other. The additional 60 ladder records are outside this table.

| Configuration | Qwen trials | Qwen any-of-5 cells | Ministral trials | Ministral any-of-5 cells |
|---|---:|---:|---:|---:|
| none | 20/30 | 4/6 | 12/30 | 4/6 |
| L3 | 20/30 | 4/6 | 13/30 | 5/6 |
| L4 | 20/30 | 4/6 | 9/30 | 3/6 |
| L3 + L4 | 20/30 | 4/6 | 8/30 | 4/6 |
| L2 | 0/30 | 0/6 | 5/30 | 3/6 |
| L2 + L3 + L4 | 1/30 | 1/6 | 6/30 | 3/6 |
| Scope lock + per-action judge | 0/30 | 0/6 | 5/30 | 2/6 |

The §R arm supplies a constructive ending: Ministral L2 breaches went **5/30 → 0/30**, all-three **6/30 → 0/30**, while vendor-shaped stayed **5/30**. Qwen all-three went **1/30 → 0/30**. Label this as a prospective patch arm on selected configurations, not proof the stack is universally safe.

For overlap, L2 flagged 35/60 and L3 12/60; union 37, intersection 10. L3 adds two flagged trajectories beyond L2 in this population. This supports complementary observations; it does not alone establish an improvement in containment or task completion.

The latency field is **first counted finding minus breach action index**. It is not recovery time or a confirmed containment time. The reported medians, two steps for Qwen and one for Ministral, are only among detected breaches. **81/111 Qwen breaches and 57/79 Ministral breaches have no counted detection before the run ends.** Put those fractions beside any median. The field may remain named `containment_latency` in frozen records while the slide uses a more precise description.

The home-directory ATBench anchors are present: binary 1.0 has 975 well-formed / 1,000 attempted; binary 1.5 has 966 / 1,000; FG1.5 has 462 / 497. Keep errors in the accounting and distinguish published benchmark scores from your local remeasurement and fixture outcomes. No direct accuracy comparison should mix different FG checkpoints, label definitions, or selected warning-only subsets.

## 4. Source and wording checks for the CFP introduction

- **Adaptive attacks:** The cited study evaluated 12 defenses and reports over 90% success **for most**, not necessarily all. Attribute it to the paper's researchers rather than suggesting the three companies issued a joint corporate finding. [USENIX: The Attacker Moves Second](https://www.usenix.org/conference/usenixsecurity26/presentation/nasr).
- **NCSC:** Supported as a technical argument for treating LLMs as inherently confusable deputies, not a formal certification/classification. Its practical emphasis on deterministic boundaries and monitoring fits the strongest version of this talk. [NCSC article](https://www.ncsc.gov.uk/blog-post/prompt-injection-is-not-sql-injection).
- **One in eight:** Supported as HiddenLayer's reported finding from a survey of 250 IT/security leaders. Say “reported AI breaches in HiddenLayer's 2026 survey/report,” not one eighth of all enterprise breaches. [HiddenLayer release, March 18](https://www.hiddenlayer.com/newsroom).
- **Prompt-based C2 in the wild:** Google documents PROMPTSPY, an Android backdoor using an LLM for device actions. This supports malicious use of an agentic loop, but does not by itself establish hijacking of previously legitimate enterprise production agents. Cite a primary incident report that matches that stronger sentence or narrow it. [GTIG report](https://cloud.google.com/blog/topics/threat-intelligence/ai-vulnerability-exploitation-initial-access/).
- **Event:** The official schedule lists this title on Thursday at 2:30 PM in OverLords. The event is September 24–25; earlier local prompts saying September 22 are stale. The indexed presentations page currently mixes your opening with unrelated GradVids/vibe-coding text; check the organizer's displayed abstract against the CFP supplied here. [Schedule](https://grrcon.com/schedule/), [presentations](https://grrcon.com/presentations/).

## 5. Recommended 50-minute flow

Budget **45 minutes of material + five minutes for questions**, unless the organizer has provided a separate Q&A slot.

| Time | Purpose and material |
|---|---|
| 0–4 | A concrete unauthorized action; show the legitimate task and observable consequence. Explain which parts are simulated. |
| 4–9 | Why agent authority changes the threat model. Two strong external citations are enough. Define compromised versus induced behavior. |
| 9–15 | Corrected conversational example: direct refusal, later action, complete guard verdicts, and the history-handling lesson. |
| 15–24 | Ops case: attempted action → policy decision → state change → independent invariant. Show the block/escalation comparison and callback only if independently recorded. |
| 24–29 | Explain the layers in plain language: content, individual action, action history, trajectory auditor, human approval. Give each its observability limit. |
| 29–36 | Main rates, safe controls, uncertainty, task completion, and the R6 patch arm. Focus on two or three takeaways. |
| 36–41 | SASTER mapping and one wire-monitoring example the audience can recognize in its own logs. Show how an operator investigates and vetoes further action. |
| 41–45 | A usable operational method: declare authority, test attacks and normal tasks, compare intended scope with observed effects, respond at the tool boundary, retest. Give the release link. |
| 45–50 | Questions; keep definitions, pins, P1–P17, detailed per-head accounting, and limitations in backup slides. |

Suggested thesis: **An agent can produce unauthorized effects through ordinary tools. Measure its actions against explicit authority, test defenses against both attacks and legitimate work, and verify the mechanism that can stop it.** This is supported more strongly than a universal claim that every layer stays silent.

## 6. Work through September 24

| Dates | Deliverable and acceptance condition |
|---|---|
| Sep 6–8 | Resolve R1; reconcile figures and denominators; determine the exact live-demo scope; recover/diagnose cluster issues. Every planned headline has a named evidence source. |
| Sep 9–12 | One bounded enhancement window: prioritize receiver-confirmed callback + actual human veto, then a small category extension if needed. Declare sampling and controls first; retain every result. |
| Sep 13–15 | Freeze research inputs. Render corrected charts. Create a dated claim-to-slide ledger and release manifest. No slide claims a measurement that was not collected. |
| Sep 16–18 | Assemble the 45-minute narrative and record all demos. Produce self-contained MP4 fallbacks and PDF; current project fallbacks are terminal typescripts, not portable conference video. |
| Sep 19–21 | Rehearse twice on the presentation laptop, including offline playback and fresh-install attendee workflow. Keep the successful presentation within 45 minutes. |
| Sep 22–23 | Freeze deck/media/release; carry local and second-device copies. Verify links, fonts, embedded media, and actual display scaling. |
| Sep 24 | Use a short preflight. Switch promptly to the recorded run if a live dependency fails. |

**Best enhancements per unit of effort:** (1) completion/escalation beside breach, computed from existing records; (2) a clear before/after R6 state-transition slide; (3) an actual human veto with proof no subsequent action executed; (4) a bounded category extension if retaining the CFP's multi-category claim.

**Defer:** larger-model migrations, full eight-node tensor parallelism, new serving-stack experiments, a large dashboard, broad taxonomy expansion, and the separate post-sweep mutation/judge-variance program in `~/grrcon-prompts/claude-code-prompt-unprompted-evidence.md`. Those do not address the immediate presentation gaps as efficiently.

## 7. Review scope and limits

Examined the project documentation, manifests, selected raw records across the complete 810-record analysis set, later L1 records, generated chart JSON/PNG, replay scripts, tests/CI configuration, and relevant home-directory material: `~/evidence`, `~/grrcon-prompts`, the prior cluster audit, ATBench evaluation outputs/scripts, runtime router, `~/halctf-agent`, and local AgentDoG source documentation. Unrelated personal files, private credentials, shell history, and model-weight contents were not needed. The old `eval_v2.txt` is an unrelated KSTE run that timed out; it supplies no completed result for this presentation.

Model-list and container/host checks are point-in-time observations, not load tests. The ten cluster-marked tests were not rerun. No new attack campaign, inference benchmark, service restart, repository publication, or communication to another person was performed. Code fixes and additional experiments in this document are recommendations, not completed changes.
