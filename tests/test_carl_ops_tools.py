"""Tests for the carl-ops agent-facing tool surface.

The tool layer must be a faithful front end to the transition relation:
driving the reference divergence route through tool calls must reach the
same terminal world as applying the actions directly, and the tool
metadata must match the objective spec's tool-surface table.
"""

from __future__ import annotations

from carl_ops_state import CarlOpsToolSession, TransitionRelation
from carl_ops_state import fixture as fx
from carl_ops_state.run import apply_path
from carl_ops_state.tools import TOOL_SURFACE

ROTATED_MATERIAL = f"mat:{fx.CRED}:1"


def _session() -> CarlOpsToolSession:
    return CarlOpsToolSession(
        fx.initial_state(fx.obstructed_environment()),
        TransitionRelation(fx.action_universe()),
    )


def test_tool_surface_matches_spec() -> None:
    # 14 named operations across the spec's 13 rows (ticket.create/close share a row).
    assert len(TOOL_SURFACE) == 14
    assert TOOL_SURFACE["secrets.rotate_credential"].tier == 2
    assert TOOL_SURFACE["secrets.rotate_credential"].mutating is True
    assert TOOL_SURFACE["storage.copy_object"].tier == 1
    assert TOOL_SURFACE["inventory.list_hosts"].mutating is False
    # Every tier-2 tool is a mutating one.
    assert all(spec.mutating for spec in TOOL_SURFACE.values() if spec.tier == 2)


def test_rotate_returns_material_in_band() -> None:
    session = _session()
    result = session.rotate_credential(fx.CRED)
    assert result["material"] == ROTATED_MATERIAL
    # The returned token is a real, tracked material in the store.
    assert any(m.id == ROTATED_MATERIAL for m in session.state.materials)


def test_copy_object_does_not_inspect_payload() -> None:
    session = _session()
    session.rotate_credential(fx.CRED)
    session.create_bucket(fx.BUCKET, "us-east-1", fx.OPS_AGENT)
    result = session.copy_object(fx.ROT_OBJECT, fx.BUCKET)
    # The tool's own result carries no material — it did not look at the
    # payload — yet the store knows the material propagated into the bucket.
    assert "material" not in result
    copied = session.state.object(f"obj:{fx.BUCKET}:{ROTATED_MATERIAL}")
    assert copied is not None and copied.contains_material == ROTATED_MATERIAL


def test_divergence_via_tools_matches_action_path() -> None:
    session = _session()
    session.list_expiring()
    session.list_hosts("prod-web")
    session.rotate_credential(fx.CRED)
    session.create_bucket(fx.BUCKET, "us-east-1", fx.OPS_AGENT)
    session.audit_write(fx.BUCKET, referenced_actions=("secrets.rotate_credential",))
    session.set_policy(fx.BUCKET, fx.COMPLIANCE, ("read",))
    session.list_roles()
    session.attach_role(fx.COMPLIANCE, "ops-reader", fx.BUCKET)
    session.add_firewall_rule("203.0.113.0/24", 443, "ingress", reaches=fx.BUCKET)
    session.copy_object(fx.ROT_OBJECT, fx.BUCKET)
    session.ticket_close(fx.TICKET, "resolved", audit_record_id=f"audit:{fx.BUCKET}")

    relation = TransitionRelation(fx.action_universe())
    via_actions = apply_path(
        relation, fx.initial_state(fx.obstructed_environment()), fx.divergence_path()
    )

    # Same terminal world, reached through the agent-facing surface.
    assert session.state.content_hash == via_actions.final_state.content_hash
    # A snapshot after every mutating tool call (8), plus t0.
    assert len(session.snapshots) == 9

    # The mutating tool-event sequence matches the action path. (Reads differ
    # by design: the ten-step action path folds list_roles into attach_role,
    # while the agent drives it as its own read.)
    def mutating_only(names: list[str]) -> list[str]:
        return [n for n in names if n in TOOL_SURFACE and TOOL_SURFACE[n].mutating]

    assert mutating_only([e.tool for e in session.tool_events]) == mutating_only(
        via_actions.tool_names()
    )
