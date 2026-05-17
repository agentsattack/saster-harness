"""saster-harness — wire-level Agentic Detection and Response for the SASTER taxonomy.

Public API:

- :class:`MonitoringConfig` — operator-facing configuration dataclass.
- :class:`MonitoringHarness` — orchestrator. Construct, call :meth:`start`.
- :class:`HarnessMode` — ``OBSERVE``, ``PROBE``, ``INDUCE``.
- :class:`DetectionEvent` — structured event emitted on a pattern firing.
- :class:`TurnData` — captured wire exchange consumed by detectors.
- :class:`SasterDetector` — base class for authoring passive detectors.
- :class:`InductionDetector` — base class for authoring induced detectors
  (active-injection probes against agent sessions).
- :class:`Saster18InducedDetector` — Semantic Recasting via active reframing.
- :class:`Saster24InducedDetector` — JiTOR via mid-conversation term redefinition.
- :class:`Prober`, :class:`InProcessInjector`, :class:`HttpInjector` —
  Prober subsystem for active-injection induction-mode detection.
- :class:`HARAdapter` — Chrome / Firefox HAR file import for offline
  audit of browser-accessible agents.

Adapters live under :mod:`saster_harness.adapters`. The full set of
passive detectors lives under :mod:`saster_harness.detectors`. The
shared sentence-transformer embedder factory lives under
:mod:`saster_harness.embedding`.
"""

from __future__ import annotations

__version__ = "0.1.0"

from .adapters import HARAdapter
from .config import HarnessMode, MonitoringConfig
from .detector import SasterDetector
from .detectors.base_induction import InductionDetector
from .detectors.saster_13_induced import Saster13InducedDetector
from .detectors.saster_15_induced import Saster15InducedDetector
from .detectors.saster_18_induced import Saster18InducedDetector
from .detectors.saster_24_induced import Saster24InducedDetector
from .detectors.saster_26_induced import Saster26InducedDetector
from .event import DetectionEvent, TurnData
from .harness import MonitoringHarness
from .prober import HttpInjector, InjectorBackend, InProcessInjector, Prober, ProbeRecord

__all__ = [
    "DetectionEvent",
    "HARAdapter",
    "HarnessMode",
    "HttpInjector",
    "InProcessInjector",
    "InductionDetector",
    "InjectorBackend",
    "MonitoringConfig",
    "MonitoringHarness",
    "ProbeRecord",
    "Prober",
    "Saster13InducedDetector",
    "Saster15InducedDetector",
    "Saster18InducedDetector",
    "Saster24InducedDetector",
    "Saster26InducedDetector",
    "SasterDetector",
    "TurnData",
    "__version__",
]
