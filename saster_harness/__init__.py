"""saster-harness — wire-level Agentic Detection and Response for the SASTER taxonomy.

Public API:

- :class:`MonitoringConfig` — operator-facing configuration dataclass.
- :class:`MonitoringHarness` — orchestrator. Construct, call :meth:`start`.
- :class:`HarnessMode` — ``OBSERVE``, ``PROBE``, ``INDUCE``.
- :class:`DetectionEvent` — structured event emitted on a pattern firing.
- :class:`TurnData` — captured wire exchange consumed by detectors.
- :class:`SasterDetector` — base class for authoring new detectors.

Adapters live under :mod:`saster_harness.adapters`; the v0.1 detector set
lives under :mod:`saster_harness.detectors`.
"""

from __future__ import annotations

__version__ = "0.1.0"

from .config import HarnessMode, MonitoringConfig
from .detector import SasterDetector
from .event import DetectionEvent, TurnData
from .harness import MonitoringHarness

__all__ = [
    "DetectionEvent",
    "HarnessMode",
    "MonitoringConfig",
    "MonitoringHarness",
    "SasterDetector",
    "TurnData",
    "__version__",
]
