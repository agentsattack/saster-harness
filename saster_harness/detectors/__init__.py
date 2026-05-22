"""SASTER pattern detectors shipped in saster-harness.

Each detector lives in its own module so practitioners can subclass,
disable, or replace patterns individually. The v0.1 set:

Passive detectors (run on captured :class:`TurnData`):

- :mod:`.saster_18` — Semantic Recasting (T3, Epistemic)
- :mod:`.saster_24` — Just-in-Time Ontological Reframing (T3, Epistemic)
- :mod:`.saster_26` — Recon-Gated Injection (T4, Infrastructure & Recon)
- :mod:`.saster_27` — Detection Layer Injection (T4, Infrastructure & Recon)
- :mod:`.saster_28` — Salience Suppression Exfiltration (T4, Infrastructure & Recon)
- :mod:`.saster_31` — Compositional Capability Emergence (T3, Epistemic)
- :mod:`.saster_33` — Context Stripping (T4, Infrastructure & Recon)

Induced detectors (actively probe agent sessions via :class:`~saster_harness.prober.Prober`):

- :mod:`.saster_13_induced` — Spec Drift via adjacency-framed out-of-scope asks.
- :mod:`.saster_15_induced` — Intent Erosion via multi-turn adjacency normalization.
- :mod:`.saster_18_induced` — Semantic Recasting via single-turn reframings.
- :mod:`.saster_18_multiturn` — Semantic Recasting via Crescendo-style multi-turn ramps (v0.3.2).
- :mod:`.saster_24_induced` — JiTOR via mid-conversation term redefinition.
- :mod:`.saster_26_induced` — Recon-Gated Injection via double-probe scenarios.

Authoring guide: :mod:`.base_induction` for the induction base classes
(:class:`SingleTurnInductionDetector`, :class:`MultiTurnInductionDetector`,
:class:`ScenarioInductionDetector`); ``docs/pattern-authoring.md`` for the
methodology walkthrough.
"""
