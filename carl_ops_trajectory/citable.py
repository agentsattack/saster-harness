"""The citable-corpus gate.

A record enters ``corpora/citable/`` only through :func:`load_citable`,
which enforces what the schema cannot or deliberately does not (the
optional-field amendments keep old records valid; a CITABLE record must
carry the fields):

- the record validates;
- ``markers.units`` is present (Amendment 11);
- a breach detected at latency 0 carries ``detected_at_breach: true``
  (Amendment 12, the latency-zero tripwire);
- ``saster_category`` is satisfiable by the fixture's capability manifest;
- no ENABLED layer in the run manifest is a stand-in (hard constraint 4);
- the marker-population gate: in a breaching campaign, no marker may be
  null across ALL trials unless the record itself declares it unmeasured
  (``onset_status: not_estimated``, ``explanatory_divergence_status:
  not_computed``) — a declared-unmeasured marker is reported, not failed.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from carl_ops_agent.capabilities import CategoryNotSatisfiable, check_category

from .schema import MARKER_NAMES, validate_record


class CitableViolation(ValueError):
    """The record (or corpus) is not citable. Carries the reasons."""

    def __init__(self, reasons: Sequence[str]):
        self.reasons = list(reasons)
        super().__init__("not citable: " + "; ".join(self.reasons))


class MarkerUnpopulated(CitableViolation):
    """A breaching campaign has a marker null on every trial with no status
    declaring it unmeasured."""


#: Which status field, with which value, declares a marker unmeasured.
_DECLARED_UNMEASURED = {
    "onset_dist": ("onset_status", "not_estimated"),
    "explanatory_divergence": ("explanatory_divergence_status", "not_computed"),
}


def _record_id(rec: dict[str, Any]) -> str:
    return f"{rec.get('campaign_id')}/{rec.get('trial_index')}"


def check_record_citable(
    rec: dict[str, Any], manifest: dict[str, Any] | None, fixture_id: str
) -> list[str]:
    """Reasons this record is not citable. Empty means it is."""
    reasons: list[str] = [f"schema: {e}" for e in validate_record(rec)]
    markers = rec.get("markers") if isinstance(rec.get("markers"), dict) else {}
    if "units" not in markers:
        reasons.append("markers.units absent (Amendment 11)")
    cl = rec.get("containment_latency") if isinstance(rec.get("containment_latency"), dict) else {}
    oracle = rec.get("oracle") if isinstance(rec.get("oracle"), dict) else {}
    if oracle.get("breach") is True and cl.get("value") == 0 and cl.get("detected_at_breach") is not True:
        reasons.append(
            "containment_latency.value is 0 on a breach without detected_at_breach: true "
            "(Amendment 12 tripwire)"
        )
    try:
        check_category(fixture_id, str(rec.get("saster_category")))
    except CategoryNotSatisfiable as exc:
        reasons.append(str(exc))
    if manifest is not None:
        enabled = manifest.get("layers_enabled") or {}
        for layer, on in enabled.items():
            block = manifest.get(layer) or {}
            if on and block.get("backend_status") == "stand-in":
                reasons.append(
                    f"layer {layer} is a stand-in ({block.get('stand_in_reason', '')!r}); "
                    f"stand-in-backed records go to corpora/dev/"
                )
    return reasons


def marker_population_gate(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Raise :class:`MarkerUnpopulated` for any breaching campaign with a
    marker null across all its trials and no status declaring it unmeasured.
    Returns a report of the declared-unmeasured markers per campaign."""
    by_campaign: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in records:
        by_campaign[str(r.get("campaign_id"))].append(r)
    report: dict[str, Any] = {"campaigns": {}, "declared_unmeasured": {}}
    failures: list[str] = []
    for cid, recs in sorted(by_campaign.items()):
        breaching = [r for r in recs if (r.get("oracle") or {}).get("breach") is True]
        report["campaigns"][cid] = {"trials": len(recs), "breaching": len(breaching)}
        if not breaching:
            continue
        for name in MARKER_NAMES:
            values = [(r.get("markers") or {}).get(name) for r in breaching]
            if any(v is not None for v in values):
                continue
            status_field, status_value = _DECLARED_UNMEASURED.get(name, (None, None))
            declared = status_field is not None and all(
                (r.get("markers") or {}).get(status_field) == status_value for r in breaching
            )
            if declared:
                report["declared_unmeasured"].setdefault(cid, []).append(name)
            else:
                failures.append(
                    f"campaign {cid}: marker {name} is null on all {len(breaching)} breaching "
                    f"trials and nothing declares it unmeasured"
                )
    if failures:
        raise MarkerUnpopulated(failures)
    return report


def load_citable(
    trajectories: Path | str,
    manifest: Path | str | None,
    fixture_id: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Load a JSONL corpus as citable, or raise :class:`CitableViolation`
    naming every record and reason. Returns ``(records, report)``."""
    man = json.loads(Path(manifest).read_text()) if manifest is not None else None
    records: list[dict[str, Any]] = []
    reasons: list[str] = []
    with open(trajectories, encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            if not line.strip():
                reasons.append(f"line {lineno}: blank line")
                continue
            rec = json.loads(line)
            records.append(rec)
            for why in check_record_citable(rec, man, fixture_id):
                reasons.append(f"{_record_id(rec)}: {why}")
    if reasons:
        raise CitableViolation(reasons)
    report = marker_population_gate(records)
    report["n_records"] = len(records)
    return records, report


__all__ = [
    "CitableViolation",
    "MarkerUnpopulated",
    "check_record_citable",
    "load_citable",
    "marker_population_gate",
]
