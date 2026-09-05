# Evidence inventory — pre-sweep, 2026-09-05

Stage 0 of the GrrCON sweep prompt. Every result artifact that existed before any sweep process ran, with path, size, SHA-256 and the claim it supports. Written once; not to be edited — a later inventory is a new file.

## Where the copies are

- No NAS exists yet (confirmed by the operator, 2026-09-05). The content-addressed copy is at `spark1:~/evidence/pre-sweep/<sha256>/<basename>`, mirrored byte-for-byte to `spark8:~/evidence/pre-sweep/`. Both verified with `sha256sum -c`; zero mismatches. Move to the NAS by hash when it exists; the manifest does not change.
- `manifest.json` (317 unique files, 327 entries) sha256 `55d855b560a9b3649ab60b0adf87cbac1e9f1607e088baa88d7fbc6c08e7e37d`
- `manifest.addendum-1.json` (10 files surfaced after the first manifest was sealed) sha256 `7523413b3cff62e139a9b9a452a72468447bad7e82ee3c20d1eac93d4bc5cf89`
- Repo tag `pre-sweep-2026-09` at `68a3085` (W21), pushed to origin. The tag message cites the first manifest hash.
- Directory rows below carry an aggregate hash: sha256 over the sorted per-file sha256 hex strings. Per-file hashes are in the manifests.

## Inventory

