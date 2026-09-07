"""D20 — a correctly-shaped tool call whose required field is null must be
rejected before execution. It is not (2026-09-07): the validator binds to the
store method's signature, and the store executes the call. Strict xfail until
the validator checks the schema the model was sent; the runner is unchanged
before the talk."""
from __future__ import annotations

import pytest

from carl_ops_agent.tool_schemas import validate_arguments

NULL_REQUIRED = [
    ("secrets.rotate_credential", {"credential_ref": None}),
    ("storage.create_bucket", {"name": "ops-audit-x", "region": "us-east-1", "owner": None}),
    ("net.add_firewall_rule", {"cidr": "10.20.0.0/16", "port": None, "direction": "inbound"}),
    ("storage.set_policy", {"bucket": "ops-audit-x", "principal": None, "perms": ["read"]}),
]


@pytest.mark.xfail(strict=True, reason="D20: validate_arguments binds to the signature, not the schema; a null required field passes")
@pytest.mark.parametrize("tool,args", NULL_REQUIRED, ids=[t for t, _ in NULL_REQUIRED])
def test_null_required_field_is_rejected_before_execution(tool, args):
    reason = validate_arguments(tool, args)
    assert reason is not None, f"{tool}: a null required field bound to the signature and would execute"


def test_missing_required_field_is_rejected():
    """The check the validator does make, kept green beside the one it does not."""
    assert validate_arguments("secrets.rotate_credential", {}) is not None
