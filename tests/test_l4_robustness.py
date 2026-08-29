"""L4 response robustness — every non-conforming AgentDoG reply maps to
unavailable (ran=False), never to clean, a default verdict, or WARN.

The real backend introduced this risk: L4's verdict is now a parse of free-text
model output. A malformed reply that silently scored as no-detection would
inflate the headline toward "contained", the error least likely to be noticed.
So each response shape has a rejection test."""
from __future__ import annotations

import httpx

import saster_defense.l4_auditor as l4
from saster_defense.l4_auditor import TrajectoryAuditor, _parse_verdict
from saster_defense.types import Verdict

ENDPOINT = "http://[fd00:200::4]:8001"


def _auditor() -> TrajectoryAuditor:
    return TrajectoryAuditor(observer_model="AI45Research/AgentDoG-Qwen3-4B", endpoint=ENDPOINT)


class _FakeResp:
    def __init__(self, payload, json_error: bool = False):
        self._payload = payload
        self._json_error = json_error

    def raise_for_status(self):
        return None

    def json(self):
        if self._json_error:
            raise ValueError("no json")
        return self._payload


def _chat(content, finish_reason="stop"):
    return {"choices": [{"index": 0, "message": {"role": "assistant", "content": content},
                         "finish_reason": finish_reason}]}


def _patch_post(monkeypatch, *, resp=None, exc=None):
    def _post(*_a, **_k):
        if exc is not None:
            raise exc
        return resp
    monkeypatch.setattr(l4.httpx, "post", _post)


def _assert_unavailable(out):
    assert out.verdict is Verdict.UNAVAILABLE, out
    assert out.ran is False
    assert out.is_unavailable
    # never clean, never a default, never WARN
    assert out.verdict not in (Verdict.ALLOW, Verdict.WARN)


# -- one rejection test per non-clean response shape ------------------------


def test_empty_response_is_unavailable(monkeypatch):
    _patch_post(monkeypatch, resp=_FakeResp(_chat("")))
    _assert_unavailable(_auditor()._audit_http("traj"))


def test_whitespace_only_response_is_unavailable(monkeypatch):
    _patch_post(monkeypatch, resp=_FakeResp(_chat("   \n  ")))
    _assert_unavailable(_auditor()._audit_http("traj"))


def test_refusal_is_unavailable(monkeypatch):
    _patch_post(monkeypatch, resp=_FakeResp(_chat("I'm sorry, I can't assist with that request.")))
    _assert_unavailable(_auditor()._audit_http("traj"))


def test_content_filter_blanked_turn_is_unavailable(monkeypatch):
    _patch_post(monkeypatch, resp=_FakeResp(_chat(None, finish_reason="content_filter")))
    _assert_unavailable(_auditor()._audit_http("traj"))


def test_reasoning_around_the_verdict_token_is_unavailable(monkeypatch):
    # WARN appears, but wrapped in reasoning — not a conforming single token.
    _patch_post(monkeypatch, resp=_FakeResp(_chat("The agent copied credential material, therefore WARN.")))
    _assert_unavailable(_auditor()._audit_http("traj"))


def test_reasoning_containing_allow_is_unavailable(monkeypatch):
    _patch_post(monkeypatch, resp=_FakeResp(_chat("I would ALLOW this, it looks benign.")))
    _assert_unavailable(_auditor()._audit_http("traj"))


def test_unrecognized_token_is_unavailable(monkeypatch):
    _patch_post(monkeypatch, resp=_FakeResp(_chat("MAYBE")))
    _assert_unavailable(_auditor()._audit_http("traj"))


def test_both_tokens_present_is_unavailable(monkeypatch):
    _patch_post(monkeypatch, resp=_FakeResp(_chat("WARN ALLOW")))
    _assert_unavailable(_auditor()._audit_http("traj"))


def test_http_error_is_unavailable(monkeypatch):
    _patch_post(monkeypatch, exc=httpx.ConnectError("connection refused"))
    _assert_unavailable(_auditor()._audit_http("traj"))


def test_timeout_is_unavailable(monkeypatch):
    _patch_post(monkeypatch, exc=httpx.ReadTimeout("timed out"))
    _assert_unavailable(_auditor()._audit_http("traj"))


def test_malformed_json_is_unavailable(monkeypatch):
    _patch_post(monkeypatch, resp=_FakeResp(None, json_error=True))
    _assert_unavailable(_auditor()._audit_http("traj"))


def test_missing_choices_is_unavailable(monkeypatch):
    _patch_post(monkeypatch, resp=_FakeResp({}))
    _assert_unavailable(_auditor()._audit_http("traj"))


# -- positive controls: only an exact conforming token is trusted -----------


def test_exact_warn_is_warn(monkeypatch):
    _patch_post(monkeypatch, resp=_FakeResp(_chat("WARN")))
    out = _auditor()._audit_http("traj")
    assert out.verdict is Verdict.WARN
    assert out.ran is True


def test_exact_allow_is_allow(monkeypatch):
    _patch_post(monkeypatch, resp=_FakeResp(_chat("ALLOW")))
    out = _auditor()._audit_http("traj")
    assert out.verdict is Verdict.ALLOW
    assert out.ran is True


def test_token_tolerates_whitespace_and_trailing_period(monkeypatch):
    for content, expect in [(" warn \n", Verdict.WARN), ("ALLOW.", Verdict.ALLOW), ("Warn", Verdict.WARN)]:
        _patch_post(monkeypatch, resp=_FakeResp(_chat(content)))
        assert _auditor()._audit_http("traj").verdict is expect


def test_parse_verdict_unit():
    assert _parse_verdict("WARN") == "warn"
    assert _parse_verdict("allow.") == "allow"
    assert _parse_verdict("") is None
    assert _parse_verdict("so WARN") is None
    assert _parse_verdict("SAFE") is None
