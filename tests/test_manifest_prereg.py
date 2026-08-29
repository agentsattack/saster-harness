"""The run manifest carries both pre-registration hashes as required fields —
the prediction matrix and the envelope-mass pre-registration — so a corpus can
be tied to the predictions it tested and to the scoring method and thresholds
it was measured under. A manifest without either is inadmissible."""
from __future__ import annotations

import pytest

from saster_defense import DefenseConfig, DefenseStack
from saster_defense.manifest import (
    ManifestError,
    envelope_preregistration_sha256,
    grrcon_matrix_sha256,
    validate_manifest,
)

# The committed GrrCON matrix hash (docs/grrcon-test-matrix.md). Pinned so any
# silent edit to the pre-registered predictions fails loudly.
EXPECTED_MATRIX_SHA256 = "60853077e446dd228ff0dae956b2d67925f63329f58d7107534af4fa138571e2"

# The committed envelope pre-registration hash
# (docs/envelope-preregistration.md). Pinned so a silent edit to the scoring
# method (MEAN over SUM), the 13-candidate set, or either calibrated threshold
# fails loudly. An intended amendment updates this pin in the same commit,
# which makes the change legible in the diff rather than invisible.
# Updated by Amendment 4 (docs/schema-amendments.md): the §4 negative-control
# table was re-measured against the store's real tool-session observations
# after the published table was found to have used a step-0 stub that omitted
# rotation_output_object. Both thresholds are unchanged; only the baseline
# table moved. Previous pin, for the record:
#   e56fe31d6560ef940b694afc0acd9304518930e02e1e9bda06362d5f6ce5e568
EXPECTED_ENVELOPE_PREREG_SHA256 = (
    "5d5d95662689914916f03e1b7e1ef0c13598722337da004d239eeb28df044c9a"
)


def _manifest():
    return DefenseStack(config=DefenseConfig(l2=True), fixture_id="t0").manifest()


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


# -- envelope pre-registration hash -----------------------------------------


def test_manifest_includes_envelope_prereg_hash():
    m = _manifest()
    assert m["envelope_preregistration_sha256"] == envelope_preregistration_sha256()
    assert len(m["envelope_preregistration_sha256"]) == 64
    validate_manifest(m)


def test_manifest_without_envelope_prereg_hash_is_rejected():
    m = _manifest()
    del m["envelope_preregistration_sha256"]
    with pytest.raises(ManifestError):
        validate_manifest(m)


def test_manifest_with_blank_envelope_prereg_hash_is_rejected():
    m = _manifest()
    m["envelope_preregistration_sha256"] = ""
    with pytest.raises(ManifestError):
        validate_manifest(m)


def test_manifest_with_short_envelope_prereg_hash_is_rejected():
    m = _manifest()
    m["envelope_preregistration_sha256"] = "abc123"
    with pytest.raises(ManifestError):
        validate_manifest(m)


def test_manifest_with_non_string_envelope_prereg_hash_is_rejected():
    m = _manifest()
    m["envelope_preregistration_sha256"] = 12345
    with pytest.raises(ManifestError):
        validate_manifest(m)


def test_envelope_prereg_hash_matches_committed_document():
    """Pinned. A failure here means docs/envelope-preregistration.md changed:
    either an intended amendment (update this pin in the same commit) or an
    edit to the pre-registered method or thresholds that must not pass
    silently."""
    assert envelope_preregistration_sha256() == EXPECTED_ENVELOPE_PREREG_SHA256


def test_the_two_prereg_hashes_are_distinct():
    """Guards against both fields being wired to the same document."""
    assert grrcon_matrix_sha256() != envelope_preregistration_sha256()


def test_manifest_error_names_the_missing_field():
    m = _manifest()
    del m["envelope_preregistration_sha256"]
    with pytest.raises(ManifestError, match="envelope_preregistration_sha256"):
        validate_manifest(m)


def test_schema_amendments_log_is_not_hashed():
    """docs/schema-amendments.md is an append-only change log: a pinned hash
    would break on every legitimate amendment, which would train the pin to be
    updated reflexively and defeat the point of pinning the others. Git
    history carries it instead."""
    m = _manifest()
    assert not any("amendment" in key.lower() for key in m)
