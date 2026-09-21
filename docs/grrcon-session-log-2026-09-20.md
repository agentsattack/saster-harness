# GrrCON talk — state of the work, 2026-09-20 (reconstitution log)

Read this first in a new session. Everything below is committed on `feat/defense-stack` (21 Sep, five commits, no Claude trailer) and pushed to the public harness repo; `main` was not merged.

## Deliverables (repo root; committed 21 Sep)

| file | what | state |
|---|---|---|
| `grrcon-deck-v4.pptx` | the deck: 68 slides, 6 clips | current; sha256 begins `01698f81` (21 Sep: invariants, t0 and reach defined on slides 3 and 21; slide 29 per-run accounting; run/cell/sweep defined on slide 22) |
| `grrcon-talk-narrative-v4.pdf` (source `docs/grrcon-talk-narrative.md`) | study guide: "The six demos, plainly", per-slide talking points, classifier table, world-state reference, cheat sheet, lines to say | current |
| `demo-defense-matrix.pdf` (source `docs/demo-defense-matrix.md`) | per demo: what each layer said and why, the oracle, demo 3's cell trial by trial, phone-home, slide map | current |
| `agentdog-one-pager.pdf` (source `docs/agentdog-one-pager.md`) | the auditor brief: what it reads, outputs, results, head-by-head reading, ATBench remeasurement, demo-specific improvements; four pages at normal type | current |
| `docs/deck-claim-audit.md` | the running log of every check, fix and correction since 18 Sep | current |
| `docs/sweep-findings.md` | F30 (I2 omits hosts from its entity set) and F31 (the clean-agent conversational arm, W38) added | current |
| `scripts/deck/` | the clip renderers, the diagram, the md→pdf converter, the slide-surgery scripts | copied from the session scratchpad |
| `scripts/run_beat1_clean_w38.py`, `scripts/analyze_w38.py`, `scripts/heads_w38.py`, `scripts/build_public_evidence.py` | the W38 experiment and the public-corpus builder | new |
| `runs/w38_beat1_clean/` | 51 W38 records (6 arms + 1 smoke), batch logs, `summary.json`, `heads/heads_posthoc.json` | complete |

