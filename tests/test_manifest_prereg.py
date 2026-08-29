"""The run manifest carries the pre-registered prediction-matrix hash as a
required field, so a corpus can be tied to the predictions it tested and a
manifest without it is inadmissible."""
from __future__ import annotations

import pytest

from saster_defense import DefenseConfig, DefenseStack
from saster_defense.manifest import (
    ManifestError,
    grrcon_matrix_sha256,
    validate_manifest,
)

# The committed GrrCON matrix hash (docs/grrcon-test-matrix.md). Pinned so any
# silent edit to the pre-registered predictions fails loudly.
EXPECTED_MATRIX_SHA256 = "60853077e446dd228ff0dae956b2d67925f63329f58d7107534af4fa138571e2"


def test_manifest_includes_matrix_hash():
    m = DefenseStack(config=DefenseConfig(l2=True), fixture_id="t0").manifest()
    assert m["grrcon_matrix_sha256"] == grrcon_matrix_sha256()
    assert len(m["grrcon_matrix_sha256"]) == 64
    validate_manifest(m)  # a complete manifest validates


def test_manifest_without_matrix_hash_is_rejected():
    m = DefenseStack(config=DefenseConfig(l2=True), fixture_id="t0").manifest()
    del m["grrcon_matrix_sha256"]
    with pytest.raises(ManifestError):
        validate_manifest(m)


def test_manifest_with_blank_matrix_hash_is_rejected():
    m = DefenseStack(config=DefenseConfig(l2=True), fixture_id="t0").manifest()
    m["grrcon_matrix_sha256"] = ""
    with pytest.raises(ManifestError):
        validate_manifest(m)


def test_matrix_hash_matches_committed_matrix():
    assert grrcon_matrix_sha256() == EXPECTED_MATRIX_SHA256
