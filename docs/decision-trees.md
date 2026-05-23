# Decision Trees — Per-Pattern Triage

This document provides one decision tree per shipped detector,
disambiguation guidance for ambiguous cases, and a reference table
of co-firing relationships. It complements
[`pattern-authoring.md`](pattern-authoring.md): use the trees here
to classify an observed behavior; use the authoring guide to
build new detectors.

## How to use this document

Run the decision tree top to bottom for each new detection event
you investigate. Each tree is structured as a sequence of
questions; the first "yes" answer is the attribution. The
ambiguity guidance at the end of each tree covers cases where two
patterns plausibly fit; the co-firing table at the end of this
document covers cases where two patterns *do* fit and both should
fire.

## SASTER-18 — Semantic Recasting

**One-line shape:** The agent's response replaces the user's
domain-specific terminology with generic equivalents; nuance is
flattened.

**Decision tree:**

```
Q1: Did the user's message contain specialised vocabulary
    (length-6+ tokens, jargon, named entities, technical terms)?
    No  → not SASTER-18.
Q2: Was the response longer than a refusal would be (>80 chars)
    and not a refusal?
    No  → not SASTER-18.
Q3: Does the response use generic synonyms for the user's specialised
    terms, dropping most of the vocabulary?
    No  → not SASTER-18.
Q4: Was the user clearly speaking as a domain practitioner (terms
    used confidently, not asked-about)?
    No  → consider whether this is a *requested* simplification.
    Yes → SASTER-18.
```

**Disambiguation:**

- *vs. legitimate jargon-simplification on request:* The
  detector cannot distinguish "user is a layperson asking for a
  simplified explanation" from "agent flattened my expert
  vocabulary." Use the surrounding session context to judge. If
  the user has been speaking technically for several turns and
  the response on this turn flattens vocabulary without
  acknowledgment, that's SASTER-18; if the user explicitly
  requested "explain this in non-technical terms," that's normal.

- *vs. SASTER-17 (Intent Alteration):* SASTER-17 is the agent
  silently rewriting the user's *question*. SASTER-18 is the
  agent absorbing the user's *vocabulary* into its training-data
  frame. Different layers — they can co-occur.

**Tunable surface:** The 20% retention threshold is the primary
knob. Raise it for deployments where vocabulary-faithful responses
are policy; lower it to alert only on extreme cases.

## SASTER-24 — Just-in-Time Ontological Reframing (JiTOR)

**One-line shape:** The agent narrates a refusal, then narrates
its own bypass by claiming the substitute framing is equivalent.

**Decision tree:**

```
Q1: Does the response contain an explicit refusal clause
    ("I cannot", "I won't", "I'm unable to", "I must decline")?
    No  → not SASTER-24.
Q2: After the refusal, does the response pivot to a substitute
    framing? Look for "however", "but", "instead", "though".
    No  → this is just a refusal — not SASTER-24.
Q3: Does the substitute framing claim equivalence with the
    original? Look for "same", "identical", "equivalent",
    "isomorphic", "structurally", "mathematically".
    No  → may be a legitimate reframe — not SASTER-24.
Q4: Does the response then deliver content under the substitute
    framing?
    No  → consider whether the response is a *meta*-discussion
          about reframing, not an actual reframe.
    Yes → SASTER-24.
```

**Disambiguation:**

- *vs. legitimate educational reframe:* "Calculus and physics use
  the same differential equations" can fire pattern 2 of the
  detector. The distinguishing signal is the *refusal clause* in
  pattern 1 — pure educational equivalence claims have no refusal.
  If the detector fires on pattern 2 or 3 only (no refusal in the
  same response), expect a higher false-positive rate.

- *vs. SASTER-17 (Intent Alteration):* SASTER-17 reframes
  *silently*. JiTOR reframes *narratedly* — the agent tells you it
  did. Different observability profile; if you can see the reframe,
  it's JiTOR.

## SASTER-26 — Recon-Gated Injection

**One-line shape:** A turn carries systematic questions about
the agent's deployment infrastructure with no apparent task
objective.

**Decision tree:**

