# Public-repo checklist — before the corpus is public on 2026-09-22

Written 2026-09-06 from `git grep` over the tracked tree at the wrap commit.
A list, not an action: nothing below has been changed.

## Must be scrubbed or rewritten

| what | where | count | note |
|---|---|---|---|
| Node addresses (`192.168.1.x`, `fd00:200::N`) | run manifests (`l4_heads.*.endpoint`, victim endpoints), console logs, monitor logs, `docs/cluster-bringup.md` | 592 tracked files, 570 under `runs/` | The manifests are content-addressed evidence: rewrite by a script that replaces addresses with role names (`victimA`, `head-1.0-binary`) and records the rewrite in the evidence manifest — never edit in place under `~/evidence`. |
| Console logs carrying addresses | `runs/*.console.log`, `runs/*/cells/*.console.log` | 0 of 218 tracked logs | Same treatment, or drop the per-cell console logs from the public tree and keep them in the evidence stores. |
| Absolute home paths | `storage.primary` in every manifest (`/home/lbsuto/evidence/…`), `sys.path.insert("/home/lbsuto/halctf-agent")` in 8 scripts, 2 docs | 440 tracked files (217 reference `~/evidence` by absolute path) | Manifests: the same rewrite pass. Scripts: replace the hard-coded sibling path with an env var (`SASTER_HALCTF_PATH`). |
| SSH host names and key names | `docs/cluster-bringup.md` (`spark1-saster-push`, cloned host-key note), `scripts/analyze_pilot_w23.py` (`ssh spark3 docker …`), `scripts/run_sweep_w24.py` (`W24_MIRROR_HOST=spark8`) | 3 files | Doc: keep the procedure, drop the key name and the host-key fingerprints. Scripts: already env-overridable; make the defaults neutral. |
| Evidence mirror roots | `~/evidence/MANIFEST.json` (`spark1:~/evidence`, `spark8:~/evidence`), every manifest's `storage.mirror` | all | Publish the top-level hash and the per-store hashes; the roots are an internal detail. |

## Must NOT be pushed

| what | state today |
|---|---|
| `login.txt` (a password-like string at the repo root) | untracked and in `.gitignore` (line 60); never used or printed. Confirm it is absent from every branch and from the evidence stores before publishing. |
| Hugging Face credentials | no token or token path is tracked; `docs/cluster-bringup.md` line 258 shows an unauthenticated `snapshot_download`; 5 tracked files mention Hugging Face at all. The gated-weights refusal (LlamaGuard/ShieldGemma, 403) is a licence fact and can stay. |
| The content stores' raw prompts and completions (`runs/*/cells/*/blobs/`) | tracked. They contain the brief, the ticket text and every model reply — nothing secret, but review the brief for anything the fixture author does not want public. |

## Must be pushed or stated

- The three pins (matrix `60853077…`, envelope `25937a1f…`, addendum `9657077b…`), the policy in force `46e61210…`, the arm file `296bf240…`, and the evidence top-level hash `2e77e1934444d3720f5455c1d34cc9ec5a303a86cc2cb0819e71e1e5656be596`.
- `docs/sweep-report.md`, `docs/defect-log.md`, `docs/schema-amendments.md`, `docs/sweep-findings.md`, the addendum with its hash history, `runs/CORPUS_README.md` and the per-root READMEs.
- The demo package under `runs/w25_stage5/demo/` with its replay scripts — after the address rewrite, the replay scripts need the router address as an env var, not a literal.
- A statement that `~/evidence` is not in the repository: the repository carries the run trees; the evidence stores are the content-addressed copies whose hashes the manifests cite.

## Not a secret, but decide

- `docs/cluster-bringup.md` documents the Ray trade, the cgroup/NVML fault and the cloned host keys: operational detail about a private cluster. Keep the procedure, drop the fingerprints.
- The 1.5 heads' raw replies in `diagnoses.jsonl` include the models' reasoning text: fine to publish, large.
