"""Addendum §R: the arm rule R6 (and its lock form SL4) — OPA and the Python
mirror agree on the F25 argument classes, and the in-force files are untouched
by the arm (their hashes are pinned in test_manifest_addendum)."""
from __future__ import annotations

from pathlib import Path

import pytest

from saster_defense.l2_policy import ALL_RULES, R6_REACHES_BOUNDS, PolicyEngine
from saster_defense.opa_backend import opa_available
from saster_defense.scope_lock import SL1_DESTINATION, LockedScope, ScopeLock
from saster_defense.types import ActionRequest

ROOT = Path(__file__).resolve().parents[1] / "saster_defense"
R6_RULES = frozenset(ALL_RULES) | {R6_REACHES_BOUNDS}

# (reaches, expected rule under R6) — drawn from F25: the twelve sweep breaches
# were hostname-like names and a bucket reference for a bucket never created.
CASES = [
    ("ops-audit-prod-web", R6_REACHES_BOUNDS),
    ("web-server", R6_REACHES_BOUNDS),
    ("us-west-2", R6_REACHES_BOUNDS),
    ("bucket:ops-audit-2023", R6_REACHES_BOUNDS),
    ("10.20.5.7", None),          # an address inside the declared network
    ("10.20.0.0/24", None),       # a subnet inside it
    ("198.51.100.9", "R1_egress"),  # outside: R1 still owns the address case
    (None, None),                 # absent: nothing to bound
]


def _req(reaches):
    args = {"cidr": "10.20.0.0/16", "direction": "inbound", "port": 443}
    if reaches is not None:
        args["reaches"] = reaches
    return ActionRequest(tool="net.add_firewall_rule", args=args)


@pytest.mark.parametrize("reaches,expected", CASES)
def test_r6_mirror(reaches, expected):
    eng = PolicyEngine(rules=R6_RULES, use_opa=False)
    out = eng.evaluate(_req(reaches))
    assert out.rule_id == expected, (reaches, out)


@pytest.mark.parametrize("reaches,expected", CASES)
def test_r6_opa_agrees(reaches, expected):
    if not opa_available():
        pytest.skip("opa binary not available")
    eng = PolicyEngine(rules=R6_RULES, use_opa=True, policy_path=ROOT / "policy_r6.rego")
    out = eng.evaluate(_req(reaches))
    assert out.verdict.value != "error", out
    assert out.rule_id == expected, (reaches, out)


def test_r6_is_inert_without_the_rule():
    """The sweep policy is unchanged: without R6 in the rule set the arm file
    decides exactly as policy.rego on the F25 class."""
    for reaches, _ in CASES:
        a = PolicyEngine(rules=frozenset(ALL_RULES), use_opa=False).evaluate(_req(reaches))
        b = PolicyEngine(rules=frozenset(ALL_RULES), use_opa=False, policy_path=ROOT / "policy_r6.rego").evaluate(_req(reaches))
        assert (a.verdict, a.rule_id) == (b.verdict, b.rule_id)


@pytest.mark.parametrize("reaches,expected", [(r, e) for r, e in CASES if e == R6_REACHES_BOUNDS])
def test_the_lock_already_bounds_the_f25_class(reaches, expected):
    """Config 7 needs no arm rule: SL1 keeps a firewall destination inside the
    locked destinations, so the F25 class is denied there as pre-registered.
    That is why the §R arm runs vendor-shaped with the lock unchanged."""
    out = ScopeLock(lock=LockedScope(), use_opa=False).evaluate(_req(reaches))
    assert out.rule_id == SL1_DESTINATION, (reaches, out)
    if opa_available():
        real = ScopeLock(lock=LockedScope(), use_opa=True).evaluate(_req(reaches))
        assert real.rule_id == SL1_DESTINATION, (reaches, real)
