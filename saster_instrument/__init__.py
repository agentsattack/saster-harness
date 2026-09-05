"""Instrument registry — the surface the instrument tests are parametrized over.

Stage 1 of the GrrCON sweep prompt: tests that would have caught the defect
catalogue are parametrized over a REGISTRY rather than hand-listed, and a
meta-test (``tests/test_instrument_registry.py``) asserts every registered
wrapper, metric and marker has coverage. A new component without a
degenerate-input test therefore fails CI instead of shipping untested.

Three registries, per ``docs/instrument-test-plan.md``:

- :data:`WRAPPERS` — every classifier / parser / detector wrapper (the five
  defense layers, the OPA and z3 clients, the refusal/turn classifier).
- :data:`METRICS` — every scalar metric a record or a report carries.
- :data:`MARKERS` — the five trajectory markers, each with its index unit.

Plus two the plan's riders need: :data:`DEFENSE_CONFIGS` (the ablation cells
the stack-level negative control must pass under) and :data:`VICTIM_FAMILIES`
(the chat-template families the round-trip test runs over).
"""

from __future__ import annotations

from .registry import (
    DEFENSE_CONFIGS,
    DEGENERATE_ROWS,
    MARKERS,
    METRICS,
    VICTIM_FAMILIES,
    WRAPPERS,
    DefenseConfigSpec,
    MarkerSpec,
    MetricSpec,
    VictimFamily,
    WrapperSpec,
)

__all__ = [
    "DEFENSE_CONFIGS",
    "DEGENERATE_ROWS",
    "MARKERS",
    "METRICS",
    "VICTIM_FAMILIES",
    "WRAPPERS",
    "DefenseConfigSpec",
    "MarkerSpec",
    "MetricSpec",
    "VictimFamily",
    "WrapperSpec",
]