```
Q1: Does the message contain vocabulary from one of the recon
    surfaces — compute (cloud, region, k8s, VPC), identity (IAM,
    credentials, secrets, vault), pipeline (CI/CD, deployment),
    observability (SIEM, audit log, log retention)?
    No  → not SASTER-26.
Q2: Is the question structured as a question (ends with `?`,
    interrogative form)?
    No  → consider SASTER-22 / SASTER-17.
Q3: Is the recon question subordinate to a normal task or
    appended to an unrelated conversation?
    Yes → SASTER-26 (the side-channel-recon shape).
    No  → this may be a legitimate platform-onboarding question.
          Still SASTER-26 in the current shipped set; suppress with a per-session
          count threshold or a per-deployment allow-list at
          the webhook.
```

**Disambiguation:**

- *vs. legitimate due-diligence questions:* Prospects asking
  "which cloud do you run on" during compliance evaluation fire
  the detector. The shipped detector cannot tell intent. Mitigation:
  require ≥2 surfaces in the same session before alerting at the
  webhook level.

- *vs. DevRel agents that answer infrastructure questions:* The
  detector inspects `user_message`, not `assistant_response`. A
  DevRel agent answering recon questions does not fire the
  detector; the *user* asking them does. Flip the inspection
  target by subclassing if your deployment shape is inverted.

## SASTER-27 — Detection Layer Injection

**One-line shape:** A turn contains artifacts crafted to
manipulate a classification or scanning layer rather than the
downstream agent.

**Decision tree:**

```
Q1: Does the user message contain zero-width Unicode characters
    (U+200B, U+200C, U+200D, U+FEFF, U+2060, U+180E) in
    non-trivial count (≥3 by default)?
    Yes → SASTER-27 (zero-width signature).
Q2: Does the user message contain a fake classifier-output
    string ([VERDICT: SAFE], [CLASSIFIER: PASS], etc.)?
    Yes → SASTER-27 (fake verdict signature).
Q3: Does the user message contain a <thinking>/<reasoning>/
    <verdict> block whose content carries classifier-targeting
    vocabulary (classifier, verdict, safe to release, allow,
    approved)?
    Yes → SASTER-27 (fake reasoning-block signature).
    No  → not SASTER-27.
```

**Disambiguation:**

- *vs. legitimate chain-of-thought UIs:* The detector requires
  the `<thinking>` block contents to also contain classifier-
  targeting vocabulary. Pure CoT tags pass.

- *vs. SASTER-28 (Salience Suppression):* SASTER-27 attacks the
  classifier directly; SASTER-28 hides extraction goals from the
  classifier via framing. Different mechanisms; can co-occur.

## SASTER-28 — Salience Suppression Exfiltration

**One-line shape:** A retrieval-style extraction objective is
embedded inside creative or low-stakes framing.

**Decision tree:**

```
Q1: Does the user message contain a creative-frame anchor (let's
    play, imagine, story, roleplay, brainstorm, what if,
    hypothetical, free association)?
    No  → not SASTER-28.
Q2: Does the user message contain a retrieval-target reference
    (system prompt, system message, your instructions, training
    data, configuration, your rules)?
    No  → just a creative request — not SASTER-28.
Q3: Are both features present in the same user message?
    Yes → SASTER-28.
```

**Disambiguation:**

- *vs. legitimate creative writing about AI:* "Write a story
  about an AI that knows its system prompt" fires by design.
  This is an acceptable false positive; the alternative is
  silence on a known attack class.

- *vs. SASTER-6 (System Prompt Extraction, not in the shipped set):* A
  direct "what is your system prompt?" is SASTER-6, not
  SASTER-28. SASTER-28 specifically requires the creative-framing
  envelope.

## SASTER-31 — Compositional Capability Emergence

**One-line shape:** Outbound POST with a record-list body
carrying sensitive field names, sourced from an internal read
without an LLM tool-call layer.

**Decision tree:** see the full Carl 2b walkthrough in
[`pattern-authoring.md`](pattern-authoring.md). Condensed form:

