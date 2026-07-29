# Configurable instrumentation

> **Positioning: this is a research instrument, not a production control
> plane.** The instrumentation planes below let a researcher *observe* an
> agent at increasing depth and record what was observed. They do not
> gate, block, or remediate agent actions, and nothing here should be
> deployed as an inline safety control. saster-harness detects and
> records; enforcement is out of scope.

## Observation planes

saster-harness can observe an agent through up to three planes:

| Plane | Observes | Maturity (v0.5.0) |
|---|---|---|
| `tool` | The agent's tool/network calls, via wire MITM. This is the v0.4.0 behaviour. | Shipped |
| `model` | The inference-API traffic — the model's own inputs/outputs, where the reasoning signal lives. Cheap relative to process hooks. | Plane + interface; concrete inference-proxy adapter is downstream |
| `process` | In-agent hooks (callbacks, spans, a sidecar). | Interface + one reference adapter (`CallbackProcessPlaneAdapter`) |

## Profiles

A **profile** is a named, runtime-switchable set of active planes.

| Profile | Planes | Notes |
|---|---|---|
| `standard` (default) | `tool` | **Reproduces v0.4.0 exactly.** |
| `model` | `tool`, `model` | Adds reasoning-level observation |
| `full` | `tool`, `model`, `process` | All planes |

Define your own via `MonitoringConfig.custom_profiles` (name → plane
list); a custom profile shadows a built-in of the same name.

```python
config = MonitoringConfig(
    ...,
    instrumentation_profile="model",           # default "standard"
    custom_profiles={"recon": ["tool", "process"]},
)
```

Switch at runtime with `harness.switch_profile(name, reason)`. The active
profile is `harness.active_profile`.

## `requires_planes` — and why unavailable ≠ clean

Every detector declares the planes it needs:

```python
class MyDetector(SasterDetector):
    requires_planes = (ObservationPlane.MODEL,)   # default is (TOOL,)
```

When a detector's required plane is **not active** under the current
profile, the detector is reported **unavailable** — not **clean**. This
distinction is load-bearing: "clean" means *observed and nothing fired*;
"unavailable" means *not observed at all*. Conflating them would let an
inactive plane masquerade as a clean bill of health.

- `harness.detector_availability()` → `{saster_id: "available" | "unavailable"}`.
- The live addon never runs an unavailable detector (so it cannot return
  a false clean) and records it via `unavailable_detectors(session_id)`.

Because every v0.4.0 detector defaults to `requires_planes=(TOOL,)`, the
`standard` profile leaves all 13 available — no per-detector change.

## Trajectory recording

`harness.instrumentation_snapshot()` returns the instrumentation slice of
a trajectory: the active profile, active planes, every recorded profile
transition (with measured overhead), and per-detector availability. Each
detection event also carries `evidence["active_profile"]`, so a firing
records which planes were live when it was observed.

## Escalation

A genuine (non-shadow, wire-origin) detector firing can automatically
raise the profile for subsequent turns:

```python
config = MonitoringConfig(
    ...,
    escalation_enabled=True,
    escalation_profile="full",   # required when escalation_enabled
)
```

Each escalation is recorded as a transition with a `reason`
(`escalation:<saster_id>`) and the **measured** wall-clock overhead of
activating the newly-added planes. Escalation is off by default;
`standard` with escalation off is exactly v0.4.0.

## Motivation — the CISO post-mortem telemetry checklist

The CSA Hugging Face CISO post-mortem (Knostic / CSA / SANS et al.,
**DRAFT v0.8, 27 Jul 2026, CC BY-NC 4.0**;
<https://cloudsecurityalliance.org/artifacts/hugging-face-ciso-post-mortem>)
argues for a telemetry checklist that spans more than the tool boundary,
and states a preference for **in-agent instrumentation** — observing the
agent's own reasoning and process, not only its outbound calls. That is
the rationale for the `model` and `process` planes: the tool plane alone
cannot see the reasoning-level signal the post-mortem calls for. Cite the
version and date; it is a draft, and it is motivation, not a spec.

The positioning statement at the top still holds: adding planes deepens
*observation*, not *control*.
