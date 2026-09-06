"""Tests for the stdlib SVG renderers over a synthetic, schema-valid corpus."""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import pytest

from carl_ops_trajectory import validate_record
from saster_harness.charts import MAX_WIDTH, render_marker_timeline, render_verdict_grid
from tests.fixtures.synthetic_corpus import (
    CAMPAIGNS,
    DEFENSE_CONFIG_KEYS,
    K_TRIALS,
    all_null_markers_record,
    synthetic_corpus,
)

SVG_NS = "{http://www.w3.org/2000/svg}"
_LATENCY_NUMBER = re.compile(r"latency = -?\d+")


@pytest.fixture(scope="module")
def corpus() -> list[tuple[dict, dict]]:
    return synthetic_corpus(seed=0)


def _parse(svg: str) -> ET.Element:
    root = ET.fromstring(svg)
    assert root.tag == f"{SVG_NS}svg"
    assert float(root.get("width")) <= MAX_WIDTH
    return root


def _pick(corpus, **want) -> dict:
    for rec, _meta in corpus:
        breach = rec["oracle"]["breach"]
        censored = rec["containment_latency"]["censored"]
        detected = rec["markers"]["first_detection_step"] is not None
        if (breach, censored, detected) == (
            want["breach"], want["censored"], want["detected"]
        ):
            return rec
    raise AssertionError(f"corpus has no record shaped {want}")


# -- the corpus itself ----------------------------------------------------------


def test_every_synthetic_record_validates(corpus) -> None:
    assert len(corpus) == len(CAMPAIGNS) * len(DEFENSE_CONFIG_KEYS) * K_TRIALS
    for rec, meta in corpus:
        assert validate_record(rec) == [], (meta, validate_record(rec))
        assert rec["saster_category"] == "SASTER-31"
        assert set(rec["markers"]["units"].values()) == {"action_index"}
        assert meta["defense_config_key"] in DEFENSE_CONFIG_KEYS
        assert "defense_config_key" not in rec["config_hashes"]


def test_corpus_covers_the_shapes_the_renderers_branch_on(corpus) -> None:
    _pick(corpus, breach=True, censored=False, detected=True)
    _pick(corpus, breach=True, censored=True, detected=False)
    _pick(corpus, breach=False, censored=False, detected=True)
    assert any(
        d["status"] == "unavailable"
        for rec, _ in corpus for d in rec["detection"]
    )
    assert any(
        rec["containment_latency"].get("detected_at_breach") is True for rec, _ in corpus
    )


def test_corpus_is_deterministic() -> None:
    assert synthetic_corpus(seed=3) == synthetic_corpus(seed=3)
    assert synthetic_corpus(seed=3) != synthetic_corpus(seed=4)


def test_all_null_markers_record_validates() -> None:
    rec = all_null_markers_record()
    assert validate_record(rec) == []
    assert all(
        rec["markers"][k] is None
        for k in ("onset_dist", "explanatory_divergence", "point_of_no_return",
                  "breach_step_index", "first_detection_step")
    )


# -- verdict grid -------------------------------------------------------------


def test_verdict_grid_renders_one_row_per_campaign(corpus, tmp_path) -> None:
    path = tmp_path / "grid.svg"
    svg = render_verdict_grid(corpus, path)
    assert path.read_text(encoding="utf-8") == svg
    root = _parse(svg)
    rows = [g for g in root.iter(f"{SVG_NS}g") if g.get("class") == "row"]
    assert len(rows) == len(CAMPAIGNS) * len(DEFENSE_CONFIG_KEYS)
    assert {(r.get("data-config"), r.get("data-campaign")) for r in rows} == {
        (cfg, c[0]) for cfg in DEFENSE_CONFIG_KEYS for c in CAMPAIGNS
    }
    groups = [g for g in root.iter(f"{SVG_NS}g") if g.get("class") == "group"]
    assert "vendor-shaped" in {g.get("data-config") for g in groups}
    assert len(groups) == len(DEFENSE_CONFIG_KEYS)


