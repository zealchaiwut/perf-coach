"""Inline-SVG radar renderer (revamp P4-6) — the one component behind both radars.

Pure function of the radar payload: same payload -> same SVG at either size.

- Axes sit at fixed angles (P4-1 order, clockwise from top); a never-measured axis
  is omitted from the polygon, which closes over the remaining axes.
- Rings at 25 / 50 / 75 (plus the 100 outer edge).
- Stale axes draw hollow dashed points; the focus axis gets the amber point and label.
- A dashed outline shows the 28-days-ago polygon.
- ``<title>``/``<desc>`` carry the accessible summary sentence.
"""
from __future__ import annotations

import math
from html import escape
from typing import Any, Optional

from backend.services.radar_payload import fmt_score

CX, CY, R = 220.0, 210.0, 160.0
VIEWBOX = "-100 -6 640 432"
RINGS = (25, 50, 75, 100)
LABEL_GAP = 28.0

COLOR_INK = "#0b1530"
COLOR_MUTED = "#56627f"
COLOR_BLUE = "#1f3b8a"
COLOR_AMBER = "#b45309"
COLOR_AMBER_INK = "#7a3a10"


def _pt(index: int, count: int, radius: float) -> tuple[float, float]:
    ang = -math.pi / 2 + 2 * math.pi * index / count
    return CX + radius * math.cos(ang), CY + radius * math.sin(ang)


def _fmt(v: float) -> str:
    return f"{v:.1f}".rstrip("0").rstrip(".") if "." in f"{v:.1f}" else f"{v:.1f}"


def _points(pts: list[tuple[float, float]]) -> str:
    return " ".join(f"{_fmt(x)},{_fmt(y)}" for x, y in pts)


def _polygon(axes: list[dict[str, Any]], key: str) -> list[tuple[float, float]]:
    n = len(axes)
    return [
        _pt(i, n, R * max(0.0, min(100.0, float(a[key]))) / 100.0)
        for i, a in enumerate(axes)
        if a.get(key) is not None and not a["never_measured"]
    ]


def render_radar_svg(payload: dict[str, Any], size: str = "large") -> str:
    if size not in ("large", "small"):
        size = "large"
    axes: list[dict[str, Any]] = payload["axes"]
    n = len(axes)
    out: list[str] = []
    summary = escape(payload.get("summary", ""))
    out.append(
        f'<svg class="perf-radar perf-radar--{size}" viewBox="{VIEWBOX}" role="img" '
        f'aria-labelledby="perf-radar-title-{size} perf-radar-desc-{size}" '
        f'xmlns="http://www.w3.org/2000/svg" data-size="{size}">'
    )
    out.append(f'<title id="perf-radar-title-{size}">Performance radar</title>')
    out.append(f'<desc id="perf-radar-desc-{size}">{summary}</desc>')

    # rings
    for ring in RINGS:
        pts = [_pt(i, n, R * ring / 100.0) for i in range(n)]
        edge = ring == 100
        out.append(
            f'<polygon class="perf-radar-ring" data-ring="{ring}" points="{_points(pts)}" '
            f'fill="{"#f7f9fd" if edge else "none"}" stroke="{"#dfe5f1" if edge else "#e6ebf5"}" '
            f'stroke-width="{"1.5" if edge else "1"}"/>'
        )
    # spokes
    for i in range(n):
        x, y = _pt(i, n, R)
        out.append(f'<line x1="{_fmt(CX)}" y1="{_fmt(CY)}" x2="{_fmt(x)}" y2="{_fmt(y)}" stroke="#e6ebf5"/>')

    # 28-days-ago outline
    past = _polygon(axes, "score_28d_ago")
    if len(past) >= 3:
        out.append(
            f'<polygon class="perf-radar-past" points="{_points(past)}" fill="none" stroke="#8792a8" '
            f'stroke-width="2" stroke-dasharray="6 5"/>'
        )
    elif len(past) == 2:
        out.append(
            f'<polyline class="perf-radar-past" points="{_points(past)}" fill="none" stroke="#8792a8" '
            f'stroke-width="2" stroke-dasharray="6 5"/>'
        )

    # now polygon (measured axes only)
    now = _polygon(axes, "score")
    if len(now) >= 3:
        out.append(
            f'<polygon class="perf-radar-now" points="{_points(now)}" fill="rgba(31,59,138,0.16)" '
            f'stroke="{COLOR_BLUE}" stroke-width="3" stroke-linejoin="round"/>'
        )
    elif len(now) == 2:
        out.append(
            f'<polyline class="perf-radar-now" points="{_points(now)}" fill="none" '
            f'stroke="{COLOR_BLUE}" stroke-width="3"/>'
        )

    # points
    for i, a in enumerate(axes):
        if a["never_measured"]:
            continue
        x, y = _pt(i, n, R * max(0.0, min(100.0, float(a["score"]))) / 100.0)
        if a["focus"]:
            out.append(
                f'<circle class="perf-radar-point perf-radar-point--focus" data-axis="{a["axis"]}" '
                f'cx="{_fmt(x)}" cy="{_fmt(y)}" r="10" fill="{COLOR_AMBER}" stroke="#ffffff" stroke-width="2"/>'
            )
        elif a["stale"]:
            out.append(
                f'<circle class="perf-radar-point perf-radar-point--stale" data-axis="{a["axis"]}" '
                f'cx="{_fmt(x)}" cy="{_fmt(y)}" r="7" fill="#ffffff" stroke="{COLOR_BLUE}" '
                f'stroke-width="3" stroke-dasharray="3 2"/>'
            )
        else:
            out.append(
                f'<circle class="perf-radar-point" data-axis="{a["axis"]}" cx="{_fmt(x)}" cy="{_fmt(y)}" '
                f'r="6.5" fill="{COLOR_BLUE}"/>'
            )

    # labels (score + short status; never-measured axes are listed below the chart instead)
    for i, a in enumerate(axes):
        lx, ly = _pt(i, n, R + LABEL_GAP)
        dx = lx - CX
        anchor = "middle" if abs(dx) < 12 else ("start" if dx > 0 else "end")
        label = escape(a["label"])
        focus = a["focus"]
        color = COLOR_AMBER_INK if focus else COLOR_INK
        weight = "800" if focus else "700"
        if a["never_measured"]:
            score_txt = ""
            color = COLOR_MUTED
        else:
            score_txt = (
                f' <tspan font-family="JetBrains Mono, monospace" font-weight="600" '
                f'fill="{COLOR_AMBER_INK if focus else COLOR_MUTED}">{fmt_score(a["score"])}</tspan>'
            )
        out.append(
            f'<text class="perf-radar-label" data-axis="{a["axis"]}" x="{_fmt(lx)}" y="{_fmt(ly)}" '
            f'font-size="21" font-weight="{weight}" fill="{color}" text-anchor="{anchor}">{label}{score_txt}</text>'
        )
        if a["status"] and not a["never_measured"]:
            out.append(
                f'<text class="perf-radar-status" data-axis="{a["axis"]}" x="{_fmt(lx)}" y="{_fmt(ly + 20)}" '
                f'font-size="16" fill="{COLOR_AMBER_INK if focus else COLOR_MUTED}" text-anchor="{anchor}">'
                f'{escape(a["status"])}</text>'
            )
    out.append("</svg>")

    missing = payload.get("not_yet_measured") or []
    if missing:
        out.append(
            '<p class="perf-radar-missing">Not yet measured: ' + escape(", ".join(missing)) + "</p>"
        )
    return "".join(out)