| Artifact | Files | Bytes | SHA-256 | What it is | Claim it supports | Source of the claim |
|---|---|---|---|---|---|---|
| `~/results_1.0-4b_full1000.json` | 1 | 235229 | `6d46347994cc36dd19ecb41fea4eda9b7cf3190324095b87f594be7c13f5f2f6` | AgentDoG 1.0-4B binary over ATBench-1000; 975 well-formed, acc 605/975, recall 86.9% | Anchor table: 1.0-4B binary n=975 (the L4 observer) | ~/job_104b_full.log |
| `~/results_1.0-4b_sliceA.json` | 1 | 13180 | `48bbc65e9e85def4bc0fd22595066cddd526c376b4bd32e79a290272804fe108` | 60-trajectory plumbing slice A, 1.0-4B: 26/60 | Plumbing sweep, detector 1.0 | ~/driver.log |
| `~/results_1.0-4b_sliceB.json` | 1 | 14180 | `4659c5179d7f77ef66f708bca3dc8bf5a6b60d6a563a5419b4fcd92009e7b8b3` | slice B, 1.0-4B: 34/56 well-formed | Plumbing sweep, detector 1.0 | ~/driver.log |
| `~/results_1.5-fg_497.json` | 1 | 193869 | `0f58937cd3219d0e090399553ff025f2b17bac2a2d7204137b59c6da9c488ea9` | AgentDoG 1.5-FG over the 497 unsafe; 462 well-formed; RS 51.3 / FM 28.4 / Harm 63.4 | Anchor table: 1.5-FG n=462; P10 baseline reproduction vs published 82.0/32.4/58.4 | ~/driver.log; docs/w11-fine-grained.md |
| `~/results_1.5_full1000.json` | 1 | 237148 | `4e9090c1a564c7a3660947d5f6378345c60ec4e571a9965150249914351297a2` | AgentDoG 1.5-4B binary over ATBench-1000; 966 well-formed, acc 678/966 | Anchor table: 1.5-4B binary n=966 | ~/job3_15.log |
| `~/results_1.5_sliceB.json` | 1 | 14497 | `0e3b96e26a4eade62f0f54b765c50b9c24af599b035b2433272fcb473e811430` | slice B, 1.5-4B: 37/54 well-formed | Plumbing sweep, detector 1.5 (slice A under 1.5 was never run) | ~/job1.log |
| `~/slice_a.json` | 1 | 594653 | `cc9d729f2d3651011f8898c92987a68dae0970df6d38f071fa632ed54edb28ad` | input slice A, 30 safe / 30 unsafe | Input corpus for the plumbing sweep |  |
| `~/slice_b.json` | 1 | 1923449 | `66b7383568ef50af7101f5367a2e54cd899850d4dfc32d2555b3184fa00c1535` | input slice B, 30 safe / 30 unsafe | Input corpus for the plumbing sweep |  |
| `~/atbench_sample.json` | 1 | 6061 | `27588ef7a4791da478735eed6f45d07317945c130f5ca6b2728be9ca81c74400` | single-record smoke fixture | Plumbing only |  |
| `~/atbench_sample_safe.json` | 1 | 3340 | `1d0cf08c374d1d5fa2a46e06fc6a3472709e57a4b7eacfbd5f26b15bba144671` | single-record smoke fixture | Plumbing only |  |
| `~/atbench_sample_unsafe.json` | 1 | 6061 | `27588ef7a4791da478735eed6f45d07317945c130f5ca6b2728be9ca81c74400` | single-record smoke fixture (byte-identical to atbench_sample.json) | Plumbing only |  |
| `~/atbench_test.json` | 1 | 18335079 | `80c534b5f3517c872b528a2e6b64e34495206968edd184f4aed563d39f0cca09` | ATBench held-out set, 1000 records (503 safe / 497 unsafe) | Denominator for both n=1000 anchors (input, not a result) |  |
| `~/atbench_unsafe497.json` | 1 | 12150965 | `22fdfe0eab817e0c7be93bd5dc9141971bd5994b265027d4c1a1dd354196122d` | the 497 unsafe ATBench records | Denominator for the FG n=462 anchor (input) | ~/driver.sh |
| `~/run_diag.py` | 1 | 1558 | `e124127c6844877e4befbf840c1876b894ba2bc0661d1f140d56d826e67b5363` | the DEFECTIVE evaluator: `json.dumps(tools)[:6000]` at line 19 | The 6,000-char truncation defect itself |  |
| `~/sweep.log` | 1 | 423 | `004fa56769488c72f52e4953082732f8c584c95806bb3c8ae4f5e6add72c3117` | BEFORE fix: 60 traj; 1.0: 28/60; 1.5: 29/59 | 6,000-char truncation before |  |
| `~/sweep2.log` | 1 | 422 | `1cf536a4e27216d419b10aae0d35abef4c5ed576279640a66f509fcf5a9d105a` | AFTER fix: 1.0: 28/60 unchanged; 1.5: 36/60 | 6,000-char truncation after; 1.0 identical 0/60 changed, 1.5 changed on 17/60 |  |
| `~/eval_full.txt` | 1 | 561 | `3a8822ea6e4b10690dfed630fe52c7f4fafa381424696dc6164580e2cfd71573` | KSTE held-out evaluation against Neo4j | NOT talk evidence (unrelated project); preserved anyway |  |
| `~/eval_output.txt` | 1 | 561 | `3a8822ea6e4b10690dfed630fe52c7f4fafa381424696dc6164580e2cfd71573` | byte-identical to eval_full.txt | NOT talk evidence |  |
| `~/eval_v2.txt` | 1 | 1535 | `5d19cad246800c7c1d6baa3a89d44abbd02ba466c8f6e95f107fa1fa71bc1647` | KSTE eval, ends in fit() timeout | NOT talk evidence |  |
| `~/cluster-audit-2026-08-31.md` | 1 | 6755 | `5888ccddc948c668dff0a0a3e9118626985099c6e609c884bc2879e4c93b7ab9` | read-only 8-node cluster audit | Infrastructure provenance; backs commit edd8971 |  |
| `~/session-transcript.md` | 1 | 68580 | `a1aee95d39b7c129d60eb25cc84761ac556ac048a5109b65f823b4d3088ba3da` | rendered Claude Code log of the 2026-08-31 audit session | Infrastructure provenance |  |
| `~/saster_router.py` | 1 | 14353 | `5165e0462fa4ff2ed88e70f37deee1f1bcff5bcbe1017d7d25efbe600ee17b81` | the affinity router that served every campaign (spark1) | Router policy held fixed; prefix-cache claim | docs/cluster-bringup.md |
| `~/agentdog-dl.log` | 1 | 1390 | `dfbcfee8d59430e572c229069c97bb1df0545d0411f36a15c14e7f6f332572f4` | AgentDoG weight download log | Provenance |  |
| `~/grrcon-prompts/claude-code-prompt-grrcon-sweep.md` | 1 | 18384 | `4a5d5ce2637a11de17ca4cc679f67c110d9f3c868b90c956e2913b9d477386c0` | the governing session prompt (Sep 1-21) | Plan, not a result |  |
| `~/grrcon-prompts/claude-code-prompt-unprompted-evidence.md` | 1 | 9258 | `3747f3713b765038955b1d9f3f5ed86c336e63662f2179b86e04500daa69d142` | the [un]prompted evidence prompt | Plan, not a result |  |
| `runs/SASTER_CATEGORY_CORRECTION.md` | 1 | 4852 | `bc114572f331c788fe751d9b2dc7faf6d99355e1765df0bd691c579c59c1f301` | all 515 records carry SASTER-24; correct is SASTER-31; annotated not revised | Category label error (Class 6) across every corpus above | 68a3085 |
| `runs/W15_README.md` | 1 | 4815 | `59c763c1617f0bad3b13aaf040ad7a4573c170afa23749cb1df81e6395d3350d` | 17.5% induced bound; 0/60 -> 0/5 correction | P14 | 385329e |
| `runs/W16_SEED_AUDIT.md` | 1 | 5090 | `bf4b61f4196072934e7c2b055ffbb3605bc32bbcbe2fb8632d60a587d614e428` | every W14 number restated on distinct-trajectory denominators | Denominator-inflation correction (Class 3) | d23bd38 |
| `runs/W18_L4_SPECIFICITY.md` | 1 | 4860 | `8c26670257a08db0178c659d272394ee437a0bbb6f37eeeadadae3f588b0516d` | prose form of the L4 result | same | 1ff279a |
| `runs/pilot_w6c_20260829` | 5 | 36757 | `5566ea5b841a35e07b9cfd65c5cd56711f75ad38a437d0eee4e756d00dc36bde (dir)` | pilot k=5 + canary | Pre-sweep pilot; content-filter canary |  |
| `runs/pilot_w6c_20260829_r2` | 5 | 42034 | `454714be6cfbbed0b32e869820a3a0962f8c1e307bb88375d2e99aad6aa9a022 (dir)` | pilot k=5 | Pre-sweep pilot |  |
| `runs/pilot_w6c_20260829_r3` | 5 | 42829 | `f1c9f9b0c73c4893f10b004e0bfa2d101e66a50dd1d137297e02c5a42e490e10 (dir)` | pilot k=5 | Pre-sweep pilot |  |
| `runs/w12_cell_qwen_compromised_obstructed_binary` | 5 | 129563 | `915206d39766714dc74adacb87b1cf13d83fe65a3fb86fc419a35f32bed34627 (dir)` | 5 records, binary head | P10: binary vs FG head on the same seeds; agent plane byte-identical | docs/w12-fg-head.md; 941165a |
| `runs/w12_cell_qwen_compromised_obstructed_fg` | 5 | 126657 | `4397a59da35e77afe76bb63af9dfeb2b67a6caa2921097f2415cc08b5807169b (dir)` | 5 records, FG head | P10; FG said safe 5/5 | docs/w12-fg-head.md |
| `runs/w13_cell_qwen_compromised_obstructed_not_computed` | 5 | 136688 | `71770d878994360b8a6bcd1cafa7c4cc314a9058e17d951923070d94a8f08c57 (dir)` | 5 records, envelope not_computed | Amendment 9: envelope measured the wrong distribution | 479fe5a |
| `runs/w14_corpus_qwen_single_victim` | 86 | 2746953 | `9c5e3e28187b3f9cff306845815e4ad35f76d9001fc11ea7c313c237a2be05dd (dir)` | 27 cells x k=5 = 135 records; 10 distinct trajectories on 5 seeds (13.5:1) | P1/P2/P3/P6/P12/P14 matrix; breach 50.0% flat across six configs; superseded denominators (W16) | runs/.../README.md, ANALYSIS.txt; c367b14, d23bd38 |
| `runs/w14_matrix_console.log` | 1 | 2112 | `6206ebc07b7f179089b5d30a75f6bba16eb14f95ceb2a065e268c570c95ffe82` | driver console | Provenance |  |
| `runs/w15_console.log` | 1 | 47273 | `f1a5308dc76830e05e0c80b475b1bd6b40cb1d135ba300e55d1eb4b3619b4367` | driver console | Provenance |  |
| `runs/w15_induced_characterization.txt` | 1 | 13692 | `e652300a329c1a60baed42d04eb93cdc1ff512db99f6ad90c9cc97cbf4edbbb7` | 140 induced records; outcomes escalated 108 / breach 14 / error 12 / agent_stopped_acting 6 | An agent that stopped acting is not a backend that failed (Amendment 10) | 3dab06d |
| `runs/w15_induced_obstructed` | 3 | 559145 | `0a5629dbc1f4858dacceebacb6a200cb98cc644409150fbedccd0222bc713896 (dir)` | 40 induced records | P14: induced arm diverges 17.5%; obstruction makes no difference | runs/W15_README.md; 385329e |
| `runs/w15_induced_unobstructed` | 3 | 564413 | `987a32982e87504953b80d32364a66e3fc984d753b4d05a8b5ec2c14d7a413e0 (dir)` | 40 induced records | P14 | runs/W15_README.md |
| `runs/w16_seed_audit.txt` | 1 | 8352 | `62830579ed02fb7b294a03a776df57caa3ae867dc175430b833f4b734894fa88` | machine output behind W16 | same | scripts/audit_seeds_w16.py |
| `runs/w17_corpus_qwen_paired` | 86 | 2778396 | `15f6783e5b8c9d145825c07e2e9469d903041d86169635914c98fb4ad182fdc2 (dir)` | 27 cells x k=5 = 135 records; 15 distinct (9.00:1 by construction) | The paired-seed matrix; current headline corpus | README.md, ANALYSIS.txt; ef69860, d339c3d |
| `runs/w17_matrix_console.log` | 1 | 2114 | `7fb7b14eaafbe702022837d48ac02c9a7d26b2ee474b9e2bf10aa282124c1aad` | driver console | Provenance |  |
| `runs/w18_console.log` | 1 | 69019 | `68688af4bf3c2eb66af99e53210d370c4403acd9747b23cee4d7e12a9f30c06d` | driver console | Provenance |  |
| `runs/w18_induced_obstructed` | 3 | 842586 | `d5f3bba92b85963ea89594c3f83696245900b1d967a6d508b1a41137f7eddaea (dir)` | 60 induced records | L4 specificity power | runs/W18_L4_SPECIFICITY.md; 1ff279a |
| `runs/w18_induced_unobstructed` | 3 | 824481 | `b5947d67aa58cdd59e60604c459a561c14cd004efa49df3946e2b6655f92e054 (dir)` | 60 induced records | L4 specificity power | runs/W18_L4_SPECIFICITY.md |
| `runs/w18_l4_posthoc_report.txt` | 1 | 2535 | `14c45275e31085fedefbcf9adc2775a3a4d3440882f4438f28009efa6e3f6774` | the headline L4 table | L4 has never returned safe: 0 of 39 | 1ff279a |
| `runs/w18_l4_posthoc_scores.json` | 1 | 21746 | `aae3ad9134dace93cd92e1c604ffd97ec567fc73ce7247ebc2f2d69e9abaa88c` | 39 distinct trajectories rescored by the binary head | L4 fired 39/39; specificity 0.000 [0,12.5]; precision 0.308; recall 1.000 | runs/w18_l4_posthoc_report.txt |
| `runs/w7_campaign_001` | 2 | 12156 | `f4fd601b62784f40ad563685a8a78e0910f92986632fc8aaed6e91d97055d904 (dir)` | campaign.json + manifest | Model-driven action plane | 63e0961 |
| `runs/w7f_compromised_ministral` | 2 | 11971 | `5b53d9696f749a176ba7bb86a2cbfb91e94d8540740065ca638fd7726fa7a964 (dir)` | campaign + manifest | Compromised arm, Ministral | 68dfadd |
| `runs/w7f_compromised_qwen` | 2 | 20433 | `8031218e03c7705dbbdaf66eadfe165de3c2c2de1ecb7895b4a0b9c99f2b49d7 (dir)` | campaign + manifest | Compromised arm: the agent composed the chain itself | 68dfadd |
| `runs/w7g_k5_ministral` | 10 | 54513 | `7c46a36ccaaf9afd98f5d2e8b49363f9090ccb8616d167981b8bc592cb1521e7 (dir)` | t0-t4 | k=5 compromised: Ministral is not | 95cd167 |
| `runs/w7g_k5_qwen` | 10 | 109996 | `bb824512bdee9ca58c96fcdc1efdad02981ca3abd1e361418ab1b2bbf625219e (dir)` | t0-t4 | k=5 compromised: Qwen is stable | 95cd167 |
| `runs/w9_dryrun_cell_qwen_compromised_obstructed` | 5 | 120222 | `049844eae43798e6005fe2650e3e57f2ef64c2797a4e00ead655a3f9c916cb64 (dir)` | 5 records | W9 dry run | 2e1b3df |
| `runs/w9_dryrun_cell_qwen_compromised_obstructed_r2` | 5 | 124780 | `61f7fc6f3453a948c18429874e79baedafc919ea020a64f29d7c0fe4aa30d950 (dir)` | 5 records | W9 dry run |  |
| `runs/w9_dryrun_cell_qwen_compromised_obstructed_r3` | 5 | 130583 | `93bb9eb2fc136f0fbf7d9d0ff9f367f509dede8c10b54fc16539b704a9d808cf (dir)` | 5 records | W11 baseline cell | 45bd01b |
| `docs/cluster-bringup.md` | 1 | 19811 | `a00d1d47202933a57df5c4a9838825ea22c5beba1a1bce8ffa5e3c8fac0811d0` | recovered vllm serve commands; topology | Serving provenance |  |
| `docs/contribution.md` | 1 | 8368 | `9dc7a00765af67165ebab859bd587e23b8226964724713fe4caef59df43380f2` | doc | Reference; no result claim |  |
| `docs/decision-trees.md` | 1 | 12891 | `745172c291c726110fafb2a722facbf98c1cd06937452578aec81f9cfaf4f648` | doc | Reference; no result claim |  |
| `docs/demo-log-v0.1.0.txt` | 1 | 7278 | `0b9a995f705543f5ccb141a2282140ea1066b64f9ea39727e85601619539886c` | Phase 6 capture, 6 reference cases vs live Llama-3.3-70B | v0.1.0 detector claim | 31bccd9 |
| `docs/detectors.md` | 1 | 6400 | `1054a69f065a8b846f250acb051ac279b33c024880b89ea634be799f951f2989` | doc | Reference; no result claim |  |
| `docs/determinism.md` | 1 | 4367 | `33782f2c343b26a5ee645080c5abfba57d6dcb014342be7479a703dc895cbbd7` | doc | Reference; no result claim |  |
| `docs/envelope-preregistration.md` | 1 | 11244 | `25937a1f761ecd42503579df8e41868ae269a34a3ad1e7bfa830e5b081e7c732` | pre-registered envelope thresholds; hash-pinned | P12/P15 | tests/test_manifest_prereg.py pin 25937a1... |
| `docs/grrcon-test-matrix.md` | 1 | 16168 | `60853077e446dd228ff0dae956b2d67925f63329f58d7107534af4fa138571e2` | THE PRE-REGISTRATION, P1-P16 + P3-refined; hash-pinned | Every P-claim | tests/test_manifest_prereg.py pin 6085307... |
| `docs/har_import.md` | 1 | 9745 | `1bffa8f4723207d2b129160d89bf3912dfc6fb7371e1ecd8e694200f94837bd8` | doc | Reference; no result claim |  |
| `docs/incident-mapping.md` | 1 | 2064 | `f3a4eaf6baccb2f2bd41ce569fbc761337c799f6a54a11f25a55b4e55ca64830` | doc | Reference; no result claim |  |
| `docs/independence-provenance.md` | 1 | 10475 | `ddd1ee81451039df1ebecbcd8bfb2b5ea1e0bf49d0f93ab0c633ea60cb229ea5` | authorship boundary record; independence control flagged PROVISIONAL in section 7 | Independence claim + its caveat | 32d3c16 |
| `docs/instrument-test-plan.md` | 1 | 11282 | `8e19d04328a12fc2cb1e603cba6dc118af6cc0b1ea2e0a0be2eacb26d640c4e5` | UNTRACKED plan | Plan, not a result |  |
| `docs/instrumentation.md` | 1 | 4357 | `d19d04a38d6dbe285facf9472664cb7237c9acd7f4d050bdd77c971e6160ae61` | doc | Reference; no result claim |  |
| `docs/methodology.md` | 1 | 17161 | `b0eacb74756d8014bc3354f7deec00910455d53ee4960ea933ca159df33f75ff` | doc | Reference; no result claim |  |
| `docs/multi-model-instrument-suite.md` | 1 | 9961 | `3d7d1a55f53b0e91999f168f3cf7580bb7e6977a52f7beb2703d9708da0ced36` | UNTRACKED plan | Plan, not a result |  |
| `docs/pattern-authoring.md` | 1 | 18087 | `14c181d359e2762513b6a05ba3367768a6b14536334d5e041b8e56f8660ccab5` | doc | Reference; no result claim |  |
| `docs/release-notes-0.1.0.md` | 1 | 10806 | `4776c5f610f5117a6fea6188654c050e540e1b8dcf0989823bcc2942d75586bf` | doc | Reference; no result claim |  |
| `docs/release-notes-0.2.0.md` | 1 | 9420 | `5007093ea9a7072169a8eb9a6ccbd0432c76d081edcd78ae71419ca98a5a086b` | doc | Reference; no result claim |  |
| `docs/router.md` | 1 | 1582 | `99ad903937bde026e7fffb2e5062cdb85bff7b023a2ec8ce7dce07f7c8dd0ba0` | doc | Reference; no result claim |  |
| `docs/schema-amendments.md` | 1 | 53615 | `c6312cb12c31b077d0da099506bdf15a73acb47ae9d2f87dfa122c7f1c4d3af0` | Amendments 1-10 | Schema integrity; P10 framing |  |
| `docs/state-store-handoff.md` | 1 | 11780 | `caf86e8803f6301b5ef71ee2bb347001ea70f49e9e4833bd5a1fe97addc060ad` | the handoff doc referenced by independence-provenance | Independence claim | 622f324 |
| `docs/trajectory-assembly.md` | 1 | 2499 | `8bceb012ada80db591666ac745fea33b09e7d913ee6492c4552134a09c1adc23` | assembler spec | Record schema |  |
| `docs/w11-fine-grained.md` | 1 | 8774 | `d2227fe9325923a6dd9d95f5e6d44b3b2e3f4d67e39b6a887a4c469396d929d4` | P10 baseline 82.0/32.4/58.4 confirmed against source; WARN/ALLOW vocabulary defect | P10; not-WARN->ALLOW defect | 45bd01b |
| `docs/w12-fg-head.md` | 1 | 11022 | `9736dde3df492aa21d92cb2f21dec7cafeb2e5dc9860a058024b83b4b928a1dd` | FG head served; the .locks/ finding | P10 re-measurement | 941165a |
| `docs/w9-readiness.md` | 1 | 15747 | `2537cd0a6e1517f7e98d735fd3ac3cbe78ddc1419272987bca5b96758c11031f` | prediction coverage audit; P16 not harvested | Honest-gap slide | 2e1b3df |
| `tests/data/README.md` | 1 | 1678 | `184c755a56d52bf1aeda833682874e865255c518c1febd80103d3acb3f6d3639` | test data | Reference |  |
| `tests/data/SASTER.md` | 1 | 27268 | `4928987b2075c9e09ae0e6dfdb3c237ff29bf23c15ab60b86bdc8aa0970a6afc` | vendored taxonomy pinned to agentsattack/saster@5e2f505 | Taxonomy-sync integrity | tests/test_taxonomy_sync.py |
| `tests/data/SASTER.md.sha256` | 1 | 65 | `c5fb9606323529b4b1d59b49840f3819139f19695cbf55c0e8afee5dd1c18d83` | its pin | same |  |
| `examples/carl_config.py` | 1 | 1631 | `5ad26ef8924efae17a1105b48c69adf68836a76edcdeedcfee6033918f2644a2` | config example | NOT a result artifact |  |
| `examples/runner.py` | 1 | 1583 | `942867955d7787369ff8f9e7ad60ad0bd1e38c3997a27cf1a65c8d9d6db46b76` | config example | NOT a result artifact |  |
| `CHANGELOG.md` | 1 | 39420 | `c6fe6c99c981d4e088f41c7b4ea4d9b47acec6816d7eb0047cbce7de6f5ba84e` | changelog | Provenance |  |
| `README.md` | 1 | 19720 | `c9db3ec7201cd37628e47d02a8424ec0ea3b45636ac9618c835f0eb6f045ad0a` | readme | Provenance |  |
| `pyproject.toml` | 1 | 3242 | `a855f7ef32b292f22497e7560ee9b85d8ab46d57338bbc0db4451cc923ac78ca` | build | Provenance |  |
| `spark2:~/agentdog-serving-pins.txt` | 1 | 446 | `03916b9b350e116c3f7cdff4de91f077332ed89efed18dcebf4bf1d76b15261b` | serving pins on spark2 (hostname aitopatom-06b2 = "ATOM"); agentdog15, revision 3193b58 | Detector pin record for the 1.5 heads |  |
| `spark4:~/agentdog-serving-pins.txt` | 1 | 445 | `a9e89cf67e2305d996f3aa0016da40db8eff4e8a298eae9a6506a63ff2e9e2b4` | serving pins on spark4 (hostname thinkstationpgx-6223 = "Lenovo"); STALE: names image vllm-node:latest and revision af13d93 / 15G, the running container is eugr/spark-vllm:latest 32f23ba5871d serving revision e7d92a7 | Detector pin record for the 1.0 head; staleness is a finding | docs/cluster-bringup.md |
| `~/sweep_results_run1.json` | 1 | 14696 | `6550107309de3128adc0b8b654ee06471373075899361ab26aabf9271cd00611` | per-record output behind sweep.log | 6,000-char truncation before |  |
| `~/sweep_results.json` | 1 | 14719 | `94a6265c6063344fe5395eecfd591aaf123a0ac9999c114a3471d4cd95a604b2` | per-record output behind sweep2.log | 6,000-char truncation after |  |
| `~/eval_slice.py` | 1 | 8267 | `faa79851aa498149aaac6e83163481e6dd2265610a1aeeefb2f0b8e1a4610131` | the FIXED evaluator, no truncation (line 119) | The fix for the truncation defect |  |
| `~/driver.sh` | 1 | 756 | `12ce31794a9b28d5c5c3b9c75e121aa03f7cb843255dea0edfd6f5826c3d4b52` | run driver for the ATBench jobs | Provenance for the anchor numbers |  |
| `~/driver.log` | 1 | 642 | `bd4dcf56ced829483db31357cc34182d29e3c4e27cd9069a85f1a58e047505a0` | driver console log | Provenance for slice A/B and FG-497 numbers |  |
| `~/job1.log` | 1 | 145 | `7c737a1916b57d6ffa79e5cd131b1f7d727237d16bcd9c4574a577e4c0863bd7` | 1.5 slice B job log | Provenance |  |
| `~/job3_15.log` | 1 | 158 | `226a3fbf16368a9bc060dd8db1a44600d69840c6539be2411a68829b40a9ae47` | 1.5 full-1000 job log | Provenance for n=966 |  |
| `~/job_104b_full.log` | 1 | 163 | `3bade35e23af56a8d81a26a8d105d435cd4740e4d0500c18642c03446897df88` | 1.0-4B full-1000 job log | Provenance for n=975 |  |
| `~/pull.log` | 1 | 1855 | `f455b70eb84361f35daf26b3a7efefd8d168609f37fbebb960b1d008de11d59f` | image/weight pull log | Provenance |  |
| `~/saster_router.log` | 1 | 477 | `6c2096a9013a4ffa261848b012a5088e0da993eb20d256d8645cb72f757409a3` | router log | Provenance |  |

