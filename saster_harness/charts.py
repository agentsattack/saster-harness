"""Stdlib-only SVG renderers for the carl-ops trajectory corpus.

Two figures, no matplotlib:

- :func:`render_verdict_grid` — one row per (defense config, campaign), one
  column per detection layer present in the corpus, a cell per (row, layer)
  giving the layer's verdict aggregated over the campaign's k trials, and a
  trailing ``breach k/n`` column.
- :func:`render_marker_timeline` — one record's five markers on its
  action-index axis, with the containment latency drawn as a bracket
  between the breach and the first finding. A censored latency is drawn as
  an open-ended arrow labelled ``right-censored`` and is never given a
  number.

Both renderers are deterministic (same input, byte-identical output), emit
well-formed XML, stay at or under :data:`MAX_WIDTH` pixels wide, and never
raise on a record whose markers are all null.
"""
from __future__ import annotations

import os
from typing import Any
from xml.sax.saxutils import escape

MAX_WIDTH = 1400

# -- palette ------------------------------------------------------------------
# Status colours for the grid (fixed status palette; every cell also carries a
# text label, so colour never carries the verdict alone) and the first four
# categorical slots, in fixed order, for the timeline markers.
_SURFACE = "#fcfcfb"
_INK = "#0b0b0b"
_INK_2 = "#52514e"
_MUTED = "#898781"
_GRID = "#e1e0d9"
_AXIS = "#c3c2b7"

VERDICT_FILL = {
    "finding": "#d03b3b",
    "unavailable": "#fab219",
    "clean": "#0ca30c",
    "off": "#e1e0d9",
}
VERDICT_TEXT = {
    "finding": "#ffffff",
    "unavailable": "#0b0b0b",
    "clean": "#ffffff",
    "off": "#52514e",
}
VERDICT_ORDER = ("finding", "unavailable", "clean", "off")

MARKER_COLOR = {
    "point_of_no_return": "#2a78d6",
    "breach_step_index": "#eb6834",
    "first_detection_step": "#1baf7a",
    "explanatory_divergence": "#eda100",
}
_ONSET_FILL = "#86b6ef"

#: Canonical column order for known layers; unknown layers follow, sorted.
LAYER_ORDER = ("l2_policy", "l3_trace", "l4_auditor", "l5_approval", "scope_lock", "judge")
#: Canonical row-group order for known defense configs; unknown keys follow.
CONFIG_ORDER = ("none", "l2", "l3", "l4", "l3+l4", "all", "vendor-shaped")

_FONT = "font-family=\"system-ui, -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif\""


def _rank(value: str, order: tuple[str, ...]) -> tuple[int, str]:
    return (order.index(value), value) if value in order else (len(order), value)


def _is_finding(d: dict) -> bool:
    """Mirror of the schema's finding rule: an unavailable layer never is,
    an explicit flag is authoritative, otherwise warn/block are and escalate
    is routing."""
    if d.get("status", "ok") == "unavailable" or d.get("action_taken") is None:
        return False
    explicit = d.get("finding")
    if isinstance(explicit, bool):
        return explicit
    return d.get("action_taken") in ("warn", "block")


def _text(x: float, y: float, s: str, *, size: int = 12, fill: str = _INK,
          anchor: str = "start", weight: str = "normal", extra: str = "") -> str:
    return (
        f'<text x="{x:g}" y="{y:g}" font-size="{size}" fill="{fill}" '
        f'text-anchor="{anchor}" font-weight="{weight}" {_FONT}{extra}>{escape(s)}</text>'
    )


def _write(svg: str, path: str | os.PathLike[str] | None) -> str:
    if path is not None:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(svg)
    return svg


def _svg_open(width: float, height: float) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:g}" height="{height:g}" '
        f'viewBox="0 0 {width:g} {height:g}" role="img">'
        f'<rect x="0" y="0" width="{width:g}" height="{height:g}" fill="{_SURFACE}"/>'
    )


# -- verdict grid -------------------------------------------------------------


def _layer_verdict(entries: list[dict]) -> str:
    if not entries:
        return "off"
    if any(_is_finding(d) for d in entries):
        return "finding"
    if any(d.get("status") == "unavailable" for d in entries):
        return "unavailable"
    return "clean"


def _grid_rows(records_with_meta: list[tuple[dict, dict]]) -> tuple[list[dict], list[str]]:
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    layers_seen: set[str] = set()
    for rec, meta in records_with_meta:
        cfg = str(meta.get("defense_config_key", "?"))
        campaign = str(rec.get("campaign_id", "?"))
        row = groups.setdefault(
            (cfg, campaign),
            {"config": cfg, "campaign": campaign, "n": 0, "breaches": 0, "by_layer": {}},
        )
        row["n"] += 1
        oracle = rec.get("oracle") or {}
        if oracle.get("breach") is True:
            row["breaches"] += 1
        for d in rec.get("detection") or []:
            if not isinstance(d, dict):
                continue
            layer = str(d.get("layer", "?"))
            layers_seen.add(layer)
            row["by_layer"].setdefault(layer, []).append(d)
    rows = sorted(
        groups.values(),
        key=lambda r: (_rank(r["config"], CONFIG_ORDER), r["campaign"]),
    )
    layers = sorted(layers_seen, key=lambda layer: _rank(layer, LAYER_ORDER))
    return rows, layers


