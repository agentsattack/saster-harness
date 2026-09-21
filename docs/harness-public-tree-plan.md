# The harness as a new public tree: what has to be done (written 2026-09-21, after the talk push)

Status on the day this was written: the whole harness, run trees included, is public on
`agentsattack/saster-harness` (`feat/defense-stack` and `main` at `30f8ee45`). The scrub that
`docs/public-repo-checklist.md` called for on 2026-09-06 was never applied to the harness tree; the
evidence corpus (`agentsattack/saster-evidence`) was built scrubbed by `scripts/build_public_evidence.py`
and is the pattern to copy. This document is the plan for doing the same to the harness, after the
talk, as a new tree. It is a list of work, not a record of work done.

## Why a new tree and not an in-place edit

- The run trees under `runs/` are the evidence the numbers cite. Every cell manifest carries the
  pre-registration pins (`grrcon_matrix_sha256`, `envelope_preregistration_sha256`,
  `grrcon_addendum_sha256`, `route_hint_sha256`, `config_hashes`) and its `storage.primary` and
  `storage.mirror` roots. Rewriting a manifest changes its bytes; the private evidence stores and the
  sweep report cite the unrewritten bytes. So the rewrite has to be a copy that records both hashes,
  never an edit of the tracked file.
- Git keeps history. A scrub commit on the existing repository leaves every address in every earlier
  commit. Removing them means rewriting history and force-pushing, and every clone made before that
  keeps the old objects. A new repository with one initial commit has no such history.
- The rule the harness already lives by: artifacts immutable, new outputs to new paths, re-runs are
  new run ids. A scrubbed harness is a new output.

## What is in the tracked tree today (measured at `30f8ee45`)

| what | files | where it lives |
|---|---|---|
| IPv4 LAN addresses (`192.168.1.x`) | 788 | manifest `router`, `endpoint` fields (victim router, classifier heads), console logs, monitor logs, a few docs and scripts |
| IPv6 fabric addresses (`fd00:200::N`) | 1108 | the same manifest fields, cluster docs |
| the operator's home path (`/home/lbsuto`) | 601 | `storage.primary` in every manifest, `sys.path.insert` in 13 scripts, docs |
| host names (`spark1` … `spark10`) | 347 | `storage.mirror`, scripts' defaults (`W24_MIRROR_HOST`), cluster docs, session logs |
| SSH key name and host-key notes | 3 | `docs/cluster-bringup.md`, one analysis script, one sweep script |
| the credentials file | 0 | `login.txt` is untracked, ignored, absent from every ref (checked 2026-09-21) |

None of these is a credential. They are private-range addresses, a login name that is also the git
author, and public-key fingerprints. The reason to scrub is posture, not exposure.

## The plan, in order

1. **Write `scripts/build_public_harness.py <staging_dir>`** on the model of
   `scripts/build_public_evidence.py`. It refuses to overwrite, copies the tracked tree of one named
   commit (`git archive`, never the working tree) into the staging directory, and rewrites text files
   with the same rule table the corpus used, so the two public repositories agree on every
   pseudonym: `fd00:200::N` -> `node-N`, `192.168.1.N` -> `lan-node-N`, `sparkN` -> `nodeN`,
   `/home/lbsuto` -> `/home/user`, `lbsuto` -> `user`, `spark1-saster-push` -> `push-key`. Add the
   rules the corpus did not need: `spark8:~/evidence` mirror roots -> `mirror:~/evidence`;
   `W24_MIRROR_HOST` and any other host default -> a neutral placeholder. Binary files (media, pptx,
   pdf, png) copy byte for byte.
2. **Log every rewrite.** `SCRUB_LOG.json` at the root of the new tree: for each rewritten file its
   path, private sha256 and public sha256, plus the rule list. `MANIFEST.json`: the source commit
   (`30f8ee45` or later), the private tree hash (`git rev-parse HEAD^{tree}`), the count of files
   rewritten, and a sha256 over the sorted list of public file hashes so the tree is citable as one
   number, the way the corpus has `top_level_sha256`.
