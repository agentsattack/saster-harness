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
