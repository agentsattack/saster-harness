# Methodology — Agentic Detection and Response

This document explains the design behind `saster-harness`: what it
monitors, why it sits where it does in your stack, and how it composes
with the controls you already run. It targets the security
practitioner who has not seen the LayerOne talk. Slides and recordings
are linked at the bottom for additional context, but this document
stands alone.

## The problem

Agents — LLM-driven assistants that take actions, call tools, and
move data — fail in ways your existing controls weren't designed to
catch.

Consider three concrete failure modes:

1. **An agent emits side-channel calls to a model that the operator
   never authorised.** The visible conversation looks normal; the
   side-channel asks an upstream LLM for infrastructure intelligence
   ("which cloud, what observability stack, what IAM roles") with the
   ordinary `role: "system"` preamble stripped. None of this is in
   the application logs; the calls go directly out of the agent's
   process to a model endpoint.

2. **An agent composes two individually-safe capabilities into an
   unsafe outcome.** Each capability passes safety review on its own:
   a read-only database tool, a network-egress tool with an
   allow-list. Composed at runtime — read records, format them into
   a payload, POST to a location not on the allow-list because the
   request is constructed dynamically by code, not by an LLM tool
   call — the result is exfiltration. Neither capability would have
   permitted this alone.

3. **An agent narrates a policy bypass before executing it.** "I
   can't help with that directly, but I can help with the
   mathematically equivalent version under a different framing." The
   reframe is the bypass; the next paragraph delivers the prohibited
   content under the substitute framing. Static rules don't catch
   this because the bypass is inference-time and self-described.

Existing controls — WAFs, EDR, SIEMs, DLP — sit at the boundaries of
your environment and at the endpoint. They look at network requests,
file access, process behavior, and audit logs. Agent failure modes
hide *inside* the agent's normal network behavior. The exfil is a
POST that looks like every other POST. The recon is an HTTPS call
that looks like every other HTTPS call. The narrated reframe is text
on the wire. The structural layers see compliance, while the agent
is doing something policy never sanctioned.

Application logs don't help either. The agent decides what to log;
a misbehaving agent decides not to log. Even a well-behaved agent
typically logs *what it intended to do*, not *what happened on the
wire when it did it*. The wire is the ground truth.

## What ADR is

**Agentic Detection and Response (ADR)** is a deployment-time
monitoring discipline: capture every request and response between
an agent and its tools/network, classify each exchange against a
taxonomy of known agentic failure modes, and emit structured
detection events when behavior matches a pattern.

ADR is the deployment-time complement to red-teaming. Red-teaming
proves that an agent *can* fail in a particular way under crafted
input. ADR proves whether the agent *is* failing in production,
where the inputs are real users and the failures are the ones that
actually matter.

