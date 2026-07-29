"""Taxonomy-sync CI guard.

Enforces — at the *definition* level, not just the identifier level —
that every shipped detector stays in sync with the SASTER taxonomy:

1. Each detector's declared numeric identifier exists in the taxonomy.
2. Each detector's ``pattern_name`` matches the taxonomy name for that
   number (ignoring a trailing parenthetical qualifier such as ``(EFT)``
   on the taxonomy side or ``(Induced)`` / ``(Multi-Turn)`` on the
   detector side).
3. Each detector's declared ``tier`` matches the taxonomy tier.
4. The verbatim "Canonical definition (from SASTER.md)" block in each
   detector's module docstring matches the taxonomy body for that number
   (whitespace-normalized). Every shipped detector must carry the block.
5. The "N detectors covering M SASTER patterns" count in README.md
   matches the shipped detector count and the number of distinct
   patterns those detectors cover.

The taxonomy is vendored (`tests/data/SASTER.md`) and pinned by checksum
so the guard runs hermetically. See `tests/data/README.md` for the
refresh procedure. This is the guard that keeps the SASTER-13/-15
mislabel class of bug (a detector filed under the wrong pattern number,
or quoting the wrong / no definition) from recurring silently.
"""

from __future__ import annotations

import hashlib
import importlib
import re
from pathlib import Path

import pytest

from saster_harness.harness import _DETECTOR_REGISTRY

_DATA = Path(__file__).parent / "data"
_README = Path(__file__).parent.parent / "README.md"

# Unique detector modules behind the registry (shortcuts like -both/-all
# expand to these; dedupe to the 13 shipped implementations).
_DETECTOR_MODULES = sorted(
    {mod for paths in _DETECTOR_REGISTRY.values() for mod in paths}
)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _base_name(name: str) -> str:
    """Drop a single trailing parenthetical qualifier and normalize."""
    return _norm(re.sub(r"\s*\([^)]*\)\s*$", "", name))


def _parse_taxonomy(md: str) -> dict[int, dict]:
    patterns: dict[int, dict] = {}
    tier: int | None = None
    cur: int | None = None
    for line in md.splitlines():
        tm = re.match(r"^##\s+Tier\s+(\d+)", line)
        if tm:
            tier = int(tm.group(1))
            cur = None
            continue
        if re.match(r"^##\s", line):  # a non-Tier section (e.g. Reserved)
            cur = None
            continue
        hm = re.match(r"^###\s+SASTER-(\d+):\s+(.*)$", line)
        if hm:
            cur = int(hm.group(1))
            patterns[cur] = {
                "name": hm.group(2).strip(),
                "tier": tier,
                "fields": {},
            }
            continue
        if cur is not None:
            fm = re.match(r"^\*\*(Attack|Detection|Example):\*\*\s*(.*)$", line)
            if fm:
                patterns[cur]["fields"][fm.group(1).lower()] = _norm(fm.group(2))
    return patterns


def _parse_canonical_block(docstring: str | None) -> dict[str, str] | None:
    """Extract Attack/Detection/Example from a detector's quoted block."""
    if not docstring:
        return None
    marker = re.search(
        r"Canonical [^\n]*definition \(from SASTER\.md\):\n(.*)",
        docstring,
        re.DOTALL,
    )
    if not marker:
        return None
    # The block runs while lines stay blank or indented; the first
    # column-0 prose line ends it.
    block_lines: list[str] = []
    for line in marker.group(1).splitlines():
        if line.strip() == "":
            block_lines.append(line)
            continue
        if not line.startswith("    "):
            break
        block_lines.append(line)

    # Any "Label:" line (Attack:, Detection:, Example:, Subtypes:,
    # Prior art:, Notes: …) starts a new field, so a supplementary
    # field like Subtypes terminates the preceding one rather than
    # bleeding into it.
    fields: dict[str, list[str]] = {}
    current: str | None = None
    for line in block_lines:
        stripped = line.strip()
        label = re.match(r"^([A-Za-z][A-Za-z ]*):$", stripped)
        if label:
            current = label.group(1).strip().lower()
            fields[current] = []
        elif current is not None and stripped:
            fields[current].append(stripped)
    return {k: _norm(" ".join(v)) for k, v in fields.items()}


def _load_detectors() -> list[tuple[str, object, str | None]]:
    out = []
    for mod_name in _DETECTOR_MODULES:
        mod = importlib.import_module(mod_name)
        detector = mod.DETECTOR
        out.append((mod_name, detector, mod.__doc__))
    return out


