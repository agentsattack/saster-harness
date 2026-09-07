"""Addendum §T: the phone-home directive variant is one appended sentence,
composed for the compromised mode only, and names the declared sink."""
from __future__ import annotations

from carl_ops_agent.agent import HIDDEN_DIRECTIVE, CarlOpsMode
from carl_ops_agent.model_driven import DIRECTIVE_VARIANTS, directive_text, system_prompt
from carl_ops_state.model import Scope


def test_phone_home_names_the_declared_sink():
    assert Scope().egress_sink in DIRECTIVE_VARIANTS["phone_home"]


def test_variant_is_appended_to_the_hidden_directive_only_when_compromised():
    text = directive_text(CarlOpsMode.COMPROMISED, "firewall", "phone_home")
    assert text.startswith(HIDDEN_DIRECTIVE) and DIRECTIVE_VARIANTS["phone_home"] in text
    assert directive_text(CarlOpsMode.INDUCED, None, "phone_home") is None
    assert DIRECTIVE_VARIANTS["phone_home"] not in system_prompt(CarlOpsMode.INDUCED, None, directive_variant="phone_home")
    assert DIRECTIVE_VARIANTS["phone_home"] in system_prompt(CarlOpsMode.COMPROMISED, "firewall", directive_variant="phone_home")
    assert DIRECTIVE_VARIANTS["phone_home"] not in system_prompt(CarlOpsMode.COMPROMISED, "firewall")
