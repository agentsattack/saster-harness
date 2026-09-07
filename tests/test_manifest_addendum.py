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
# Prior pins, in order, each in the addendum's own hash-history table:
PRIOR_ADDENDUM_SHA256 = (
    "73b3b177626f00b202b5c035cb579474c0ce34e7c6654d47109e85457e04c29e",  # 2026-09-06, §O
    "970f5b0afd8b6b3019a96bdc32543849ae95fe7f6c39a9578b166d2a078712b2",  # 2026-09-06, §P §Q
    "9657077b0c9d75552b67c7bee0b1989d3f1b6685126a17a9b4cd11607614b648",  # 2026-09-06, §R
    "d5b753c4a497b5671ca8c758a462d044e78960490edff9cc99c49077907b2fad",  # 2026-09-06, §S
    "d1fe956f419592dd2e386a7dab75ea03e3dcf0f272b75e788b7ff95e0088ebf0",  # 2026-09-06, §S as run
    "ffbde3c9e99bc2f4dbd0c20bc8827bb898569d61baa3da5d83663548a2e31e16",  # 2026-09-05 opened: A golden trace, B marker units
    "fffd4dc734381ae374918aa1e6e3ecc42540d771a415f8e8e0bdf8dc044bbe0e",  # 2026-09-05 + C P17, D P2-D, E base-rate, F P6; closure
    "eea89233100903f377fa61fa8bf653accf2d1cc4492046db928f3dc28db2c849",  # 2026-09-05 + G canary thresholds, H tarpit rule
    "2560bc3e9f7e99ab58c11481afae1599f9f5b406b0697d170f72e55d42ad5553",  # 2026-09-05 + I fixture-validity, J P17b, K bucket route
    "b848011fcafb27025ebec3a28ab44cd09aadc901568cef0576836ba0c11accf0",  # 2026-09-05 + L Ministral tool_choice, M within-class length
    "50ef648118a2d05289ab244ea70c1da1a7e5c6546595eb698959977b0d675fa5",  # 2026-09-05 + N blocking-layer admission gate
)
# 2026-09-05: + C P17, D P2 as discrimination, E base-rate rule, F P6
# conditioned; closure at the start of Stage 3 stated.
# 2026-09-06: + O P5 at two levels.
EXPECTED_ADDENDUM_SHA256 = "206e36b2ce3e9a5325f6a4c7bf4dc9d42c5e2051ab10ac08fa559ff0f1314dae"


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


def test_every_prior_pin_is_in_the_addendums_hash_history():
    text = GRRCON_ADDENDUM_PATH.read_text()
    for prior in PRIOR_ADDENDUM_SHA256:
        assert prior in text, f"prior pin {prior[:12]} missing from the hash-history table"
    assert EXPECTED_ADDENDUM_SHA256 not in text, "the current hash is pinned in the test, not typed into the file"
    assert "CLOSES at the start of Stage 3" in text


def test_addendum_is_dated_and_never_edits_the_closed_matrix():
    text = GRRCON_ADDENDUM_PATH.read_text()
    assert "2026-09-05" in text
    assert "CLOSED" in text
    # the closed matrix is byte-identical to its pin (its own test asserts
    # the value; this asserts the addendum did not touch it)
    from tests.test_manifest_prereg import EXPECTED_MATRIX_SHA256

    assert grrcon_matrix_sha256() == EXPECTED_MATRIX_SHA256


# The declared policy in force for the w24b sweep. A mid-sweep change moves
# this hash and is refused by this test; R5 is drafted beside it
# (saster_defense/policy_r5_draft.rego) and enters as a post-sweep arm.
SWEEP_POLICY_SHA256 = "46e612109aab6088208852ba96601d44af25bbd12fbfbdb6ee9bdc2a04ae7c3c"
R5_DRAFT_SHA256 = "c11a144b7029b4a672104a84ca7147759aa8be5a940dc8ababb40c931b9a5eba"
R6_DRAFT_SHA256 = "cf8fbbb8aeb235dc4271f791f5fb48d0b46e366dbd0afef3d40ce9df0e8b5ff5"  # drafted 2026-09-06, unwired
R6_ARM_POLICY_SHA256 = "296bf24061eabdcf69db46c90baa8b26f31ace456a20f601d3178dcb0d50a2a2"  # addendum §R arm file: policy.rego + R6
SWEEP_LOCK_SHA256 = "7f3a8dc7605a1489e890eff32e3344905062218b64b2f9d3fa088220ac028947"


def test_the_sweep_policy_is_unchanged_and_r5_is_only_a_draft():
    import hashlib
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "saster_defense"
    assert hashlib.sha256((root / "policy.rego").read_bytes()).hexdigest() == SWEEP_POLICY_SHA256
    assert hashlib.sha256((root / "policy_r5_draft.rego").read_bytes()).hexdigest() == R5_DRAFT_SHA256
    assert hashlib.sha256((root / "policy_r6_draft.rego").read_bytes()).hexdigest() == R6_DRAFT_SHA256
    assert hashlib.sha256((root / "policy_r6.rego").read_bytes()).hexdigest() == R6_ARM_POLICY_SHA256
    assert hashlib.sha256((root / "scope_lock.rego").read_bytes()).hexdigest() == SWEEP_LOCK_SHA256
    # the arm files are the in-force files plus one block each
    assert (root / "policy_r6.rego").read_text().startswith((root / "policy.rego").read_text().rstrip("\n"))
    from saster_defense import ALL_RULES

    assert "R5_grant_population" not in ALL_RULES
    assert "R5" not in (root / "policy.rego").read_text()
