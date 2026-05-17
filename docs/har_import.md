# HAR Import — Offline Audit Without MITM

`saster-harness` ships an offline audit path: read a Chrome /
Firefox **HAR** (HTTP Archive) file, run the full SASTER detector
chain against it, emit a structured JSON report. This is for
practitioners who want to validate an agent's behavior after a
session without installing mitmproxy, terminating TLS, or wiring
the harness into live traffic.

The full pipeline runs identically to the live mode — same detectors,
same baselines, same event schema — only the front end changes.

## Quickstart — 60 seconds

1. **Capture a HAR.** Open the browser's DevTools, click the
   **Network** tab, perform the conversation you want audited, then
   right-click any request and choose **Save all as HAR with
   content**. (Chrome and Firefox both support this; the resulting
   file conforms to the [HAR 1.2 spec](http://www.softwareishard.com/blog/har-12-spec/).)

2. **Run the audit:**

   ```bash
   saster-har session.har
   ```

   The CLI streams a JSON report to stdout. Use `-o report.json` to
   write to a file instead.

3. **Read the report.** Each detected pattern lands as a
   `DetectionEvent` in the `events` array. A summary section gives
   you the count by SASTER id at a glance.

## Report shape

```json
{
  "har_path": "session.har",
  "harness_version": "0.1.0",
  "summary": {
    "turns_captured": 23,
    "events_emitted": 4,
    "by_pattern": {
      "SASTER-26": 3,
      "SASTER-31": 1
    }
  },
  "events": [
    {
      "saster_id": "SASTER-26",
      "pattern_name": "Recon-Gated Injection",
      "tier": 4,
      "evidence": {
        "signal": "recon_vocabulary_match",
        "detail": "User-message text contains compute recon vocabulary…",
        "match": "which cloud provider are you running this on?",
        "surface": "compute"
      },
      "session_id": "demo-session-A",
      "turn_idx": 5,
      "co_fires_with": ["SASTER-33"]
    }
  ]
}
```

The shape is stable across patch releases. Consumer scripts can
parse it without version-gating.

## Privacy and consent — read this before recording HARs

HAR files contain **everything** the browser sent and received,
verbatim — including authentication tokens, session cookies, and
the bodies of every HTTPS request. The default redaction pass in
`saster-har` masks the obvious credentials before events reach
detectors, but the **raw HAR file on disk is still sensitive
material**.

Operational rules:

- Treat a captured HAR as you would treat a database export: it
  goes in a controlled location, gets deleted when the audit is
  finished, and never lands in a chat thread or shared drive.
- Only capture HARs from sessions you have authorization to audit.
  HAR capture from someone else's session — even with shared
  access to their browser — is a credential disclosure.
- If you ship a HAR-derived report externally (to a vendor, a
  customer, an analyst outside your security team), inspect the
  `events` array's `raw_request` / `raw_response` excerpts and
  confirm no sensitive content survived the redaction pass.

## What the default redaction strips

Always-on (no opt-out short of `--no-redact`):

- **Sensitive headers** are replaced with `[REDACTED]`:
  `Authorization`, `Proxy-Authorization`, `Cookie`, `Set-Cookie`,
  `X-API-Key`, `X-Auth-Token`, `X-Amz-Security-Token`,
  `X-CSRF-Token`.
- **JSON body fields** with sensitive names get their values
  replaced with `[REDACTED]` (case-insensitive match):
  `password`, `pw`, `pwd`, `passwd`, `token`, `access_token`,
  `refresh_token`, `auth_token`, `bearer_token`, `session_token`,
  `id_token`, `api_key`, `apikey`, `x_api_key`, `secret`,
  `client_secret`, `private_key`, `ssn`, `social_security`,
  `credit_card`, `creditcard`, `card_number`, `cvv`.
- **Pattern-matched values** anywhere in request / response
  bodies — JWTs (`eyJ…` triplets), credit-card numbers (13–19
  digit groups in 4-digit blocks), and US SSNs (NNN-NN-NNNN
  format).

Operator extensions:

- `HARAdapter(extra_redacted_body_keys=["internal_id", "device_fingerprint"])`
  adds field-name patterns specific to your deployment.
- Pass `extra_redacted_headers=["X-Internal-Token"]` for
  deployment-specific header names.

Opting out:

- `HARAdapter(redact=False)` or `saster-har --no-redact` disables
  the entire pass. A console warning fires the first time the
  adapter loads a HAR that contains apparent auth material. Only
  use this on HARs you have already manually scrubbed.

## Session correlation

HAR files don't carry conversation identifiers. The harness needs
some way to group multiple entries into a logical session so
detectors that depend on session baselines (SASTER-33, drift
scoring) work correctly. `saster-har` ships three strategies and
runs them in a fallback chain by default:

| Strategy | When to use | Flag |
|---|---|---|
| **Header** | Your agent injects an explicit session-id header (`X-Session-Id`, `X-Conversation-Id`, custom). | `--session-strategy "header:X-Session-Id"` |
| **Cookie** | Your agent's web UI sets a session cookie that the browser propagates on every request. | `--session-strategy cookie` |
| **Time-window** | No header, no cookie — group by (hostname, time-gap). | `--session-strategy time --time-window 30` |
| **Auto** (default) | Try header → cookie → time-window in order, per entry. | `--session-strategy auto` |

For most browser sessions the cookie strategy is enough. The
header strategy is the best signal when you control the agent and
can inject one. The time-window fallback is a sensible default
when neither is available.

Custom strategies plug in via the `SessionCorrelator` protocol:

```python
from saster_harness.adapters import HARAdapter
from saster_harness.adapters.har_adapter import SessionCorrelator

class TenantSessionCorrelator:
    def correlate(self, entry, turn):
        # Read a path-prefix to derive tenant-scoped session ids.
        path = entry["request"]["url"].split("?", 1)[0]
        if "/tenants/" in path:
            tenant = path.split("/tenants/")[1].split("/")[0]
            return f"tenant-{tenant}"
        return None  # defer to the next correlator

adapter = HARAdapter(session_id_strategy=TenantSessionCorrelator())
```

No subclassing required. The protocol is structural — anything
with a `.correlate(entry, turn) -> str | None` method is
accepted.

## What HAR can — and can't — detect

HAR captures everything that flowed through the browser. It
captures **nothing** that didn't. That distinction matters for
detector coverage.

### What works well

- **SASTER-18** (Semantic Recasting) — operates on the visible
  user message + assistant response, both of which are in the HAR.
- **SASTER-27** (Detection Layer Injection) — inspects user
  message content for evasion artifacts; full coverage.
- **SASTER-28** (Salience Suppression) — inspects user message
  framing; full coverage.
- **SASTER-31** (Compositional Capability Emergence) — inspects
  POST body shape and target host; HAR captures both directly. The
  one place where browser-only capture genuinely helps: data egress
  POSTs from the page to non-canonical endpoints are recorded
  exactly the same way an LLM completion is recorded.

### What under-fires on HAR

- **SASTER-26** (Recon-Gated Injection) — the canonical attack
  shape is a server-side agent emitting recon questions to its
  upstream LLM on a side-channel that bypasses the browser. Those
  side-channel calls are NOT in the HAR. You will catch any recon
  the browser was involved in (e.g. an injected user message
  containing recon vocabulary); you will miss the rogue-agent-emits-
  recon shape entirely.
- **SASTER-33** (Context Stripping) — depends on observing a
  session's normal `role:system` baseline across many turns and
  detecting violations. HARs typically capture one session's
  worth of traffic; the baseline machinery needs that to be
  consistent with the production normal. Mileage varies.

### What HAR doesn't see at all

- Side-channel LLM calls from the agent's own process
- WebSocket frames (HAR records the handshake; the frames are
  empty bodies in the HAR spec)
- DNS, file system, subprocess execution, anything outside the
  browser's HTTP stack

For full coverage, the live mitmproxy mode is the right tool. HAR
is the *audit* path — high-confidence detection of what was
visible from the browser, without the deployment cost of
intercepting TLS.

## CLI reference

```bash
saster-har FILE.har [OPTIONS]
```

| Option | Default | Notes |
|---|---|---|
| `-o, --output FILE` | stdout | Write the report to a file. |
| `-d, --detectors LIST` | all seven passive | Comma-separated SASTER ids: `SASTER-26,SASTER-31` |
| `--session-strategy STR` | `auto` | `auto` / `cookie` / `time` / `header:NAME` |
| `--time-window INT` | 30 | Time-window correlator window in seconds. |
| `--no-redact` | off | Disable the default redaction pass (warning fires). |
| `-v, --verbose` | quiet | `-v` info, `-vv` debug, on stderr. |

## Programmatic use

The CLI is a thin wrapper; everything is also available as a
library:

```python
from pathlib import Path
from saster_harness.adapters import HARAdapter
from saster_harness.detectors import saster_26, saster_31

adapter = HARAdapter(session_id_strategy="cookie", redact=True)
for turn in adapter.read_file(Path("session.har")):
    for detector in (saster_26.DETECTOR, saster_31.DETECTOR):
        event = detector.evaluate(turn)
        if event is not None:
            print(event.to_json(indent=2))
```

The `read_file()` method yields `TurnData` instances — the same
type the live mitmproxy adapter produces — so any pipeline you
build around live capture works against HARs unchanged.