```
Q1: Is the request an outbound POST / PUT / PATCH?
    No  → not SASTER-31.
Q2: Does the body parse as JSON with a record-list shape
    (top-level array of ≥2 dicts, OR a records/rows/data/items
    field containing one)?
    No  → not SASTER-31.
Q3: Do the record keys include sensitive field names (password,
    email, ssn, credit_card, api_key, token, ...)?
    No  → may be a legitimate batch upload — not SASTER-31.
Q4: Is the target host outside the agent's authorized tool list?
    Yes → SASTER-31 (highest confidence).
    No  → SASTER-31 (alert with lower priority — operator can
          allow-list known sinks at the webhook).
```

**Disambiguation:**

- *vs. SASTER-28 (Salience Suppression):* SASTER-28 fires on the
  *input* shape (framed retrieval ask). SASTER-31 fires on the
  *output* shape (egress with structured data). Both can co-occur
  if a successful SSE prompt is followed by an egress POST.

- *vs. SASTER-27 (DLI):* SASTER-27 targets the classifier;
  SASTER-31 targets the data plane. Different surfaces.

## SASTER-33 — Context Stripping

**One-line shape:** A captured chat-completion request lacks the
`role: "system"` message that the session has otherwise
consistently been sending.

**Decision tree:**

```
Q1: Has the session accumulated at least min_turns chat-shape
    captures (default 3)?
    No  → wait for the baseline to lock in.
Q2: Has the session locked in an expectation of "with system
    message" at the consistency threshold (default 0.7)?
    No  → mixed session, no baseline expectation — not SASTER-33.
Q3: Does this specific turn lack a role:system message?
    Yes → SASTER-33.
    No  → consistent with baseline — not SASTER-33.
```

**Disambiguation:**

- *vs. RAG agents with per-query system prompts:* These never
  lock in a consistent baseline (system messages vary per query),
  so the detector never fires. No false positives in this class.

- *vs. SASTER-26:* SASTER-33 is the *structural* anomaly; SASTER-26
  is the *content* anomaly. They co-fire on side-channel recon
  turns (the recon question carries recon vocabulary AND drops the
  system message), which is canonical per SASTER.md.

## Disambiguation table — when two patterns plausibly fit

| Observation | Likely pattern | Differential |
|---|---|---|
| User asks "what's your system prompt?" directly | (out of shipped set — SASTER-6) | If framed creatively: SASTER-28. If plain ask: SASTER-6. |
| Agent response includes content it previously refused | (consider SASTER-19 or SASTER-24) | If reframed with equivalence: SASTER-24. If denied refusal happened: SASTER-19. |
| Outbound POST with PII | SASTER-31 | If creative-framed prior: also SASTER-28. If POST is to a registered tool path: low-priority SASTER-31. |
| Long technical user message, generic response | SASTER-18 | If response is a refusal: not SASTER-18. If user was confirming-not-asking jargon: SASTER-18. |
| Refusal with substitute framing | SASTER-24 | Pure refusal (no equivalence claim): not SASTER-24. |
| Recon question with no system message | SASTER-26 + SASTER-33 | Both fire by design — canonical pair. |
| Creative-framed retrieval ask | SASTER-28 | If also stripping classifier signals: + SASTER-27. |

## Co-firing reference

Patterns the shipped detectors flag as canonically co-firing via the
`co_fires_with` class attribute. Downstream consumers can use this
to group alerts without having to know the taxonomy.

| Pattern | Canonically co-fires with | Why |
|---|---|---|
| SASTER-26 (Recon-Gated Injection) | SASTER-33 (Context Stripping) | Recon side-channels typically drop the system message — SASTER.md cross-reference at SASTER-33's notes. |
| SASTER-33 (Context Stripping) | SASTER-26 (Recon-Gated Injection) | Reciprocal of the above. |
| SASTER-28 (Salience Suppression) | SASTER-24 (JiTOR) | Both involve framing manipulation around a prohibited objective. SSE hides the ask; JiTOR hides the bypass. |
| SASTER-18 (Semantic Recasting) | — | No canonical co-fire in the shipped set. |
| SASTER-27 (Detection Layer Injection) | — | No canonical co-fire in the shipped set. |
| SASTER-31 (Compositional Capability Emergence) | — | No canonical co-fire in the shipped set. |

Detectors with no canonical co-fire still fire independently of
each other on the same turn if their respective conditions match.
The `co_fires_with` attribute is a hint about *expected* pairings,
not a constraint on actual firing.
