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

from typing import Any

__version__ = "0.4.0"

from .adapters import HARAdapter
from .baseline import (
    EmbeddingBaseline,
    ObservedToolCallMix,
    SessionBaseline,
    TrainedRefusalBaseline,
)
from .config import HarnessMode, MonitoringConfig
from .detector import SasterDetector
from .detectors.base_induction import (
    InductionDetector,
    MultiTurnInductionDetector,
    ScenarioInductionDetector,
    SingleTurnInductionDetector,
)
from .detectors.saster_11_induced import Saster11InducedDetector
from .detectors.saster_14_induced import Saster14InducedDetector
from .detectors.saster_18_induced import Saster18InducedDetector
from .detectors.saster_18_multiturn import Saster18MultiTurnDetector
from .detectors.saster_24_induced import Saster24InducedDetector
from .detectors.saster_26_induced import Saster26InducedDetector
from .event import DetectionEvent, TurnData
from .harness import (
    MonitoringHarness,
    register_detector,
    register_detector_instance,
    registered_detector_ids,
)
from .prober import HttpInjector, InjectorBackend, InProcessInjector, Prober, ProbeRecord
from .refusal_sampler import CalibrationReceipt, RefusalSampler

__all__ = [
    "CalibrationReceipt",
    "DetectionEvent",
    "EmbeddingBaseline",
    "HARAdapter",
    "HarnessMode",
    "HttpInjector",
    "InProcessInjector",
    "InductionDetector",
    "InjectorBackend",
    "MonitoringConfig",
    "MonitoringHarness",
    "MultiTurnInductionDetector",
    "ObservedToolCallMix",
    "ProbeRecord",
    "Prober",
    "RefusalSampler",
    "Saster11InducedDetector",
    "Saster14InducedDetector",
    "Saster18InducedDetector",
    "Saster18MultiTurnDetector",
    "Saster24InducedDetector",
    "Saster26InducedDetector",
    "SasterDetector",
    "ScenarioInductionDetector",
    "SessionBaseline",
    "SingleTurnInductionDetector",
    "TrainedRefusalBaseline",
    "TurnData",
    "__version__",
    "register_detector",
    "register_detector_instance",
    "registered_detector_ids",
]

# Deprecated class-name aliases (v0.4.0 renumbering). The
# Specification Drift and Gradual Intent Erosion induced detectors
# shipped under the wrong taxonomy numbers (13/15) through v0.3.x; they
# are now Saster11InducedDetector / Saster14InducedDetector. The old
# names remain importable via PEP 562 module ``__getattr__`` with a
# DeprecationWarning; removal target v0.5.0.
_DEPRECATED_CLASS_ALIASES = {
    "Saster13InducedDetector": ("Saster11InducedDetector", Saster11InducedDetector),
    "Saster15InducedDetector": ("Saster14InducedDetector", Saster14InducedDetector),
}


def __getattr__(name: str) -> Any:
    entry = _DEPRECATED_CLASS_ALIASES.get(name)
    if entry is not None:
        import warnings

        new_name, obj = entry
        warnings.warn(
            f"{name} is deprecated and will be removed in v0.5.0; use "
            f"{new_name} instead (SASTER-13/-15-induced were renumbered "
            f"to SASTER-11/-14-induced in v0.4.0).",
            DeprecationWarning,
            stacklevel=2,
        )
        return obj
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
