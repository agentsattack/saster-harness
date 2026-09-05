"""The prediction-matrix addendum is the third hashed document on the run
manifest — same mechanism as the matrix and the envelope pre-registration,
a second file because the matrix is CLOSED. This pin fails loudly on any
edit; an intended amendment updates it in the same commit."""
from __future__ import annotations

import pytest

from saster_defense import DefenseConfig, DefenseStack
from saster_defense.manifest import (
    GRRCON_ADDENDUM_PATH,
    ManifestError,
    envelope_preregistration_sha256,
    grrcon_addendum_sha256,
    grrcon_matrix_sha256,
    validate_manifest,
)

# docs/grrcon-test-matrix-addendum.md as committed. Opened 2026-09-05 with
# section A (golden trace) and B (marker units); P17 lands in Stage 2 and
# re-pins here, in the open.
EXPECTED_ADDENDUM_SHA256 = "ffbde3c9e99bc2f4dbd0c20bc8827bb898569d61baa3da5d83663548a2e31e16"


def _manifest():
    return DefenseStack(config=DefenseConfig(l2=True), fixture_id="t0").manifest()


def test_addendum_hash_matches_committed_document():
    assert grrcon_addendum_sha256() == EXPECTED_ADDENDUM_SHA256


def test_manifest_includes_addendum_hash():
    m = _manifest()
    assert m["grrcon_addendum_sha256"] == grrcon_addendum_sha256()
    assert len(m["grrcon_addendum_sha256"]) == 64
    validate_manifest(m)


def test_manifest_without_addendum_hash_is_rejected():
    m = _manifest()
    del m["grrcon_addendum_sha256"]
    with pytest.raises(ManifestError, match="grrcon_addendum_sha256"):
        validate_manifest(m)


def test_the_three_pinned_documents_are_distinct():
    assert len({grrcon_matrix_sha256(), envelope_preregistration_sha256(),
                grrcon_addendum_sha256()}) == 3


def test_addendum_is_dated_and_never_edits_the_closed_matrix():
    text = GRRCON_ADDENDUM_PATH.read_text()
    assert "2026-09-05" in text
    assert "CLOSED" in text
    # the closed matrix is byte-identical to its pin (its own test asserts
    # the value; this asserts the addendum did not touch it)
    from tests.test_manifest_prereg import EXPECTED_MATRIX_SHA256

    assert grrcon_matrix_sha256() == EXPECTED_MATRIX_SHA256