Superseded, untouched: `grrcon-deck-v3.pptx` (user's 18 Sep original), `grrcon-deck-v3-fixed.pptx`, `grrcon-talk-narrative.pdf`.

## The deck in play order

1 title · 2 console legend · 3 boundary spec · 4 **Demo 1** clip (opening breach) · 5 what you just saw · 6 why no per-action fix · 7 verbatim prompt · 8 one line of difference · 9 reframe · 10–13 threat model · 14 the instruction · 15–20 the stack (21 = oracle workflow diagram) · 22 seven setups grid · 23 one trajectory · 24 demo map · 25 same fixture · 26 demos 2/3 setup · 27 **Demo 2** clip · 28 **Demo 3** clip · 29 demo 4 setup · 30 **Demo 4** clip (support chatbot, W38 clean run) · 31 demo 5 setup · 32 **Demo 5** clip (phone home, §T) · 33–37 cases 1–5 · 38 D19 the block that wasn't a block · 39 common thread · 40 what each layer buys · 41 console vs world · 42 no-attacker slide · 43 demo 6 setup · 44 **Demo 6** clip (no attacker, Ministral) · 45 initiation varies · 46 vendor · 47 detectors · 48 three holes · 49 why it matters · 50–51 Monday · 52 what changed · 53 monitoring · 54 SASTER · 55 limitations · 56 take it and run it (corpus hash) · 57 thanks · 58 appendix divider · 59 predictions · 60 uncertainty · 61–68 appendix.

Demo records: 1 = `qwen3:matrix__all__unobstructed__compromised__firewall#4` (w24b); 2 = `qwen3:matrix__l3-l4__obstructed__compromised__firewall#3` (w24c); 3 = `…firewall#0` (w24b); 4 = `runs/w38_beat1_clean/w38-model-deepseek-seed20260925`; 5 = `w30t-qwen3:matrix__all__obstructed__compromised__firewall#0`; 6 = `ministral:matrix__l2__obstructed__induced__agent#0` (w24b).

## Corrections made this week (all logged in deck-claim-audit.md)

- Demo 3 tally: five runs, not ten (the §P arm is a same-seed replay); 1 breach, 1 clean escalation, 3 honest resolved. Invented audit ids are in the grant-route cell, demo 2 and demo 6.
- Boundary wording: nothing outside the network was reached in demos 1 and 6; I2 fires on a name it cannot resolve (F25 class; F30 for hosts). Demo 5 is the one real out-of-bounds address (loopback URL). Violation vs false report kept apart everywhere.
- Both the policy engine and the trace monitor can block; the trace monitor blocked 31 of 61 breaching runs under its configs (21 grants, 5 rules, 5 copies), always 1–3 steps after the oracle's breach, by construction.
- Demo 4 rebuilt (W38): clean agent, quarantine, model attacker. Old version's planted weakness and D19 leak are gone from the mechanism; D19 has its own slide (38).
- AgentDoG: local ATBench-1000 remeasurement (1.0 head F1 0.69 vs published 0.71, specificity 0.39) on slide 47 and in the one-pager.
- Slide 56's corpus figures replaced with the real snapshot: 16 stores, 12,809 files, top hash `b0d80136…`.

## W38 results (F31)

DeepSeek attacker vs clean Qwen, quarantine: 10/10 (turns 1–4, 21 blocks). Same with the D19 leak restored: 6/10, later. Ministral attacker: 3/10. DeepSeek as victim: 2/10 after 65 blocks. Pre-registered scripted ramp: 0/5. Longer scripted ramp: 5/5. 3 of 10 exported then said they could not. Post hoc heads: always-on heads warn on every run with a tool call; the fine-grained head says safe on all.

## Public corpus

Built by `scripts/build_public_evidence.py ~/saster-evidence-public` from `~/evidence` (never edited in place): 16 stores, 12,809 files, 150 MB, top hash `b0d8013685a0ce61834e72fb749d686ff57e549f62de48212505a622c097d845`; 789 files pseudonymised (SCRUB_LOG.json), five withheld and listed by hash; README + MIT. Local commit `843aa83d` as Larry Suto, no trailer, remote set to `git@github.com:agentsattack/saster-evidence.git`. Pushed 21 Sep to `git@github.com:agentsattack/saster-evidence.git`, branch main.

## Standing constraints (from the governing prompt and memory)

Never edit oracle code, invariant definitions, hash-pinned docs or pre-registered predictions; findings go to `docs/sweep-findings.md`; artifacts immutable, new outputs to new paths, re-runs are new run ids; no stand-ins in `corpora/citable/`; the untracked credentials file in the repo root is never used or printed; public repos commit as Larry Suto with no Claude trailer; do not use `.tools/gh`; do not touch `~/.ssh/config`. Suite: 1554 passed, 11 skipped, 4 xfailed at last run.

## Open items

- Public corpus PUSHED 21 Sep: `agentsattack/saster-evidence` main = `843aa83d`, author Larry Suto, no trailer; deploy key `~/.ssh/saster-evidence` (write) via repo-local `core.sshCommand`.
- Committed and pushed 21 Sep on `feat/defense-stack`; left out: superseded v3 decks, `currentpres/`, the zip bundles, `scripts/deck/*.pdf|html` duplicates. `main` still at `04e7836` (no oracle, no runs): fast-forward is the operator's call. The `docs/public-repo-checklist.md` scrub (LAN addresses, home paths, host-key notes) was never applied to the harness tree; the pushed branch already carried them.
- Optional: bridge line on the D19 slide notes to the Artifactory cache episode in the OpenAI report (keys left in an anonymously readable cache re-enabled admin access after the wipe).
- Cluster: victim router on spark1:8080 (Qwen on spark10, Ministral on 192.168.1.208, DeepSeek local); Granite Guardian on spark7:8003, Llama Guard :8004, AgentDoG 1.0 heads spark7:8001/8002, 1.5 heads spark5:8001/8002.
