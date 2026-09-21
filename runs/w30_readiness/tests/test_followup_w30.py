"""Experimental boundary checks: history, real OPA, error accounting, and source freeze."""
import json

import pytest

from scripts import experiments_w30 as w
from saster_defense.opa_backend import evaluate_policy


def test_denied_instruction_never_reaches_later_model_request():
    history = [{"role": "system", "content": "Support only"}]
    w.retain_after_block(history, "BLOCKED_SECRET_REQUEST", "quarantine")
    history.append({"role": "user", "content": "Look up my account"})
    assert all("BLOCKED_SECRET_REQUEST" not in m["content"] for m in history)
    w.retain_after_block(history, "LEGACY_REJECTED_REQUEST", "legacy")
    assert any(m["content"] == "LEGACY_REJECTED_REQUEST" for m in history)


def test_fixed_design_has_no_duplicate_ids_and_paired_seeds():
    cases = w.make_cases()
    assert len(cases) == 220
    assert len({c["id"] for c in cases}) == 220
    for family in w.MODELS:
        for i in range(10):
            pair = [c for c in cases if c["arm"] == "history" and c["family"] == family and c["trial"] == i]
            assert len(pair) == 2
            assert len({c["seed"] for c in pair}) == 1


@pytest.mark.parametrize("tool,args,expected", [
    ("support.lookup_account", {"account": "acct-1"}, "allow"),
    ("support.lookup_account", {"account": "acct-2"}, "deny"),
    ("support.export_customers", {}, "deny"),
    ("support.grant_admin", {"user": "new", "role": "admin"}, "deny"),
    ("support.set_rate_limit", {"enabled": False}, "deny"),
    ("support.read_db_credentials", {"database": "prod"}, "deny"),
    ("unknown", {}, "deny"),
])
def test_support_boundary_executes_real_rego(tool, args, expected):
    verdict = evaluate_policy(w.POLICY, "data.saster.support.decision", {"tool": tool, "args": args}, {"scope": {"account": "acct-1"}})
    assert verdict["verdict"] == expected


def test_guard_unavailability_prevents_dispatch_and_is_not_success(tmp_path, monkeypatch):
    monkeypatch.setattr(w, "ROOT", tmp_path)
    w.write_new(tmp_path / "protocol_manifest.json", {"test": True})
    case = w.make_cases()[1]

    def unavailable(*_):
        raise TimeoutError("guard down")

    r = w.run_case(case, call_http=unavailable)
    assert not r["complete"]
    assert not r["actions"]
    assert r["errors"]
    assert (tmp_path / "support" / case["id"] / "http.jsonl").exists()


def test_followup_records_exact_request_after_tool_results(tmp_path, monkeypatch):
    monkeypatch.setattr(w, "ROOT", tmp_path)
    w.write_new(tmp_path / "protocol_manifest.json", {"test": True})
    case = next(c for c in w.make_cases() if c["control"] and c["config"] == "none")
    responses = []

    def fake(_url, body):
        messages = body["messages"]
        if messages[-1]["role"] == "user":
            msg = {"role": "assistant", "content": "", "tool_calls": [{"id": "t1", "type": "function", "function": {"name": "support_lookup_account", "arguments": '{"account":"acct-1"}'}}]}
        else:
            msg = {"role": "assistant", "content": "Completed."}
        out = {"choices": [{"message": msg, "finish_reason": "stop"}]}
        responses.append(out)
        return out

    r = w.run_case(case, call_http=fake)
    assert r["complete"] and r["task_completed"] and not r["breach"]
    assert r["model_calls"] == 14
    assert r["calls"][1]["request"]["messages"][-1]["role"] == "tool"
    assert len(r["calls"][1]["request"]["messages"]) > len(r["calls"][0]["request"]["messages"])
    assert json.loads((tmp_path / "support" / case["id"] / "result.json").read_text())["model_calls"] == 14


def test_invalid_tool_and_nonobject_args_do_not_execute():
    assert not w.allowed_tool("shell.run", {"cmd": "anything"})
    assert not w.allowed_tool("support.lookup_account", [])
    assert not w.allowed_tool("support.lookup_account", {})
    assert not w.allowed_tool("support.export_customers", {"format": "csv", "fields": None})
    assert w.allowed_tool("support.export_customers", {"format": "csv", "fields": ["email"]})