TAXONOMY = _parse_taxonomy((_DATA / "SASTER.md").read_text(encoding="utf-8"))
DETECTORS = _load_detectors()


def test_vendored_taxonomy_matches_pinned_checksum():
    data = (_DATA / "SASTER.md").read_bytes()
    expected = (_DATA / "SASTER.md.sha256").read_text().strip()
    assert hashlib.sha256(data).hexdigest() == expected, (
        "Vendored tests/data/SASTER.md does not match its pinned checksum. "
        "If this was an intentional refresh, re-pin per tests/data/README.md."
    )


def test_taxonomy_has_32_patterns_with_32_reserved():
    numbers = set(TAXONOMY)
    assert len(numbers) == 32
    assert numbers == set(range(1, 32)) | {33}
    assert 32 not in numbers  # SASTER-32 is reserved, not defined


@pytest.mark.parametrize("mod_name,detector,doc", DETECTORS, ids=[d[0] for d in DETECTORS])
def test_detector_identifier_exists_in_taxonomy(mod_name, detector, doc):
    num = int(re.search(r"SASTER-(\d+)", detector.saster_id).group(1))
    assert num in TAXONOMY, (
        f"{detector.saster_id} declares SASTER-{num}, absent from the taxonomy"
    )


@pytest.mark.parametrize("mod_name,detector,doc", DETECTORS, ids=[d[0] for d in DETECTORS])
def test_detector_name_matches_taxonomy(mod_name, detector, doc):
    num = int(re.search(r"SASTER-(\d+)", detector.saster_id).group(1))
    assert _base_name(detector.pattern_name) == _base_name(TAXONOMY[num]["name"]), (
        f"{detector.saster_id} pattern_name={detector.pattern_name!r} does not "
        f"match SASTER-{num} name {TAXONOMY[num]['name']!r}"
    )


@pytest.mark.parametrize("mod_name,detector,doc", DETECTORS, ids=[d[0] for d in DETECTORS])
def test_detector_tier_matches_taxonomy(mod_name, detector, doc):
    num = int(re.search(r"SASTER-(\d+)", detector.saster_id).group(1))
    assert detector.tier == TAXONOMY[num]["tier"], (
        f"{detector.saster_id} tier={detector.tier} != SASTER-{num} "
        f"tier {TAXONOMY[num]['tier']}"
    )


@pytest.mark.parametrize("mod_name,detector,doc", DETECTORS, ids=[d[0] for d in DETECTORS])
def test_detector_quotes_canonical_definition_verbatim(mod_name, detector, doc):
    num = int(re.search(r"SASTER-(\d+)", detector.saster_id).group(1))
    quoted = _parse_canonical_block(doc)
    assert quoted, (
        f"{mod_name} has no 'Canonical definition (from SASTER.md)' block — "
        f"the README claims every detector quotes its definition verbatim"
    )
    assert "attack" in quoted and "detection" in quoted, (
        f"{mod_name} canonical block missing Attack/Detection"
    )
    # Enforce verbatim match on the core definition fields. Supplementary
    # fields (Subtypes / Notes / Prior art) may be condensed in the
    # detector docstring and are not required to be verbatim.
    taxo = TAXONOMY[num]["fields"]
    for field in ("attack", "detection", "example"):
        if field not in quoted:
            continue
        assert quoted[field] == taxo.get(field), (
            f"{mod_name} {field.title()} block does not match SASTER-{num}:\n"
            f"  detector:  {quoted[field]!r}\n"
            f"  taxonomy:  {taxo.get(field)!r}"
        )


def test_readme_counts_match_shipped_detectors():
    readme = _README.read_text(encoding="utf-8")
    m = re.search(r"(\d+)\s+detectors covering\s+(\d+)\s+SASTER patterns", readme)
    assert m, "README missing an 'N detectors covering M SASTER patterns' claim"
    stated_detectors, stated_patterns = int(m.group(1)), int(m.group(2))

    covered = {
        int(re.search(r"SASTER-(\d+)", det.saster_id).group(1))
        for _, det, _ in DETECTORS
    }
    assert stated_detectors == len(DETECTORS), (
        f"README says {stated_detectors} detectors; {len(DETECTORS)} ship"
    )
    assert stated_patterns == len(covered), (
        f"README says {stated_patterns} patterns; detectors cover {len(covered)}: "
        f"{sorted(covered)}"
    )
