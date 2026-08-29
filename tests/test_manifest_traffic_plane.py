"""The run manifest records the deliberate management-plane traffic decision,
so a corpus is self-describing about which network plane produced it."""
from __future__ import annotations

from saster_defense import DefenseConfig, DefenseStack


def test_manifest_records_management_plane_decision():
    m = DefenseStack(config=DefenseConfig(l2=True), fixture_id="t0").manifest()
    tp = m["traffic_plane"]
    assert tp["plane"] == "management"
    assert tp["deliberate"] is True
    # both victim models named against their management-plane backends
    assert set(tp["victim_backends"].values()) == {
        "Qwen/Qwen3-8B", "mistralai/Ministral-8B-Instruct-2410",
    }
    # the fabric alternative and the reason it was not taken are recorded
    assert "192.168.1.228:8000" in tp["victim_backends"]
    assert "fd00:200::3:8000" in tp["fabric_alternative"]
    assert "consistent-hash" in tp["rationale"]
    assert "DIFFERENT victim models" in tp["rationale"]