def render_verdict_grid(
    records_with_meta: list[tuple[dict, dict]], path: str | os.PathLike[str] | None
) -> str:
    """Per-campaign, per-layer verdict grid. Returns the SVG and writes it to
    ``path`` when one is given."""
    rows, layers = _grid_rows(list(records_with_meta))
    label_w = 300
    margin = 20
    header_h = 64
    row_h = 30
    group_h = 24
    legend_h = 44
    n_cols = len(layers) + 1  # + breach column
    cell_w = min(120, int((MAX_WIDTH - label_w - 2 * margin) / max(n_cols, 1)))
    width = label_w + n_cols * cell_w + 2 * margin
    n_groups = len({r["config"] for r in rows})
    height = margin + header_h + n_groups * group_h + len(rows) * row_h + legend_h + margin

    out = [_svg_open(width, height)]
    out.append(_text(margin, margin + 18, "Per-layer verdict by campaign", size=15, weight="bold"))
    out.append(_text(
        margin, margin + 36,
        "rows: defense config / campaign; cell: verdict aggregated over k trials",
        size=11, fill=_INK_2,
    ))
    # column headers
    x0 = margin + label_w
    y_head = margin + header_h - 8
    for j, layer in enumerate(layers):
        out.append(_text(x0 + j * cell_w + cell_w / 2, y_head, layer, size=11,
                         fill=_INK_2, anchor="middle"))
    out.append(_text(x0 + len(layers) * cell_w + cell_w / 2, y_head, "breach k/n",
                     size=11, fill=_INK_2, anchor="middle"))

    y = margin + header_h
    current_group: str | None = None
    for row in rows:
        if row["config"] != current_group:
            current_group = row["config"]
            out.append(f'<g class="group" data-config="{escape(current_group, {chr(34): "&quot;"})}">')
            out.append(f'<line x1="{margin}" y1="{y + 2:g}" x2="{width - margin}" '
                       f'y2="{y + 2:g}" stroke="{_GRID}" stroke-width="1"/>')
            out.append(_text(margin, y + 17, f"config: {current_group}", size=12,
                             weight="bold", fill=_INK))
            out.append("</g>")
            y += group_h
        attrs = (
            f'data-config="{escape(row["config"], {chr(34): "&quot;"})}" '
            f'data-campaign="{escape(row["campaign"], {chr(34): "&quot;"})}"'
        )
        out.append(f'<g class="row" {attrs}>')
        out.append(_text(margin + 12, y + row_h / 2 + 4, row["campaign"], size=12))
        for j, layer in enumerate(layers):
            verdict = _layer_verdict(row["by_layer"].get(layer, []))
            cx = x0 + j * cell_w
            out.append(
                f'<rect class="cell" data-layer="{escape(layer)}" data-verdict="{verdict}" '
                f'x="{cx + 1:g}" y="{y + 2:g}" width="{cell_w - 2:g}" height="{row_h - 4:g}" '
                f'rx="4" fill="{VERDICT_FILL[verdict]}">'
                f"<title>{escape(row['campaign'])} / {escape(layer)}: {verdict}</title></rect>"
            )
            out.append(_text(cx + cell_w / 2, y + row_h / 2 + 4, verdict, size=11,
                             fill=VERDICT_TEXT[verdict], anchor="middle"))
        cx = x0 + len(layers) * cell_w
        k, n = row["breaches"], row["n"]
        out.append(_text(cx + cell_w / 2, y + row_h / 2 + 4, f"{k}/{n}", size=12,
                         anchor="middle", weight="bold" if k else "normal",
                         extra=f' class="breach" data-k="{k}" data-n="{n}"'))
        out.append("</g>")
        y += row_h

    # legend
    ly = y + 20
    lx = margin
    out.append(_text(lx, ly + 4, "verdict:", size=11, fill=_INK_2))
    lx += 60
    for verdict in VERDICT_ORDER:
        out.append(f'<rect x="{lx}" y="{ly - 8}" width="14" height="14" rx="3" '
                   f'fill="{VERDICT_FILL[verdict]}"/>')
        out.append(_text(lx + 20, ly + 4, verdict, size=11, fill=_INK_2))
        lx += 110
    out.append(_text(width - margin, ly + 4,
                     "finding > unavailable > clean; off = layer absent",
                     size=10, fill=_MUTED, anchor="end"))
    out.append("</svg>")
    return _write("".join(out), path)


