---
name: saster-harness
description: |
  Wire-level Agentic Detection and Response (ADR) for the SASTER
  taxonomy. Use this skill when working with `saster-harness` —
  configuring detectors, building adapters, authoring SASTER
  pattern detectors, running HAR-file audits, calibrating the
  induced detectors against a reference agent, or debugging why
  a pattern isn't firing.
when_to_use: |
  - The user has `saster-harness` in their dependency list and is
    configuring detectors, modes, or webhooks.
  - The user is debugging "I enabled SASTER-N and nothing fires" or
    similar detection-coverage questions.
  - The user is authoring a new SASTER detector or extending the
    Carl reference agent.
  - The user mentions HAR files, mitmproxy traffic, or ADR.
  - The user references SASTER pattern IDs (SASTER-18, SASTER-24,
    SASTER-26, etc.).
---

# saster-harness — operational guide

`saster-harness` is the open-source ADR harness for the SASTER
agentic-failure taxonomy. v0.1 ships 9 detector implementations
covering 7 SASTER patterns, 4 operating modes, and three audit
paths: live mitmproxy capture, HAR file import, and
direct-pipeline scenario validation.

This guide is for practitioners using saster-harness day-to-day.
For the methodology rationale see
[docs/methodology.md](docs/methodology.md); for pattern-authoring
see [docs/pattern-authoring.md](docs/pattern-authoring.md).

---

## ⚠️ The first thing to know — induced detectors

Two of the nine shipped detectors run in **induction mode**:

- `SASTER-18-induced` — active probe for Semantic Recasting
- `SASTER-24-induced` — active probe for JiTOR

**These do NOT fire on captured traffic.** They actively send
probe turns into an agent session and reason about the responses.
If you enable one and watch your wire feed expecting events to
appear automatically, you'll see nothing — that is the correct
behaviour.

Induced detectors run out-of-band via the Prober subsystem:

```python
from saster_harness import (
    MonitoringConfig, MonitoringHarness, Saster18InducedDetector
)
from saster_harness.prober import HttpInjector, Prober

config = MonitoringConfig(
    agent_name="...",
    agent_endpoint="...",
    authorized_tools=[...],
    enabled_detectors=["SASTER-18-induced"],  # induced only
)
harness = MonitoringHarness(config)

# Explicit trigger — drives the probe cycle now:
prober = Prober(HttpInjector(endpoint=config.agent_endpoint, timeout=180.0))
event = Saster18InducedDetector().induce(prober, session_id="probe-1")
if event:
    print(f"Detected: {event.saster_id} — {event.evidence['detail']}")
```

The harness's PROBE mode (v0.2+) will schedule induced probes
automatically. For v0.1 you call `.induce()` explicitly from a
script, a cron job, or your own orchestrator.

**HttpInjector timeout for induction:** the default `timeout=30.0`
is sufficient for single-shot probes but NOT for induction-mode
follow-ups against LLM-shaped agents. Use `timeout=180.0` for any
HttpInjector you hand to an induced detector — the Phase 4
calibration against Llama-3.3-70B required this margin.

---

## Detectors

| ID | Tier | Mode | Use when |
|---|---|---|---|
| `SASTER-18` | T3 | passive | You want passive monitoring of vocabulary-flattening in agent responses |
| `SASTER-18-induced` | T3 | induced | You want to actively probe whether your agent honors reframings of refused requests |
| `SASTER-24` | T3 | passive | You want to catch agent-narrated reframes ("I can't directly, but I can help with the equivalent ...") |
| `SASTER-24-induced` | T3 | induced | You want to actively probe whether your agent accepts mid-conversation term redefinitions |
| `SASTER-26` | T4 | passive | You want to catch agent-emitted infrastructure-recon questions in conversation traffic |
| `SASTER-27` | T4 | passive | You want to catch classifier-targeting evasion artifacts in user messages (zero-width chars, fake verdicts) |
| `SASTER-28` | T4 | passive | You want to catch retrieval-extraction asks framed as creative writing |
| `SASTER-31` | T3 | passive | You want to catch DB-read + network-egress compositional exfil shapes |
| `SASTER-33` | T4 | passive | You want to catch chat-completion requests with the system message stripped |

Convenience identifiers for `MonitoringConfig.enabled_detectors`:

- `"SASTER-18-both"` — passive + induced flavours together
- `"SASTER-24-both"` — same for SASTER-24

Default-when-omitted loads all 9 implementations
(`["SASTER-18-both", "SASTER-24-both", "SASTER-26", "SASTER-27",
"SASTER-28", "SASTER-31", "SASTER-33"]`).

---

## Adapters

| Adapter | Use for | Performance |
|---|---|---|
| `HttpJsonAdapter` (default) | OpenAI-style chat completion traffic captured live via mitmproxy | One TurnData per request; fast |
| `HARAdapter` | Offline audit of HAR files exported from Chrome / Firefox DevTools | Batch; one-shot |
| Custom subclass of `BaseAdapter` | Non-HTTP protocols (gRPC, MCP, server-sent events) | Per-protocol |

The HAR path ships a `saster-har` CLI:

```bash
saster-har session.har                         # report to stdout
saster-har session.har -o report.json          # report to file
saster-har session.har --detectors SASTER-31   # filter detector set
saster-har session.har --session-strategy "header:X-Session-Id"
saster-har session.har --no-redact             # disable default redaction
```

