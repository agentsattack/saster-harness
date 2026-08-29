"""carl-ops agent — the IT-operations victim deployment on the VictimAgent
base. Wires the 13-tool surface and world-state store of
:mod:`carl_ops_state` onto :mod:`saster_harness.victim_agent`.

Two modes share one implementation (:class:`CarlOpsMode`); obstruction is an
environment declaration, not a mode. See :mod:`carl_ops_agent.agent`.
"""

from __future__ import annotations

from .agent import (
    HIDDEN_DIRECTIVE,
    CarlOps,
    CarlOpsMode,
    build_environment,
)
from .widening import (
    WideningRouteMismatch,
    derive_widening_route,
    resolve_widening_route,
)

__all__ = [
    "CarlOps",
    "CarlOpsMode",
    "HIDDEN_DIRECTIVE",
    "build_environment",
    "derive_widening_route",
    "resolve_widening_route",
    "WideningRouteMismatch",
]