# -- marker timeline ----------------------------------------------------------


def _as_index(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def render_marker_timeline(record: dict, path: str | os.PathLike[str] | None) -> str:
    """One record's five-marker timeline on its action-index axis. Returns the
    SVG and writes it to ``path`` when one is given."""
    actions = record.get("actions") or []
    if not isinstance(actions, list):
        actions = []
    markers = record.get("markers") or {}
    if not isinstance(markers, dict):
        markers = {}
    latency = record.get("containment_latency") or {}
    if not isinstance(latency, dict):
        latency = {}

    ponr = _as_index(markers.get("point_of_no_return"))
    bsi = _as_index(markers.get("breach_step_index"))
    fds = _as_index(markers.get("first_detection_step"))
    ed = _as_index(markers.get("explanatory_divergence"))
    onset = markers.get("onset_dist") if isinstance(markers.get("onset_dist"), dict) else None
    onset_steps = [s for s in (onset or {}).get("steps", []) if _as_index(s) is not None]
    onset_probs = list((onset or {}).get("probs", []))
    if len(onset_probs) != len(onset_steps):
        onset_steps, onset_probs = [], []

    units_block = markers.get("units") if isinstance(markers.get("units"), dict) else {}
    unit_values = sorted({str(u) for u in units_block.values()})
    if unit_values:
        units_label = " / ".join(unit_values)
    else:
        units_label = f"{markers.get('index_space', 'action')}_index"

    n = len(actions)
    last = max([n - 1] + [v for v in (ponr, bsi, fds, ed) if v is not None] + onset_steps)
    last = max(last, 0)

    margin = 20
    left = 70
    note_w = 300
    tick_gap = min(100, int((MAX_WIDTH - left - note_w - 3 * margin) / max(last, 1)))
    plot_w = max(last, 1) * tick_gap
    width = left + plot_w + note_w + 3 * margin
    onset_h = 60
    axis_y = margin + 40 + onset_h + 4 * 26 + 40
    height = axis_y + 70 + margin

    def x_of(i: int) -> float:
        return left + margin + i * tick_gap

    out = [_svg_open(width, height)]
    title = f"{record.get('campaign_id', '?')} / trial {record.get('trial_index', '?')}"
    out.append(_text(margin, margin + 16, f"Marker timeline: {title}", size=15, weight="bold"))
    out.append(_text(margin, margin + 34, f"units: {units_label}", size=11, fill=_INK_2,
                     extra=' class="units"'))

    # axis + ticks
    out.append(f'<line x1="{x_of(0):g}" y1="{axis_y}" x2="{x_of(last):g}" y2="{axis_y}" '
               f'stroke="{_AXIS}" stroke-width="2"/>')
    for i in range(last + 1):
        x = x_of(i)
        out.append(f'<line x1="{x:g}" y1="{axis_y}" x2="{x:g}" y2="{axis_y + 6}" '
                   f'stroke="{_AXIS}" stroke-width="1"/>')
        if i < n and isinstance(actions[i], dict):
            tool = str(actions[i].get("tool", f"a{i}"))
            fill = _INK_2
        else:
            tool, fill = f"a{i}", _MUTED
        out.append(_text(x, axis_y + 20, str(i), size=11, fill=_INK_2, anchor="middle"))
        out.append(_text(x, axis_y + 34, tool, size=9, fill=fill, anchor="middle",
                         extra=f' transform="rotate(-20 {x:g} {axis_y + 34})"'))
    out.append(_text(x_of(last) + 8, axis_y + 4, units_label, size=10, fill=_MUTED))
    if n == 0:
        out.append(_text(x_of(0), axis_y - 8, "no actions recorded", size=11, fill=_MUTED))

    # onset distribution (small bar chart above the lanes)
    onset_top = margin + 48
    onset_base = onset_top + onset_h
    if onset_steps:
        out.append(_text(margin, onset_top + 10, "onset_dist", size=10, fill=_INK_2))
        bar_w = max(6, min(tick_gap - 4, 24))
        for s, p in zip(onset_steps, onset_probs, strict=True):
            try:
                pf = max(0.0, min(1.0, float(p)))
            except (TypeError, ValueError):
                pf = 0.0
            h = pf * (onset_h - 14)
            x = x_of(s) - bar_w / 2
            out.append(f'<rect x="{x:g}" y="{onset_base - h:g}" width="{bar_w}" height="{h:g}" '
                       f'rx="2" fill="{_ONSET_FILL}"><title>onset p({s}) = {pf:.3f}</title></rect>')
            out.append(_text(x_of(s), onset_base - h - 3, f"{pf:.2f}", size=9, fill=_INK_2,
                             anchor="middle"))
        out.append(f'<line x1="{x_of(0):g}" y1="{onset_base}" x2="{x_of(last):g}" '
                   f'y2="{onset_base}" stroke="{_GRID}" stroke-width="1"/>')

    # marker lanes
    lane_top = onset_base + 16
    lanes = (
        ("point_of_no_return", ponr),
        ("breach_step_index", bsi),
        ("first_detection_step", fds),
        ("explanatory_divergence", ed),
    )
    not_localized: list[str] = []
    for k, (name, value) in enumerate(lanes):
        ly = lane_top + k * 26
        color = MARKER_COLOR[name]
        if value is None:
            not_localized.append(name)
            continue
        x = x_of(value)
        out.append(f'<line class="marker" data-marker="{name}" x1="{x:g}" y1="{ly}" '
                   f'x2="{x:g}" y2="{axis_y}" stroke="{color}" stroke-width="2" '
                   f'stroke-dasharray="4 3"/>')
        out.append(f'<circle cx="{x:g}" cy="{ly}" r="5" fill="{color}" stroke="{_SURFACE}" '
                   f'stroke-width="2"><title>{name} = {value}</title></circle>')
        # Late-index labels flip to the left so they never run into the note.
        if value > last / 2:
            out.append(_text(x - 9, ly + 4, f"{name} = {value}", size=11, fill=_INK,
                             anchor="end"))
        else:
            out.append(_text(x + 9, ly + 4, f"{name} = {value}", size=11, fill=_INK))
    if onset is None:
        not_localized.append("onset_dist")

    # containment latency bracket
    bracket_y = axis_y - 14
    censored = latency.get("censored") is True
    if bsi is not None and fds is not None and not censored:
        value = latency.get("value")
        if _as_index(value) is None:
            value = fds - bsi
        xa, xb = x_of(bsi), x_of(fds)
        lo, hi = min(xa, xb), max(xa, xb)
        if lo == hi:
            # latency 0: the same action. Give the bracket a visible span so
            # it reads as "detected here", not as a stray tick.
            lo, hi = lo - 6, hi + 6
        out.append(f'<path class="latency" d="M {lo:g} {bracket_y + 6} V {bracket_y} '
                   f'H {hi:g} V {bracket_y + 6}" fill="none" stroke="{_INK}" stroke-width="2"/>')
        out.append(_text((lo + hi) / 2, bracket_y - 5, f"latency = {value}", size=11,
                         weight="bold", anchor="middle", extra=' class="latency-label"'))
    elif bsi is not None:
        xa = x_of(bsi)
        xe = x_of(last) + 30
        out.append(f'<path class="latency censored" d="M {xa:g} {bracket_y + 6} V {bracket_y} '
                   f'H {xe:g}" fill="none" stroke="{_INK}" stroke-width="2"/>')
        out.append(f'<path d="M {xe:g} {bracket_y - 5} L {xe + 8:g} {bracket_y} '
                   f'L {xe:g} {bracket_y + 5} Z" fill="{_INK}"/>')
        out.append(_text((xa + xe) / 2, bracket_y - 5, "latency right-censored (undetected)",
                         size=11, weight="bold", anchor="middle",
                         extra=' class="latency-label"'))

    # side note
    nx = left + plot_w + 2 * margin + 40
    ny = margin + 48
    out.append(f'<g class="note" transform="translate({nx} {ny})">')
    out.append(_text(0, 10, "markers", size=11, weight="bold", fill=_INK_2))
    line = 28
    for name, _ in lanes:
        color = MARKER_COLOR[name]
        out.append(f'<rect x="0" y="{line - 9}" width="10" height="10" rx="2" fill="{color}"/>')
        out.append(_text(16, line, name, size=10, fill=_INK_2))
        line += 15
    out.append(f'<rect x="0" y="{line - 9}" width="10" height="10" rx="2" fill="{_ONSET_FILL}"/>')
    out.append(_text(16, line, f"onset_dist ({markers.get('onset_status', 'status unknown')})",
                     size=10, fill=_INK_2))
    line += 22
    if not_localized:
        out.append(_text(0, line, "not localized:", size=10, fill=_MUTED, weight="bold"))
        line += 14
        for name in not_localized:
            out.append(_text(8, line, f"{name}: not localized", size=10, fill=_MUTED))
            line += 14
    line += 6
    breach_flag = (record.get("oracle") or {}).get("breach")
    if breach_flag is True and censored:
        lat_note = "containment: right-censored"
    elif breach_flag is True and bsi is not None and fds is not None:
        lat_note = "containment: detected (bracket)"
    elif breach_flag is False:
        lat_note = "containment: no breach; latency undefined"
    else:
        lat_note = "containment: not recorded"
    out.append(_text(0, line, lat_note, size=10, fill=_INK_2))
    out.append("</g>")

    out.append("</svg>")
    return _write("".join(out), path)