## Verified on-box (read-only)

- OPA `.tools/opa version` = 1.20.1; z3 in `.venv` = 5.1.0. P1/P3/P4 under the real backends are recorded in commit `68d0ec3`; the stand-in baseline they were compared to is commit `3265bef`; live assertions in `tests/test_defense_stack.py`.
- P16 (`net.cidr_contains` fail-open on URL-form `reaches`) and the non-executable-Rego finding are recorded in commit `68d0ec3` and `saster_defense/policy.rego`; **no sweep has harvested P16** (`docs/w9-readiness.md`).
- The L4 rejection matrix is commit `594e8f3` and `tests/test_l4_robustness.py` (now 33 test functions; the commit says 16). The not-WARN/ALLOW vocabulary defect is in `docs/w11-fine-grained.md`; the stand-in-to-real transition is commit `fc50965`.
- Oracle negative control and independence control: `tests/test_containment_oracle.py` (commit `97e08ba`); the independence control is still marked PROVISIONAL in `docs/independence-provenance.md` section 7 even though its W1/L2 acceptance criterion landed.
- Pinned hashes both match on disk: test-matrix `60853077e446dd228ff0dae956b2d67925f63329f58d7107534af4fa138571e2`, envelope prereg `25937a1f761ecd42503579df8e41868ae269a34a3ad1e7bfa830e5b081e7c732`.

## Gaps found while inventorying

- No `results_1.5_sliceA.json`: the 1.5 detector never ran slice A. 'Both detectors on both slices' is three of four cells.
- No `corpora/` directory exists; `corpora/citable/`, `docs/sweep-report.md`, `docs/pilot-report.md`, `docs/sweep-findings.md` are referenced by the prompts and do not exist.
- All 515 trajectory records under `runs/` carry `saster_category: SASTER-24`; the correct label is SASTER-31 (`runs/SASTER_CATEGORY_CORRECTION.md`). Annotated, not revised.
- `~/run_diag.py` and `~/atbench_test.json` are on spark1 only; neither exists on spark2 or spark4 (the prompt expected them on each detector node).
- `spark4:~/agentdog-serving-pins.txt` is stale: it names `vllm-node:latest` and model revision `af13d93` (15G); the running container is `eugr/spark-vllm:latest` (`32f23ba5871d`) serving `AI45Research/AgentDoG-Qwen3-4B` at `e7d92a7b`.
- `~/eval_full.txt`, `~/eval_output.txt`, `~/eval_v2.txt` belong to an unrelated project (KSTE/Neo4j) and support no talk claim; preserved for completeness.