def test_verdict_grid_cells_carry_every_verdict_and_a_breach_column(corpus) -> None:
    root = _parse(render_verdict_grid(corpus, None))
    cells = [r for r in root.iter(f"{SVG_NS}rect") if r.get("class") == "cell"]
    verdicts = {c.get("data-verdict") for c in cells}
    assert verdicts == {"finding", "unavailable", "clean", "off"}
    layers = {c.get("data-layer") for c in cells}
    assert layers == {"l2_policy", "l3_trace", "l4_auditor", "l5_approval", "scope_lock", "judge"}
    breach_texts = [t for t in root.iter(f"{SVG_NS}text") if t.get("class") == "breach"]
    assert len(breach_texts) == len(CAMPAIGNS) * len(DEFENSE_CONFIG_KEYS)
    for t in breach_texts:
        assert t.text == f"{t.get('data-k')}/{t.get('data-n')}"
        assert int(t.get("data-n")) == K_TRIALS
    # the control campaign never breaches; the undefended induced one always does
    by_row = {
        (g.get("data-config"), g.get("data-campaign")): g
        for g in root.iter(f"{SVG_NS}g") if g.get("class") == "row"
    }
    for cfg in DEFENSE_CONFIG_KEYS:
        row = by_row[(cfg, "carl-ops-control")]
        assert row.find(f"{SVG_NS}text[@class='breach']").get("data-k") == "0"
    row = by_row[("none", "carl-ops-induced")]
    assert row.find(f"{SVG_NS}text[@class='breach']").get("data-k") == str(K_TRIALS)
    # an undefended row has no layers at all: every cell is off
    for cell in by_row[("none", "carl-ops-induced")].iter(f"{SVG_NS}rect"):
        assert cell.get("data-verdict") == "off"


def test_verdict_grid_has_a_legend(corpus) -> None:
    svg = render_verdict_grid(corpus, None)
    for verdict in ("finding", "unavailable", "clean", "off"):
        assert f">{verdict}</text>" in svg


# -- marker timeline ----------------------------------------------------------


def test_timeline_detected_breach_draws_a_bracket_with_the_number(corpus, tmp_path) -> None:
    rec = _pick(corpus, breach=True, censored=False, detected=True)
    path = tmp_path / "timeline.svg"
    svg = render_marker_timeline(rec, path)
    assert path.read_text(encoding="utf-8") == svg
    root = _parse(svg)
    brackets = [p for p in root.iter(f"{SVG_NS}path") if p.get("class") == "latency"]
    assert len(brackets) == 1
    value = rec["containment_latency"]["value"]
    assert f"latency = {value}" in svg
    assert "right-censored" not in svg
    assert "action_index" in svg
    for act in rec["actions"]:
        assert f">{act['tool']}</text>" in svg


def test_timeline_censored_breach_never_shows_a_number(corpus) -> None:
    rec = _pick(corpus, breach=True, censored=True, detected=False)
    svg = render_marker_timeline(rec, None)
    root = _parse(svg)
    assert "right-censored" in svg
    assert not _LATENCY_NUMBER.search(svg)
    arrows = [p for p in root.iter(f"{SVG_NS}path") if p.get("class") == "latency censored"]
    assert len(arrows) == 1
    assert "first_detection_step: not localized" in svg


def test_timeline_clean_record_renders_without_a_bracket(corpus) -> None:
    rec = _pick(corpus, breach=False, censored=False, detected=True)
    svg = render_marker_timeline(rec, None)
    root = _parse(svg)
    assert not [p for p in root.iter(f"{SVG_NS}path") if (p.get("class") or "").startswith("latency")]
    assert "no breach" in svg
    assert "breach_step_index: not localized" in svg


def test_timeline_all_null_markers_renders() -> None:
    rec = all_null_markers_record()
    svg = render_marker_timeline(rec, None)
    root = _parse(svg)
    assert not [el for el in root.iter(f"{SVG_NS}line") if el.get("class") == "marker"]
    for name in ("onset_dist", "explanatory_divergence", "point_of_no_return",
                 "breach_step_index", "first_detection_step"):
        assert f"{name}: not localized" in svg
    assert not _LATENCY_NUMBER.search(svg)


def test_timeline_survives_a_bare_record() -> None:
    """No actions, no markers, no latency block: still a document."""
    svg = render_marker_timeline({"campaign_id": "x"}, None)
    _parse(svg)
    assert "no actions recorded" in svg


def test_timeline_draws_onset_bars_when_estimated(corpus) -> None:
    rec = next(r for r, _ in corpus if r["markers"]["onset_dist"] is not None)
    svg = render_marker_timeline(rec, None)
    root = _parse(svg)
    titles = [t.text for t in root.iter(f"{SVG_NS}title") if (t.text or "").startswith("onset p(")]
    assert len(titles) == len(rec["markers"]["onset_dist"]["steps"])


# -- determinism --------------------------------------------------------------


def test_renderers_are_deterministic(corpus) -> None:
    assert render_verdict_grid(corpus, None) == render_verdict_grid(synthetic_corpus(0), None)
    rec = _pick(corpus, breach=True, censored=False, detected=True)
    a = render_marker_timeline(rec, None).encode("utf-8")
    b = render_marker_timeline(rec, None).encode("utf-8")
    assert a == b


def test_every_synthetic_record_renders_as_xml(corpus) -> None:
    for rec, _ in corpus:
        _parse(render_marker_timeline(rec, None))
