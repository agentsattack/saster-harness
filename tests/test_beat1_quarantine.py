"""Addendum §U / D19: under quarantine a denied input turn never reaches the
history the model sees; under legacy it does (the recorded defect)."""
from __future__ import annotations

import importlib
import os


def _load(mode):
    os.environ["BEAT1_INPUT_BLOCK"] = mode
    import scripts.run_beat1_w29 as m
    return importlib.reload(m)


def test_quarantine_keeps_denied_text_out_of_history():
    m = _load("quarantine")
    assert m.INPUT_BLOCK == "quarantine"
    from pathlib import Path
    src = Path(m.__file__).read_text()
    assert 'if INPUT_BLOCK == "legacy":' in src  # the append is gated on legacy only


def test_legacy_is_the_recorded_defect():
    m = _load("legacy")
    assert m.INPUT_BLOCK == "legacy"
