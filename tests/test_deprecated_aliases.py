"""Deprecated-identifier aliases for the v0.4.0 SASTER-13/-15 renumbering.

The Specification Drift and Gradual Intent Erosion induced detectors
shipped through v0.3.x under the wrong taxonomy numbers
(``SASTER-13-induced`` / ``SASTER-15-induced``). v0.4.0 renumbered them
to ``SASTER-11-induced`` / ``SASTER-14-induced`` and kept the old
identifiers as deprecated aliases so existing ``enabled_detectors``
configs keep working with a warning rather than breaking.
"""

from __future__ import annotations

import warnings

import pytest

from saster_harness.harness import _load_default_detectors


def test_old_induced_id_resolves_and_warns():
    with pytest.warns(DeprecationWarning, match="SASTER-13-induced"):
        dets = _load_default_detectors(["SASTER-13-induced"])
    assert [d.saster_id for d in dets] == ["SASTER-11-induced"]


def test_old_15_induced_id_resolves_and_warns():
    with pytest.warns(DeprecationWarning, match="SASTER-15-induced"):
        dets = _load_default_detectors(["SASTER-15-induced"])
    assert [d.saster_id for d in dets] == ["SASTER-14-induced"]


def test_old_both_shortcuts_resolve_to_induced_and_warn():
    # The v0.3.x "-both" shortcuts expanded to the induced module alone
    # (no passive SASTER-11/-14 ships). They alias to the induced id.
    with pytest.warns(DeprecationWarning, match="SASTER-13-both"):
        dets = _load_default_detectors(["SASTER-13-both"])
    assert [d.saster_id for d in dets] == ["SASTER-11-induced"]
    with pytest.warns(DeprecationWarning, match="SASTER-15-both"):
        dets = _load_default_detectors(["SASTER-15-both"])
    assert [d.saster_id for d in dets] == ["SASTER-14-induced"]


def test_current_ids_do_not_emit_renumber_warning():
    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        dets = _load_default_detectors(["SASTER-11-induced", "SASTER-14-induced"])
    assert {d.saster_id for d in dets} == {"SASTER-11-induced", "SASTER-14-induced"}
    assert not [
        w for w in recorded if "removed in v0.5.0" in str(w.message)
    ]


def test_deprecated_class_names_resolve_and_warn():
    import saster_harness
    from saster_harness import Saster11InducedDetector, Saster14InducedDetector

    with pytest.warns(DeprecationWarning, match="Saster13InducedDetector"):
        old_13 = saster_harness.Saster13InducedDetector
    assert old_13 is Saster11InducedDetector

    with pytest.warns(DeprecationWarning, match="Saster15InducedDetector"):
        old_15 = saster_harness.Saster15InducedDetector
    assert old_15 is Saster14InducedDetector
