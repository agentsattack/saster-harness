# Contributing to saster-harness

`saster-harness` ships as a research tool for the security community.
Contributions — detectors for new SASTER patterns, adapters for
non-HTTP transports, false-positive reductions on shipped detectors,
documentation improvements — are welcome.

This document covers the PR workflow, code quality standards, and
the process for proposing new SASTER patterns.

## PR workflow

1. **Open an issue first** for non-trivial changes. Detector tuning
   changes (FP/FN trade-offs) and new detectors benefit from
   discussion before code. Typos and small doc fixes can skip to
   step 3.

2. **Fork and branch.** Branch naming convention:
   `detector/saster-XX` for a new detector, `fix/saster-XX-fp-FOO`
   for a false-positive fix, `docs/TOPIC` for documentation,
   `adapter/PROTOCOL` for a new adapter.

3. **Write the code + tests + docs in the same PR.** v0.1 standards:
   a detector PR that doesn't update the docstring or doesn't add
   tests won't merge, even if the code itself is good. The
   docstring + tests are how a future maintainer understands what
   you intended.

4. **Run the quality gates locally** before pushing:

   ```bash
   ruff check saster_harness tests carl examples
   mypy saster_harness
   pytest -q
   ```

   All three must pass. The CI runs the same gates on every
   push — a green local run is the contract.

5. **Open the PR.** Use the template (below). Link the issue from
   step 1 if applicable.

6. **Review.** Maintainers review for: pattern attribution
   accuracy (does the SASTER citation match what the code does?),
   false-positive surface (are the documented FP cases honest?),
   test coverage (positive + negative + edge), and code style
   consistency with the shipped detectors.

7. **Squash-merge** once approved. The PR title becomes the commit
   message in the squash; write it clearly.

## Code style

The shipped detectors are the style template. The repo uses:

- **ruff** for linting. Configuration in `pyproject.toml` selects
  E/F/W/I/UP/B/SIM rule families. Line length 100. Run
  `ruff check` and `ruff check --fix` before submitting.

- **mypy** in strict mode. All type annotations required;
  `# type: ignore` allowed only with a specific error code
  (`# type: ignore[attr-defined]`, never bare).

- **No external code formatters required.** ruff handles
  formatting concerns within its lint scope; the maintainers
  don't impose black/isort beyond what ruff covers.

- **Imports:** `from __future__ import annotations` at the top of
  every module. Standard library first, third-party next,
  saster-harness internal last. Import groups separated by blank
  lines. Ruff's `I` rule family enforces this automatically.

- **Type hints:** Use modern syntax — `list[str]` over
  `List[str]`, `str | None` over `Optional[str]`. The
  `__future__` import makes this work on Python 3.10+.

- **Docstrings:** Triple-quoted, NumPy-ish style for parameter
  documentation. Module-level docstrings on every detector and
  every public module. Function docstrings for public functions;
  optional but encouraged for private functions whose behavior
  isn't obvious.

- **No comments that just restate the code.** Comments should
  explain *why*, not *what*. The exceptions are the canonical
  SASTER definition quotes in detector module docstrings (which
  are *required*) and section dividers in long modules.

## Test requirements

Every new detector must ship with:

1. **At least one positive case** firing on a canonical attack
   input. The input should be quoted from or close to the
   SASTER.md example for the pattern.

2. **At least one negative case** *not* firing on a legitimate-
   traffic input that resembles the attack shape. This encodes
   the false-positive surface you've claimed in the docstring.

3. **No new failure of the empty-turn safety check.** The
   cross-cutting parametrised test in `tests/test_detectors.py`
   runs every shipped detector against an empty `TurnData()` and
   expects `None`. New detectors are automatically included via
   the parametrised list — add yours to the list.

When you tune a threshold or adjust a signature, add an at-the-
edge legitimate case as a negative test. This encodes the rationale
for the tuning in code, so future changes can't silently regress
it. See the SASTER-18 ClickHouse-jargon test case for the worked
example.

For adapter changes, add tests against the protocol shape you're
extracting. The reference is `HttpJsonAdapter` — extract user
messages, response content, session identifier, and structural
flags (`has_system_message`), and verify each is populated
correctly from a representative request/response pair.

## PR template

```markdown
## Summary

(One-paragraph description of what this PR does.)

## What changed

- (Bullet list of concrete changes.)

## SASTER pattern

(If this PR ships a new detector or modifies an existing one,
cite the canonical SASTER.md definition. Link the SASTER repo.)

## False-positive analysis

(For detector changes: what legitimate-traffic shapes will fire
this detector? What's the documented mitigation?)

## Tests

- (List the new test cases added.)
- ruff: clean / mypy: clean / pytest: N tests, all passing.

## Open questions

(Anything you'd like the reviewer's input on. Tuning thresholds,
naming, scope. Empty if none.)
```

## Proposing a new SASTER pattern

If you observe an agent failure mode that no catalogued SASTER
pattern covers, the harness is the wrong place to propose the
taxonomy expansion. SASTER lives at
[github.com/lsuto/saster](https://github.com/lsuto/saster); patterns
are catalogued there, in the canonical taxonomy.

The SASTER repo distinguishes **Candidate** patterns (proposed,
under refinement) from **Canonical** patterns (immutable
identifier, complete writeup). The process:

1. **Open a Candidate proposal** as an issue against the SASTER
   repo. Include:
   - Attack writeup (what the agent does)
   - Detection writeup (how a defender catches it)
   - Example (a concrete instance, ideally from observed traffic)
   - Relationship to existing patterns (is this a sibling, a
     subtype, or genuinely new?)

2. **Discussion / refinement.** Reviewers may push back on scope
   (does this collapse into an existing pattern?), on naming, on
   the detection writeup. Iterate.

3. **Acceptance.** Accepted Candidates get assigned the next
   available SASTER number. Numbers are immutable; rejected
   Candidates release the number back to the pool.

4. **Detector contribution.** Once the pattern is Canonical,
   propose a harness detector against it via the normal PR
   workflow above.

Authoring a Candidate is not a prerequisite for contributing a
detector against an existing Canonical pattern. The two paths are
independent — patches against under-represented catalogued
patterns are particularly welcome.

## Attribution

- **Detectors against existing SASTER patterns:** the detector
  module docstring credits the SASTER pattern (number + name).
  The PR author is credited in the commit history; no in-source
  attribution required.

- **Candidate pattern proposals:** the SASTER repo's
  CONTRIBUTING.md governs attribution for taxonomy submissions.
  The harness does not duplicate that attribution; the canonical
  reference is the SASTER pattern's `Prior art:` section in
  SASTER.md.

- **Adapters:** module docstring credits the adapter's author
  + the protocol the adapter targets. Adapters for proprietary
  protocols (vendor MCP variants, internal tool schemas) are
  welcome as third-party packages; the harness's adapter
  interface is stable across patch releases.

- **AI-assisted contributions:** AI tooling is welcome. If an
  LLM helped write substantial code, note it in the PR
  description so reviewers can apply appropriate scrutiny. The
  shipped code must still meet the quality standards regardless
  of authorship aid; reviewers will not relax the bar for
  AI-assisted contributions.

## License

By contributing you agree your contributions are licensed under
the [MIT License](../LICENSE), the same license as the rest of
the project.

## Maintainer contact

Larry Suto — `larry@stratdatsec.com`. Use GitHub issues for the
default-public discussion; use email for security-disclosure
issues or anything you'd rather not raise in public.
