"""The 13 model-facing tools as function schemas, derived rather than listed.

Two things are load-bearing here. The tool SET is the denominator
``envelope_mass`` is scored over, so a hand-maintained second list that drifted
by one entry would silently change the metric — these tests assert the schema
set is the derived set. And the canonical names are dotted while vLLM's tool
parsers reject dots, so the wire mapping has to be exactly reversible or a
recorded action would name a tool the store does not have.
"""

from __future__ import annotations

import inspect
import re

import pytest

from carl_ops_agent.agent import NON_MODEL_FACING_TOOLS, CarlOps
from carl_ops_agent.tool_schemas import (
    DESCRIPTIONS,
    canonical_name,
    model_facing_tools,
    tool_schemas,
    validate_arguments,
    wire_name,
)
from carl_ops_state import CarlOpsToolSession
from carl_ops_state.tools import TOOL_SURFACE

#: vLLM's constraint, verbatim from its 400: "must be a-z, A-Z, 0-9, or
#: contain underscores and dashes, with a maximum length of 64".
VLLM_FUNCTION_NAME = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def test_exactly_thirteen_model_facing_tools():
    assert len(model_facing_tools()) == 13


def test_the_schema_set_is_the_derived_set_not_a_second_list():
    """If these ever diverge, envelope_mass is scored over a different
    denominator than the model was offered."""
    assert {s["function"]["name"] for s in tool_schemas()} == {
        wire_name(t) for t in model_facing_tools()
    }
    assert set(model_facing_tools()) == set(TOOL_SURFACE) - NON_MODEL_FACING_TOOLS


def test_the_non_model_facing_tool_is_not_offered():
    offered = {canonical_name(s["function"]["name"]) for s in tool_schemas()}
    assert "ticket.create" not in offered
    assert NON_MODEL_FACING_TOOLS.isdisjoint(offered)


def test_agent_and_schemas_agree_on_the_surface():
    assert set(CarlOps.model_facing_tools()) == set(model_facing_tools())


# -- wire names -------------------------------------------------------------


def test_every_wire_name_is_acceptable_to_vllm():
    """The regression that made this module necessary: a dotted name is a 400,
    so no tool would have been callable at all."""
    for tool in model_facing_tools():
        assert "." not in wire_name(tool)
        assert VLLM_FUNCTION_NAME.match(wire_name(tool))


def test_wire_mapping_round_trips_for_every_tool():
    for tool in model_facing_tools():
        assert canonical_name(wire_name(tool)) == tool


def test_wire_names_are_unique():
    """Reversal is a lookup, so uniqueness is what makes it unambiguous."""
    names = [wire_name(t) for t in model_facing_tools()]
    assert len(set(names)) == len(names)


def test_an_off_surface_name_is_none_not_a_near_match():
    """An unknown tool must be its own outcome. Guessing the closest match
    would put an action the model did not choose into the record."""
    assert canonical_name("storage_delete_bucket") is None
    assert canonical_name("ticket_create") is None  # real tool, not model-facing
    assert canonical_name("") is None


# -- parameters -------------------------------------------------------------


def test_parameters_match_the_store_method_signature():
    """The schema the model sees and the call the store accepts are the same
    thing, derived from one source."""
    for schema in tool_schemas():
        tool = canonical_name(schema["function"]["name"])
        method = getattr(CarlOpsToolSession, CarlOps._TOOL_METHODS[tool])
        expected = {n for n in inspect.signature(method).parameters if n != "self"}
        assert set(schema["function"]["parameters"]["properties"]) == expected


def test_required_parameters_are_those_without_defaults():
    for schema in tool_schemas():
        tool = canonical_name(schema["function"]["name"])
        method = getattr(CarlOpsToolSession, CarlOps._TOOL_METHODS[tool])
        expected = {
            n for n, p in inspect.signature(method).parameters.items()
            if n != "self" and p.default is inspect.Parameter.empty
        }
        assert set(schema["function"]["parameters"]["required"]) == expected


def test_a_tuple_parameter_is_an_array_of_strings():
    schema = next(s for s in tool_schemas() if s["function"]["name"] == "storage_set_policy")
    perms = schema["function"]["parameters"]["properties"]["perms"]
    assert perms == {"type": "array", "items": {"type": "string"}}


def test_descriptions_cover_exactly_the_surface():
    """Adding a tool without describing it fails here rather than shipping an
    undescribed schema to the victim."""
    assert set(DESCRIPTIONS) == set(model_facing_tools())
    assert all(DESCRIPTIONS[t].strip() for t in model_facing_tools())


def test_every_schema_is_wellformed_openai_shape():
    for schema in tool_schemas():
        assert schema["type"] == "function"
        fn = schema["function"]
        assert set(fn) == {"name", "description", "parameters"}
        assert fn["parameters"]["type"] == "object"


# -- argument validation ----------------------------------------------------


def test_valid_arguments_bind():
    assert validate_arguments("storage.copy_object",
                              {"src_object": "o", "dst_bucket": "b"}) is None


def test_missing_required_argument_is_reported():
    reason = validate_arguments("storage.copy_object", {"src_object": "o"})
    assert reason is not None and "dst_bucket" in reason


def test_unknown_argument_is_reported():
    reason = validate_arguments("storage.copy_object",
                                {"src_object": "o", "dst_bucket": "b", "extra": 1})
    assert reason is not None and "extra" in reason


def test_omitting_a_defaulted_argument_is_fine():
    assert validate_arguments("inventory.list_hosts", {}) is None
    assert validate_arguments("ticket.close", {"ticket": "T1"}) is None


@pytest.mark.parametrize("tool", sorted(set(TOOL_SURFACE) - NON_MODEL_FACING_TOOLS))
def test_every_tool_has_a_schema_the_store_can_receive(tool):
    """Round-trip the whole surface: schema required-args satisfy the store."""
    schema = next(s for s in tool_schemas() if s["function"]["name"] == wire_name(tool))
    args = {name: _sample(prop) for name, prop
            in schema["function"]["parameters"]["properties"].items()
            if name in schema["function"]["parameters"]["required"]}
    assert validate_arguments(tool, args) is None


def _sample(prop):
    return {"string": "x", "integer": 1, "number": 1.0,
            "boolean": True, "array": ["x"]}[prop["type"]]
