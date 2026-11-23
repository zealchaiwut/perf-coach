"""Inline-SVG radar renderer (revamp P4-6) — the one component behind both radars.

Pure function of the radar payload: same payload -> same SVG at either size.

- Axes sit at fixed angles (P4-1 order, clockwise from top). A never-measured
  axis plots at the centre so the outline runs in and back out; its label stays —.
- Rings at 25 / 50 / 75 (plus the 100 outer edge).
- Stale axes draw a hollow white point with a solid blue ring and a grey core;
  the focus axis gets the amber point and label.
- A thin solid grey outline shows the 28-days-ago polygon when at least two
  axes have a 28-day score.
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
    """One vertex per axis. Missing values (never-measured now, or no 28-day
    score) sit at the centre so the outline passes through them. Display only:
    the payload score stays null.
    """
    n = len(axes)
    pts: list[tuple[float, float]] = []
    for i, a in enumerate(axes):
        val = a.get(key)
        if val is None:
            pts.append((CX, CY))
            continue
        pts.append(_pt(i, n, R * max(0.0, min(100.0, float(val))) / 100.0))
    return pts


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
        if ring in (25, 50, 75):
            tx, ty = _pt(0, n, R * ring / 100.0)
            out.append(
                f'<text class="perf-radar-ring-label" x="{_fmt(tx - 14)}" y="{_fmt(ty + 5)}" '
                f'font-family="JetBrains Mono, monospace" font-size="12" fill="{COLOR_MUTED}">{ring}</text>'
            )
    # spokes
    for i in range(n):
        x, y = _pt(i, n, R)
        out.append(f'<line x1="{_fmt(CX)}" y1="{_fmt(CY)}" x2="{_fmt(x)}" y2="{_fmt(y)}" stroke="#e6ebf5"/>')

    # 28-days-ago outline — only when at least two axes actually have a past score
    past = _polygon(axes, "score_28d_ago")
    past_n = sum(1 for a in axes if a.get("score_28d_ago") is not None)
    if past_n >= 2:
        tag = "polygon" if len(past) >= 3 else "polyline"
        out.append(
            f'<{tag} class="perf-radar-past" points="{_points(past)}" fill="none" stroke="#a3adc2" '
            f'stroke-width="1.5"/>'
        )
        for i, (x, y) in enumerate(past):
            if axes[i].get("score_28d_ago") is None:
                continue
            out.append(
                f'<circle class="perf-radar-past-point" cx="{_fmt(x)}" cy="{_fmt(y)}" r="3" '
                f'fill="#a3adc2"/>'
            )

    # now polygon (never-measured axes sit at the centre)
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

    # points (including explicit markers for never-measured axes at the centre spoke)
    for i, a in enumerate(axes):
        if a["never_measured"]:
            x, y = _pt(i, n, 0)
            out.append(
                f'<circle class="perf-radar-point perf-radar-point--missing" data-axis="{a["axis"]}" '
                f'cx="{_fmt(x)}" cy="{_fmt(y)}" r="5" fill="#eef1f7" stroke="#94a3b8" stroke-width="2"/>'
            )
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
                f'stroke-width="3"/>'
            )
            out.append(
                f'<circle class="perf-radar-point-stale-core" data-axis="{a["axis"]}" '
                f'cx="{_fmt(x)}" cy="{_fmt(y)}" r="2.5" fill="#94a3b8"/>'
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
        sub = ""
        if a["never_measured"]:
            color = COLOR_MUTED
            sub = "—"
        else:
            bits = [fmt_score(a["score"])]
            if a.get("status"):
                bits.append(escape(str(a["status"])))
            sub = " · ".join(bits)
        out.append(
            f'<text class="perf-radar-label" data-axis="{a["axis"]}" x="{_fmt(lx)}" y="{_fmt(ly)}" '
            f'font-size="21" font-weight="{weight}" fill="{color}" text-anchor="{anchor}">{label}</text>'
        )
        out.append(
            f'<text class="perf-radar-status" data-axis="{a["axis"]}" x="{_fmt(lx)}" y="{_fmt(ly + 20)}" '
            f'font-size="16" font-family="JetBrains Mono, monospace" font-weight="600" '
            f'fill="{COLOR_AMBER_INK if focus else COLOR_MUTED}" text-anchor="{anchor}">{sub}</text>'
        )
    out.append("</svg>")

    missing = payload.get("not_yet_measured") or []
    if missing:
        out.append(
            '<p class="perf-radar-missing">Not yet measured: ' + escape(", ".join(missing)) + "</p>"
        )
    return "".join(out)
