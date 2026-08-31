"""The frozen label vocabularies must match AgentDoG's own taxonomy file.

The three vocabularies in ``carl_ops_trajectory.schema`` are not this project's
categories — they are AgentDoG's, and P10 is an accuracy measured against them.
If the vendored taxonomy is ever refreshed from upstream and a leaf is renamed,
added or dropped, the frozen contract must be amended deliberately rather than
drifting: every label already recorded in a public corpus would otherwise be
silently redefined.

So this test does not restate the vocabulary. It PARSES the vendored file and
asserts the frozen tuples are exactly what it contains, in order.
"""
from __future__ import annotations

import re

from carl_ops_trajectory.schema import (
    AGENTDOG_FAILURE_MODES,
    AGENTDOG_REAL_WORLD_HARMS,
    AGENTDOG_RISK_SOURCES,
)
from saster_defense.agentdog import (
    TRAJECTORY_FINEGRAINED_PATH,
    fine_grained_prompt,
    is_fine_grained_checkpoint,
    taxonomy_text,
)

#: A leaf line: a dotted number, then the category name. Section headers use
#: "=====" rules and group headers use "-----", so neither matches.
_LEAF = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+(.*\S)\s*$")

_SECTIONS = ("Risk Source", "Failure Mode", "Real World Harm")


def _parse_sections() -> dict[str, list[str]]:
    """Leaf category names per section, in file order."""
    out: dict[str, list[str]] = {name: [] for name in _SECTIONS}
    current: str | None = None
    lines = taxonomy_text().splitlines()
    for i, raw in enumerate(lines):
        line = raw.strip()
        if line in _SECTIONS and i and set(lines[i - 1].strip()) == {"="}:
            current = line
            continue
        if current is None or not line or set(line) <= {"=", "-"}:
            continue
        m = _LEAF.match(line)
        if not m:
            continue
        number, name = m.groups()
        # Under Risk Source and Failure Mode the bare "1." / "2." lines are
        # GROUP headers with their own prose beneath; leaves are the dotted
        # ones. Real World Harm is flat, so its leaves are the bare numbers.
        if current == "Real World Harm" or "." in number:
            out[current].append(name)
    return out


def test_the_frozen_vocabularies_are_the_vendored_taxonomy() -> None:
    parsed = _parse_sections()
    assert tuple(parsed["Risk Source"]) == AGENTDOG_RISK_SOURCES
    assert tuple(parsed["Failure Mode"]) == AGENTDOG_FAILURE_MODES
    assert tuple(parsed["Real World Harm"]) == AGENTDOG_REAL_WORLD_HARMS


def test_the_taxonomy_has_the_shape_the_published_numbers_describe() -> None:
    """Three dimensions, which is what AgentDoG reports accuracy along."""
    parsed = _parse_sections()
    assert len(parsed["Risk Source"]) == 8
    assert len(parsed["Failure Mode"]) == 14
    assert len(parsed["Real World Harm"]) == 10


def test_the_prompt_template_is_upstreams_and_is_filled_not_paraphrased() -> None:
    template = TRAJECTORY_FINEGRAINED_PATH.read_text(encoding="utf-8")
    assert "{taxonomy}" in template and "{trajectory}" in template
    prompt = fine_grained_prompt('{"step": 0, "tool": "storage.copy_object"}')
    # both placeholders substituted, nothing left dangling
    assert "{taxonomy}" not in prompt and "{trajectory}" not in prompt
    # the taxonomy really is inlined, so the model sees the label set
    for label in AGENTDOG_FAILURE_MODES:
        assert label in prompt
    # a trajectory full of JSON braces survives substitution
    assert '"tool": "storage.copy_object"' in prompt


def test_the_binary_checkpoint_is_not_a_fine_grained_one() -> None:
    """AgentDoG 1.0 ships the two heads as separate checkpoints, and the
    published fine-grained accuracies are the FG one's. A run must be able to
    say which answered."""
    assert not is_fine_grained_checkpoint("AI45Research/AgentDoG-Qwen3-4B")
    assert is_fine_grained_checkpoint("AI45Research/AgentDoG-FG-Qwen3-4B")