3. **Keep the run manifests' own pins untouched.** The rewrite changes `storage.*`, `router` and
   `endpoint` strings only. The pre-registration hashes inside a manifest are hashes of documents, not
   of the manifest, so they stay valid after the rewrite; state that in the README so a reader does not
   try to re-derive them from the public manifest bytes.
4. **Replace the hard-coded sibling path.** Thirteen scripts do `sys.path.insert(0, "/home/lbsuto/halctf-agent")`.
   Change them, in the private tree first, to read `SASTER_HALCTF_PATH` with the old value as the
   default, so the public copy is runnable with one environment variable. Same for `W24_MIRROR_HOST`,
   `W24_MIRROR_PATH`, `ROUTER_URL` and the classifier endpoints in the W38 and W30 runners: every one
   already reads an environment variable or can. Commit that change here before building, so the
   public scripts are not patched copies.
5. **Withhold, and list by hash**, the same set the corpus withheld: `docs/cluster-bringup.md` (keep
   the procedure in a rewritten copy, drop the host-key fingerprints and the key name), the cluster
   audit and session transcripts, and any third-party dataset copy (ATBench) that may sit under
   `runs/`. `MANIFEST.json` lists each with its private hash and a one-line reason.
6. **Regenerate the pin tests' expectations only if a pinned doc was rewritten.** The tests in
   `tests/test_manifest_prereg.py` and `tests/test_manifest_addendum.py` pin
   `docs/grrcon-test-matrix.md`, `docs/grrcon-test-matrix-addendum.md`, `docs/envelope-preregistration.md`
   and `docs/schema-amendments.md`. Checked 2026-09-21: the matrix and the envelope pre-registration
   contain no private name; the addendum has 13 lines with one and `schema-amendments.md` has 7. Those
   two cannot be rewritten (the pin is the point): the builder copies them byte-identical, the rule
   table skips them by path, and the README names them as the two files where a node address or a
   host name survives and why. The pins and the suite then pass in the new tree unchanged.
7. **Run the suite in the staging tree** with a clean virtualenv built from `pyproject.toml`, from
   a directory that is not the private checkout, with `SASTER_HALCTF_PATH` unset, so the run shows what
   a stranger gets. Expected: the same 1554 passed, 11 skipped, 4 xfailed. Any test that needs the
   private cluster (a live router, a served classifier head) must already be skipping on its own;
   if one fails instead, that is a defect in the test, fixed in the private tree first.
8. **Write the README of the new tree** with: what the harness is, the link to the evidence corpus
   and its top-level hash, the scrub rules and the rewrite count, the withheld list, the two
   environment variables a reader has to set, the exact commands to replay one cited record, and the
   statement that the private evidence stores are not in this repository and that the run trees
   here are the same records the corpus holds, byte-identical except for the logged rewrites.
9. **Publish as a new repository** with one initial commit, authored Larry Suto, no trailer
   (`git init`, `git add -A`, one commit), with a new write-scoped deploy key, the same way
   `saster-evidence` was done on 2026-09-21. Keep `agentsattack/saster-harness` as it is, or archive
   it with a README pointing at the new tree; do not rewrite its history.
10. **Cross-link.** Update the corpus README and slide 56's successor to point at the new tree and
    its manifest hash. Add a line to `docs/sweep-findings.md` only if the build turns up something that
    changes a number; a pure rename does not.

## What must not happen

- No edit under `~/evidence`, and no edit of a tracked run manifest in place.
- No rewrite of `docs/grrcon-test-matrix.md`, the addendum, the envelope pre-registration or
  `docs/schema-amendments.md` (hash-pinned; step 6).
- No oracle code or invariant definition changes ride along with the scrub.
- The credentials file is never read, copied or named in the public tree; the checklist's phrase for
  it is "an untracked credentials file".
- No Claude attribution in the public commit.

## Effort

The builder is about 120 lines by analogy with the corpus one. The tree is about 3,400 tracked files;
the corpus build of 12,809 files ran in under a minute. Steps 4 and 7 are the real work: a private
commit that makes the scripts environment-driven, and a suite run in a clean environment that will
surface any test still leaning on the cluster.
