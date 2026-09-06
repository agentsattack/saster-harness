"""F27: the input classifier sees the wire form of an action."""
from __future__ import annotations

from saster_defense.l1_classifier import render_action_text
from saster_defense.types import ActionRequest


def test_render_is_the_wire_form():
    req = ActionRequest(tool="secrets.rotate_credential", args={"credential_ref": "cred:prod-web:db", "b": 1})
    text = render_action_text(req)
    assert text.startswith("secrets_rotate_credential ")
    # emission order, not key-sorted
    assert text.index("credential_ref") < text.index('"b"')
    assert "secrets.rotate" not in text
