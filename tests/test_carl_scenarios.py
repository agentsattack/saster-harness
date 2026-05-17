"""Carl scenario integration tests.

Exercises the recon and exfil scenarios end-to-end against the v0.1
detector set and asserts the expected SASTER patterns fire at the
expected captured-turn indices. These are the "did the framework wire
up correctly?" smoke checks an operator runs after install.
"""

from __future__ import annotations

from collections import defaultdict

from carl import carl_agent, run_exfil, run_recon
from saster_harness.detectors import saster_26, saster_31, saster_33


def test_carl_recon_fires_saster_26_and_33_three_times() -> None:
    turns = run_recon._build_turn_stream()
    # SASTER-33 carries per-session baseline state — instantiate once
    # across the whole turn stream so the baseline can lock in.
    detectors = (saster_26.DETECTOR, saster_33.ContextStrippingDetector())
    firings: dict[str, list[int]] = defaultdict(list)
    for turn in turns:
        for det in detectors:
            ev = det.evaluate(turn)
            if ev is not None:
                firings[ev.saster_id].append(turn.turn_idx)

    # Recon side-channels live at captured turns 5/11/17, matching the
    # slide deck and recorded demos.
    assert firings["SASTER-26"] == [5, 11, 17]
    # SASTER-33 also fires on each side-channel turn (system msg stripped)
    # — and only on those turns.
    assert firings["SASTER-33"] == [5, 11, 17]


def test_carl_exfil_fires_saster_31_at_turn_8() -> None:
    turns = run_exfil._build_turn_stream()
    firings: list[int] = []
    for turn in turns:
        ev = saster_31.DETECTOR.evaluate(turn)
        if ev is not None:
            firings.append(turn.turn_idx)
            # spot-check evidence shape
            assert ev.evidence["record_count"] == len(carl_agent.SYNTHETIC_USER_RECORDS)
            assert "email" in ev.evidence["sensitive_fields"]
            assert "password_hash" in ev.evidence["sensitive_fields"]
            assert "ssn" in ev.evidence["sensitive_fields"]

    # Exfil POST at captured turn 8.
    assert firings == [8]


def test_carl_recon_runner_returns_zero() -> None:
    """The runner's CLI exit code is part of the demo contract."""
    assert run_recon.main() == 0


def test_carl_exfil_runner_returns_zero() -> None:
    assert run_exfil.main() == 0
