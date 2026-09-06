# Vendored from AgentDoG — verbatim

These three files are copied **byte-for-byte** from the AgentDoG repository and
are not edited here. They are the observer model's own prompt templates and its
own label taxonomy, and using them verbatim is the whole point: a failure-mode
label is only comparable to AgentDoG's published fine-grained accuracy if the
model is asked the question it was trained and evaluated on, in the format it
was trained and evaluated in. A paraphrased prompt or a re-worded label set
would measure a different thing and could not be read against the published
baseline.

| file | upstream path |
|---|---|
| `trajectory_finegrained.txt` | `prompts/v1.0/trajectory_finegrained.txt` |
| `trajectory_binary.txt` | `prompts/v1.0/trajectory_binary.txt` |
| `taxonomy_finegrained.txt` | `prompts/v1.0/taxonomy_finegrained.txt` |

- **Source:** https://github.com/AI45Lab/AgentDoG
- **Revision:** `c8d803f267a43ec0e103a651265f50f1ff4456d5`
- **License:** Apache 2.0 (per the upstream README)
- **Vendored:** 2026-08-31 (W11)

## Why vendored rather than read from a checkout

The harness must not depend on a checkout outside the repository. The corpus
records `config_hashes`, and a prompt that lives outside the repo cannot be
hashed into a run — so a record could not say which prompt produced its labels.
These files are hashed into the run manifest as
`l4.prompt_sha256` / `l4.taxonomy_sha256`.

## Drift

`carl_ops_trajectory.schema` freezes the three label vocabularies as part of
the record contract. `tests/test_agentdog_taxonomy.py` parses
`taxonomy_finegrained.txt` and asserts the frozen vocabularies match it exactly,
so an upstream taxonomy change cannot silently diverge from the corpus contract.

## v1.5 prompts (vendored 2026-09-05, Stage 2)

| file | upstream path |
|---|---|
| `v1.5/coarse_grained_moderation.txt` | `prompts/v1.5/coarse_grained_moderation.txt` |
| `v1.5/unified_safety_classification.txt` | `prompts/v1.5/unified_safety_classification.txt` |

- **Source:** the same checkout, HEAD `c8d803f267a43ec0e103a651265f50f1ff4456d5`;
  `prompts/v1.5` last changed upstream at `ea174fe942c24b128312502239516777789cfed8` (2026-05-24).
- Byte-for-byte; sha256 verified equal to the checkout at vendoring.
- Why: the AgentDoG 1.5 heads (spark2 :8001 coarse, :8002 FG) answer these
  prompts and not the v1.0 templates — under the v1.0 template both are
  `unavailable` on every call (`docs/sweep-findings.md`, F2 follow-up). The
  coarse prompt answers `<Judgment>safe|unsafe</Judgment>`; the unified
  prompt answers `Safety: safe|unsafe` and, only when unsafe, `Failure
  Mode:` / `Risk Consequence:` / `Risk Source:` from the same label lists
  the v1.0 taxonomy freezes (`Risk Consequence` is the 1.5 name for the
  v1.0 `Real World Harm` dimension).
