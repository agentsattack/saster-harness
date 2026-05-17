"""Tests for HARAdapter — parsing, session correlation, redaction, detector chain."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from saster_harness.adapters import HARAdapter
from saster_harness.adapters.har_adapter import (
    AutoSessionCorrelator,
    CookieSessionCorrelator,
    HeaderSessionCorrelator,
    TimeWindowSessionCorrelator,
    redact_body_bytes,
    redact_headers,
)
from saster_harness.detectors import saster_26, saster_31

FIXTURE = Path(__file__).parent / "fixtures" / "har" / "sample_chat.har"


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def test_read_file_yields_chat_turns_and_skips_static_asset() -> None:
    adapter = HARAdapter()
    turns = list(adapter.read_file(FIXTURE))
    # 4 chat-shape entries; the 5th (GET app.js) is a non-chat static asset
    # that HttpJsonAdapter should reject.
    assert len(turns) == 4
    methods = {turn.request_method for turn in turns}
    assert methods == {"POST"}


def test_read_file_populates_har_extras() -> None:
    adapter = HARAdapter()
    turn = next(adapter.read_file(FIXTURE))
    assert "har_started" in turn.extras
    assert "har_request_size" in turn.extras


def test_read_file_handles_missing_har_gracefully(tmp_path: Path) -> None:
    empty = tmp_path / "empty.har"
    empty.write_text('{"log": {"version": "1.2", "entries": []}}')
    adapter = HARAdapter()
    assert list(adapter.read_file(empty)) == []


# ---------------------------------------------------------------------------
# Session correlation — header
# ---------------------------------------------------------------------------


def test_header_strategy_uses_x_session_id() -> None:
    adapter = HARAdapter(session_id_strategy="header:X-Session-Id")
    turns = list(adapter.read_file(FIXTURE))
    chat_a = [t for t in turns if t.target_host == "example.test"]
    # First two entries carry X-Session-Id; last chat entry does NOT,
    # so the header correlator returns None for it — and the adapter
    # falls back on whatever HttpJsonAdapter inferred (derived-… hash).
    # That's the documented behaviour for header-only mode.
    sessions_with_x = [t.session_id for t in chat_a if t.session_id == "demo-session-A"]
    assert len(sessions_with_x) == 2


def test_header_strategy_rejects_empty_header_name() -> None:
    with pytest.raises(ValueError):
        HARAdapter(session_id_strategy="header:")


# ---------------------------------------------------------------------------
# Session correlation — cookie
# ---------------------------------------------------------------------------


def test_cookie_strategy_clusters_by_sessionid_cookie() -> None:
    adapter = HARAdapter(session_id_strategy="cookie")
    turns = list(adapter.read_file(FIXTURE))
    by_session: dict[str, list[int]] = {}
    for t in turns:
        by_session.setdefault(t.session_id, []).append(t.turn_idx)
    # Three entries share cookie alpha-…; one is the upload entry (no
    # session cookie → falls through to None, then HttpJsonAdapter's
    # derived fallback); one entry uses cookie beta-….
    alpha_sessions = [k for k in by_session if k.startswith("cookie-")]
    assert len(alpha_sessions) >= 2  # one per distinct session cookie


# ---------------------------------------------------------------------------
# Session correlation — time-window
# ---------------------------------------------------------------------------


def test_time_window_strategy_groups_close_entries() -> None:
    adapter = HARAdapter(session_id_strategy="time", time_window_seconds=30)
    turns = list(adapter.read_file(FIXTURE))
    by_session: dict[str, list[int]] = {}
    for t in turns:
        by_session.setdefault(t.session_id, []).append(t.turn_idx)
    # The fixture spans 12:00 → 13:30 — well outside a 30s window —
    # so we expect at least two distinct synthesised sessions per host.
    example_sessions = [k for k in by_session if k.startswith("har-example.test-")]
    assert len(example_sessions) >= 2


def test_auto_strategy_falls_through_chain() -> None:
    """The 'auto' strategy uses header → cookie → time; verify it
    produces sensible session ids end-to-end."""
    adapter = HARAdapter()  # default = auto
    turns = list(adapter.read_file(FIXTURE))
    # Every turn should land in some session — auto's last fallback is
    # time-window, which always returns something.
    assert all(turn.session_id for turn in turns)


def test_custom_correlator_protocol() -> None:
    """Custom strategies plug in without subclassing the adapter."""

    class _StaticCorrelator:
        def correlate(self, entry: dict, turn) -> str:  # type: ignore[no-untyped-def]
            return "static-session"

    adapter = HARAdapter(session_id_strategy=_StaticCorrelator())
    turns = list(adapter.read_file(FIXTURE))
    assert {turn.session_id for turn in turns} == {"static-session"}


def test_invalid_strategy_rejected() -> None:
    with pytest.raises(ValueError):
        HARAdapter(session_id_strategy="bogus")


# ---------------------------------------------------------------------------
# Redaction — header level
# ---------------------------------------------------------------------------


def test_redact_headers_strips_known_sensitive() -> None:
    redacted = redact_headers(
        {
            "Authorization": "Bearer eyJabc.def.ghi",
            "Cookie": "session=abc",
            "X-API-Key": "secret-key",
            "Content-Type": "application/json",
        }
    )
    assert redacted["Authorization"] == "[REDACTED]"
    assert redacted["Cookie"] == "[REDACTED]"
    assert redacted["X-API-Key"] == "[REDACTED]"
    assert redacted["Content-Type"] == "application/json"


def test_redact_body_strips_sensitive_json_keys() -> None:
    body = json.dumps(
        {"username": "alice", "password": "hunter2", "nested": {"api_key": "k"}}
    ).encode()
    redacted = redact_body_bytes(body)
    assert redacted is not None
    parsed = json.loads(redacted)
    assert parsed["password"] == "[REDACTED]"
    assert parsed["nested"]["api_key"] == "[REDACTED]"
    assert parsed["username"] == "alice"


def test_redact_body_strips_jwt_and_ssn_patterns() -> None:
    body = (
        b'Auth: eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.signature_fake_value_zzz '
        b"SSN 123-45-6789 trailing"
    )
    redacted = redact_body_bytes(body)
    assert redacted is not None
    assert b"123-45-6789" not in redacted
    assert b"eyJhbGciOiJIUzI1NiJ9" not in redacted
    assert b"[REDACTED]" in redacted


def test_har_default_redaction_runs_on_load() -> None:
    """Sensitive headers in the fixture must not surface on TurnData."""
    adapter = HARAdapter()  # redact=True default
    for turn in adapter.read_file(FIXTURE):
        raw = (turn.raw_request or b"").decode("utf-8", errors="replace")
        # The fixture's JWT bearer token must have been scrubbed.
        assert "eyJabc.def.ghi-NOT-A-REAL-TOKEN" not in raw


def test_har_redact_false_emits_warning_when_loading_sensitive(
    tmp_path: Path,
) -> None:
    adapter = HARAdapter(redact=False)
    with pytest.warns(UserWarning, match="redact=False"):
        list(adapter.read_file(FIXTURE))


def test_extra_redacted_body_keys() -> None:
    adapter = HARAdapter(extra_redacted_body_keys=["internal_id"])
    body = json.dumps({"internal_id": "secret-deploy-123", "msg": "ok"}).encode()
    redacted = adapter._redact_body(body)
    assert redacted is not None
    assert b"secret-deploy-123" not in redacted


# ---------------------------------------------------------------------------
# Detector chain integration
# ---------------------------------------------------------------------------


def test_detector_chain_fires_on_har_derived_turns() -> None:
    """The recon-shape entry should fire SASTER-26; the upload entry
    should fire SASTER-31."""
    adapter = HARAdapter()
    fired_by: dict[str, list[str]] = {}
    for turn in adapter.read_file(FIXTURE):
        for det in (saster_26.DETECTOR, saster_31.DETECTOR):
            event = det.evaluate(turn)
            if event is not None:
                fired_by.setdefault(event.saster_id, []).append(
                    event.evidence.get("signal", "")
                )
    assert "SASTER-26" in fired_by
    assert "SASTER-31" in fired_by
    assert fired_by["SASTER-31"][0] == "structured_egress_with_sensitive_fields"


# ---------------------------------------------------------------------------
# Correlator unit tests
# ---------------------------------------------------------------------------


def test_auto_correlator_rejects_empty_chain() -> None:
    with pytest.raises(ValueError):
        AutoSessionCorrelator([])


def test_header_correlator_handles_missing_header() -> None:
    correlator = HeaderSessionCorrelator("X-Missing")
    result = correlator.correlate({"request": {"headers": []}}, _make_minimal_turn())
    assert result is None


def test_cookie_correlator_handles_missing_cookies() -> None:
    correlator = CookieSessionCorrelator()
    assert (
        correlator.correlate({"request": {"cookies": []}}, _make_minimal_turn())
        is None
    )


def test_time_window_correlator_starts_new_session_after_gap() -> None:
    correlator = TimeWindowSessionCorrelator(window_seconds=10)
    t1 = _make_minimal_turn(host="x.example")
    s1 = correlator.correlate({"startedDateTime": "2026-05-17T12:00:00Z"}, t1)
    s2 = correlator.correlate({"startedDateTime": "2026-05-17T12:00:05Z"}, t1)
    s3 = correlator.correlate({"startedDateTime": "2026-05-17T12:05:00Z"}, t1)
    assert s1 == s2  # within window
    assert s2 != s3  # outside window


def _make_minimal_turn(host: str = "example.test"):  # type: ignore[no-untyped-def]
    from saster_harness import TurnData

    return TurnData(session_id="", turn_idx=0, target_host=host)