The SASTER taxonomy ([github.com/lsuto/saster](https://github.com/lsuto/saster))
is the open catalog of agentic failure modes the harness detects
against. Each shipped detector cites its canonical SASTER definition
in its module docstring; `pattern-authoring.md` walks through how to
add new detectors as the taxonomy evolves.

## Why wire-level — not LLM-level

The harness sits between the agent and everything the agent talks to,
intercepting traffic at the HTTP layer through `mitmproxy`. It does
not run inside the agent's process, does not require modifying the
agent's code, and does not depend on the agent's own logging.

The alternatives are worse:

- **Log-based monitoring** assumes the agent reports honestly. A
  rogue agent decides what's in the log. A confused agent omits the
  side-channel call from its own self-description. Wire capture is
  free of agent self-report bias because it observes what was
  actually sent.

- **In-process instrumentation** is invasive (you change the agent's
  code), version-bound (the instrumentation must track the agent's
  internal API surface), and limited (it sees what the agent's tool
  layer sees, which by definition misses the side-channel calls
  built outside the tool layer — the SASTER-31 / Carl 2b shape).

- **LLM-output inspection** at the model API requires either model
  vendor cooperation or terminating TLS on the model traffic. The
  harness does the latter, by design, but inspects *only the agent
  side* of the conversation. We are not measuring model alignment;
  we are measuring agent behavior against an agentic-failure-mode
  taxonomy.

Wire capture has two trade-offs you should know about up front:

1. **It requires the agent's traffic to be proxiable.** This is the
   normal case for HTTP/HTTPS agents — point them at
   `http://localhost:8888` as their proxy and they go through
   mitmproxy. Agents that pin certificates against a CA outside the
   harness's trust store, or that use non-HTTP transports, need
   adapter work; see `pattern-authoring.md` for the adapter
   interface.

2. **It captures payload bytes**, including the user's messages and
   the model's responses. Treat the harness's event stream with the
   same sensitivity controls you apply to any system that handles
   user data. The webhook payload includes a configurable
   ``raw_request`` / ``raw_response`` excerpt; redact at the sink
   if your compliance posture requires it.

## Session baseline: drift is necessary, not sufficient

Many security tools alert on "anomaly" — input distance from a
trained-on baseline. ADR uses session baseline differently. The
baseline produces a `boundary_proximity` score per turn, but the
score is not in itself a signal: it gates *which detectors run* and
informs evidence, but it does not by itself fire an alert.

Why: raw drift is too noisy. Real users say a wide variety of
things; legitimate technical conversations zigzag across topic
vocabulary. A drift-based alert on its own produces hundreds of false
positives per agent per day.

Combine drift with a pattern-specific detector, and the picture
changes. A turn that scores high drift *and* matches the SASTER-26
infrastructure-recon vocabulary regex is a much rarer event. A turn
that scores high drift *and* drops the role:system message the
session has consistently been sending (SASTER-33) is rarer still.
The harness ships drift and detectors as separate concerns precisely
because the joint distribution is where actionable signal lives.

The session baseline is per-session, not per-deployment. Each
session establishes its own centroid over the first
`baseline_turns` in-band turns (default: 10). This handles the
common case of agents whose acceptable turn-shape varies by tenant,
by tool context, or by deployment vertical — the baseline learns
what "normal" looks like for *this* conversation rather than
imposing a global expectation.

## Composite drift: integrating four signals

The per-turn `boundary_proximity` described above is the most
visible drift signal but not the only one. Operationally the
harness integrates four signals per session into a cumulative
`drift` score, following the boundary-calculation composition from
the LayerOne slide deck:

    drift = 1.0·unauthorized + 0.8·refusal_change + 0.6·behavioral + 0.9·susceptibility

Each signal answers a different question about a session:

- **Unauthorized (DECLARED)** — did this turn talk to a host the
  operator didn't declare as authorized? Pulled from
  `MonitoringConfig.authorized_tools`, matched against
  `turn.target_host` with case-insensitive bidirectional substring.
- **Refusal change (TRAINED)** — under a refusal-eliciting prompt,
  did the response sit far from the agent's empirical refusal
  centroid? Built at boot by sampling the agent against a bundled
  refusal-eliciting corpus.
- **Behavioral (OBSERVED)** — the per-turn `boundary_proximity`
  from the per-session centroid above.
- **Susceptibility (PROBED)** — for any detector that fires, does
  the cached PROBE-cycle susceptibility for that pattern indicate
  the agent was known weak against it?

Three of the signals accumulate per wire turn; the fourth (PROBED)
contributes per detector firing rather than per turn — passive
wire turns carry no firing pattern to attribute a cache lookup to.
The weighted sum is compared to `max_drift_score` (default 25)
after each contribution; the first time a session crosses, the
harness emits a synthetic `SASTER-DRIFT-COMPOSITE` event carrying
the full signal breakdown and the cache provenance.

The four-signal composition does not replace pattern-specific
detectors. It runs alongside them and integrates over time. A
high single-signal score is rarely actionable on its own; a
cumulative drift that crosses threshold over multiple turns
indicates a session whose entire trajectory has drifted from
expected, even if no single detector ever individually fired.

**Probe-elicited events do not feed organic drift.** When the
PROBE-mode scheduler runs an induced detector and that detector
fires, the resulting event is marked `origin="probe"` and is
skipped by the drift accumulator entirely — no score contribution,
no distinct-firings counter, no escalation. The harness provoked
the behavior; the agent didn't do it on its own. This makes the
drift score a structural reflection of organic session shape, not
an amalgam of organic and provoked signal.

## Detector composition

SASTER detectors are independent. Each one runs on every captured
turn, decides whether its pattern fires, and emits a
`DetectionEvent` (or nothing). There is no detector ordering, no
chained logic, no cross-detector mutation of turn state.

This is deliberate. Composition through independence means:

- A new detector ships without auditing or re-tuning the existing
  ones.
- A faulty detector cannot break detection of other patterns.
- Operators can disable any subset of the shipped detectors via
  `MonitoringConfig.detectors` without functional regressions in
  the rest.

Patterns that *canonically* co-occur — for instance SASTER-26
(Recon-Gated Injection) and SASTER-33 (Context Stripping), which
the SASTER.md notes on SASTER-33 explicitly pair during active
reconnaissance — surface that relationship via the
`co_fires_with` class attribute. The harness propagates this
metadata onto every emitted event so a downstream consumer can
correlate without having to know the taxonomy. The correlation is
*advisory* — both detectors decide independently.

## Induced detector shapes

The shipped induced detectors take three orchestration shapes,
formalized in the three abstract base classes in
`saster_harness/detectors/base_induction.py`:

- **Single-turn induction** (`SingleTurnInductionDetector`) — a
  baseline ask plus N reframings, each reframing tried
  independently; the first that produces divergence above
  threshold fires. SASTER-13-induced and SASTER-18-induced.
- **Scenario induction** (`ScenarioInductionDetector`) —
  multi-turn scenarios with custom orchestration; each scenario
  carries its own intermediate turns and target. SASTER-15-induced
  (intent erosion across adjacency-normalizing turns),
  SASTER-24-induced (mid-conversation redefinition),
  SASTER-26-induced (recon-gated injection with structurally-matched
  neutral controls).
- **Multi-turn induction** (`MultiTurnInductionDetector`) — the
  Crescendo shape; each probe attempt is a sequence of turns sent
  under a scoped sub-session, where each step normalizes the
  request one increment further. Only the final-turn response is
  scored, with the full ramp history available for trajectory-
  commitment signals. SASTER-18-multiturn ships as the reference
  implementation.

The three shapes exist because the underlying attack vectors have
different temporal structures. Crescendo-style jailbreaks against
modern safety-tuned models routinely succeed where single-turn
reframings fail because each individual turn looks innocuous to
the safety classifier — the attack is in the cumulative
trajectory. The multi-turn detector is the explicit counter; the
single-turn and scenario shapes catch attacks that don't need the
gradient.

Probe orchestration is one concern; the divergence-scoring math
is separate. A detector's `divergence_score()` is unaware of which
shape it sits inside — single-turn and multi-turn SASTER-18
detectors share the same scoring primitives (refusal-marker drop,
length ratio, refusal-corpus distance) plus a
trajectory-commitment term in the multi-turn case. Operators
tuning thresholds via calibration treat each shape the same way:
the `>0.05` margin rule from `scripts/phase4_calibration.py`
applies across all three.

## Where ADR fits in your security stack

ADR is a complement, not a replacement. Concretely:

| Existing control | What it catches | What ADR catches that it doesn't |
|---|---|---|
| **WAF** (web application firewall) | Inbound attacks on your application surface, traffic-shape anomalies, known-bad payload signatures | Agent-emitted outbound traffic, lateral side-channel calls, behavior on already-allowed paths |
| **EDR** (endpoint detection) | Process behavior, file access, network connections at the endpoint | Semantic-level patterns inside individual network requests, composition of safe capabilities |
| **SIEM** (log correlation) | Cross-source correlation of logged events | Behavior the agent didn't log; wire-truth disagreements with self-report |
| **DLP** (data loss prevention) | Content-keyword matches, file-shape signatures | Compositionally-emergent exfiltration shapes where each piece individually appears benign |
| **API gateway** | Authentication, rate limiting, schema validation | Behavior on authenticated, well-formed requests that nevertheless violates agent policy |

ADR's detection events should land in your existing SIEM via the
`alert_webhook` config; from there they correlate with the rest of
your control output. Treat them as a new event source, not a
parallel response system.

## Design philosophy: deployment-tuned vs. generic detectors

A note on a recurring trade-off you'll encounter when authoring
detectors and tuning thresholds.

Detectors can be tightly tuned against a deployment's specific
traffic — high recall, low false-positive rate, brittle when the
deployment changes. They can also be generic — moderate recall,
documented false positives, robust across deployments. v0.1
deliberately ships the second kind.

The clearest case is SASTER-24 (JiTOR). The original
ProxyGAP regex was tuned against the ASAGAP research corpus, where
most JiTOR exemplars were dual-use physics ("I'll help with the
civilian aerospace version of this problem"). That regex achieved
high recall on its training data and would have shipped here as the
"right answer" — except its anchor vocabulary
(`rocket | aerospace | booster | navigation`) carries the research
corpus's domain bias. Deploying it against general traffic would
miss most JiTOR cases that aren't physics-shaped.

The v0.1 SASTER-24 detector strips those domain anchors and keeps
only the generic reframe shape: refusal clause + pivot conjunction +
equivalence claim. Recall is lower than what the ProxyGAP regex
achieves on its own dataset; recall against general traffic is
better. This is the right trade for a public release.

The same principle drives other choices throughout the v0.1
detectors:

- SASTER-26 reports the matched recon *surface* (compute, identity,
  pipeline, observability) rather than tuning vocabulary against
  any one industry.
- SASTER-27 ships three signatures (zero-width, fake verdict
  strings, fake reasoning blocks) — the ones with documented
  false-positive shapes — and skips the more exotic subtypes
  (delayed activation, constitutional bypass) until practitioner
  feedback indicates the trade-off is worth it.
- SASTER-31 fires on the *intersection* of record-list shape and
  sensitive-field-name presence, so legitimate batch uploads of
  non-sensitive data pass.

The pattern-authoring guide ([pattern-authoring.md](pattern-authoring.md))
walks through the false-positive analysis methodology that produces
these decisions, with the SASTER-18 threshold-tuning narrative as
the worked example.

## Further reading

- LayerOne 2026 talk on Agentic Detection and Response — slides and
  recording at the conference proceedings page.
- [SASTER taxonomy](https://github.com/lsuto/saster) — the open
  catalog of agentic failure modes.
- [`pattern-authoring.md`](pattern-authoring.md) — how to add a new
  detector.
- [`decision-trees.md`](decision-trees.md) — per-pattern decision
  trees and disambiguation guidance.
- [`contribution.md`](contribution.md) — PR workflow, code style,
  Candidate pattern submission process.