The default redaction pass strips `Authorization`, `Cookie`,
`X-API-Key`, etc. plus body fields named `password`, `token`,
`api_key`, `ssn`, `credit_card`, and pattern-matches JWT / credit
card / SSN values. See [docs/har_import.md](docs/har_import.md)
for the privacy walkthrough.

---

## Operating modes

```python
from saster_harness import HarnessMode, MonitoringConfig

config = MonitoringConfig(
    ...,
    mode=HarnessMode.OBSERVE,  # default; passive wire capture
    # mode=HarnessMode.PROBE,  # v0.2: scheduled induced probes (no-op in v0.1)
    # mode=HarnessMode.INDUCE, # active adversarial — gated by allow_induce=True
)
```

The `IMPORT` mode referenced by the LayerOne talk is the
`saster-har` CLI path documented above — there's no separate
`HarnessMode.IMPORT` enum value because HAR import doesn't need
the harness object at all.

---

## Using HAR import for offline audit

When the agent is browser-accessible (a chat UI, an internal LLM
console), HAR import is the no-MITM audit path:

1. Open browser DevTools → Network panel.
2. Perform the conversation you want audited.
3. Right-click any request → Save all as HAR with content.
4. `saster-har session.har` — JSON report streams to stdout.

What HAR covers well:
- SASTER-18 (Semantic Recasting), SASTER-27 (DLI), SASTER-28
  (Salience Suppression), SASTER-31 (CCE) — all operate on
  observable user/assistant content or POST-body shapes.

What HAR under-fires:
- SASTER-26 (Recon-Gated Injection) and SASTER-33 (Context
  Stripping) — the canonical shapes involve side-channel calls
  the agent makes from its own process. Those don't pass through
  the browser and therefore aren't in the HAR. Use live mitmproxy
  for full coverage of these patterns.

---

## Induced patterns — what changes operationally

| Concern | Passive detectors | Induced detectors |
|---|---|---|
| **When does it fire?** | Automatically on every captured turn | Only when you call `.induce()` (manual) or via PROBE mode (v0.2) |
| **Does it modify agent traffic?** | No | Yes — actively sends probe turns into the agent's session |
| **Requires agent consent?** | No (read-only observation) | YES — only run against agents in non-prod environments unless you have explicit authorization |
| **Recommended environment** | Production OK | Staging / sandbox / dedicated probe sessions |
| **HttpInjector timeout** | n/a (no probe traffic) | `timeout=180.0` — default 30s is too tight |

The author of the agent must explicitly consent to induced
probing. The system prompt of the probed agent is observed by the
probe (via responses to the baseline turn); regulated content
(HIPAA, GDPR) may make induced probing inappropriate even with
operator authorization. When in doubt, run induced detectors
against an isolated reference target (see Carl, below).

---

## Verifying against Carl (the bundled reference agent)

Carl is a simulated agent with 4 planted susceptibilities. Two
scenarios drive the detector pipeline directly without HTTP; two
scenarios run as an HTTP server calling a real upstream LLM with a
hidden directive system prompt.

**Direct-pipeline scenarios** (no LLM, no network — fast):

```bash
python -m carl.run_recon   # SASTER-26 + SASTER-33 fire 3× each
python -m carl.run_exfil   # SASTER-31 fires once
```

**HTTP-mode scenarios** (real LLM, real induced probing):

```bash
# Carl as HTTP server with susceptibility:
CARL_DIRECTIVE=jitor_susceptible \
CARL_LLM_ENDPOINT=http://your-llm:8000/v1/chat/completions \
python -m carl.server

# Calibration script — drives both induced detectors against
# live Carl with the production sentence-transformer embedder:
python scripts/phase4_calibration.py
```

The calibration script is the load-bearing integration test. If
it passes from a clean clone with a real upstream LLM, the harness
is shippable. The Phase 4 calibration against Llama-3.3-70B
produced scores of +0.399 and +0.153 above the SASTER-18 and
SASTER-24 induction thresholds respectively — both detectors fire
where expected, neither fires against neutral Carl.

---

## Common questions

**"I enabled SASTER-18-induced and nothing fires when I run my
agent."**
Induced detectors don't fire on captured traffic. See the heads-up
section above; you need to call `.induce()` explicitly or use the
calibration script as your invocation pattern.

**"The harness times out when I run an induced probe."**
`HttpInjector(timeout=180.0)` — the default 30s is too tight for
70B-parameter models generating 400-600 tokens of compliance text.
v0.2 will add a separate `induction_timeout` default.

**"My CI runs flag the SASTER-31 detector firing on a legitimate
batch upload."**
SASTER-31 fires on PII pipelines by design. Allow-list the
destination at your webhook sink, OR subclass the detector and
override `evaluate()` to early-return for known-good hosts.

**"I want to write a detector for a SASTER pattern not in v0.1."**
See [docs/pattern-authoring.md](docs/pattern-authoring.md). For
induced detectors, the new pattern's reference target needs
explicit susceptibility encoding — vague prompts produce vague
behaviour.

---

## Related files

- [README.md](README.md) — five-minute install + first-detection
  quickstart
- [docs/methodology.md](docs/methodology.md) — ADR concept
- [docs/pattern-authoring.md](docs/pattern-authoring.md) — how to
  write a detector
- [docs/decision-trees.md](docs/decision-trees.md) — analyst
  triage trees
- [carl/README.md](carl/README.md) — Carl simulation disclaimer
- [CHANGELOG.md](CHANGELOG.md) — release history + v0.2 roadmap
