"""Inline-SVG radar renderer (revamp P4-6 / sprint-149).

Pure function of the radar payload: same payload -> same SVG at either size.

Never-measured axes do not plot at the centre. The Now fill covers measured
axes only; an edge that skips an unmeasured spoke is dashed grey.
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
PLUS_R = 11.0

COLOR_INK = "#0b1530"
COLOR_MUTED = "#8792a8"
COLOR_BLUE = "#1f3b8a"
COLOR_AMBER = "#b45309"
COLOR_AMBER_INK = "#7a3a10"
COLOR_SPOKE_MISS = "#c3cbdb"
COLOR_EDGE_SKIP = "#8792a8"


def _pt(index: int, count: int, radius: float) -> tuple[float, float]:
    ang = -math.pi / 2 + 2 * math.pi * index / count
    return CX + radius * math.cos(ang), CY + radius * math.sin(ang)


def _fmt(v: float) -> str:
    return f"{v:.1f}".rstrip("0").rstrip(".") if "." in f"{v:.1f}" else f"{v:.1f}"


def _points(pts: list[tuple[float, float]]) -> str:
    return " ".join(f"{_fmt(x)},{_fmt(y)}" for x, y in pts)


def _score_pt(axes: list[dict[str, Any]], i: int, key: str) -> Optional[tuple[float, float]]:
    val = axes[i].get(key)
    if val is None:
        return None
    n = len(axes)
    return _pt(i, n, R * max(0.0, min(100.0, float(val))) / 100.0)


def measured_indices(axes: list[dict[str, Any]], key: str = "score") -> list[int]:
    return [i for i, a in enumerate(axes) if a.get(key) is not None]


def now_edges(axes: list[dict[str, Any]], key: str = "score") -> list[dict[str, Any]]:
    """Edges between consecutive measured axes, wrapping in axis order.

    ``adjacent`` is True when the two vertices sit on neighbouring spokes
    (no unmeasured spoke between them).
    """
    n = len(axes)
    idxs = measured_indices(axes, key)
    if len(idxs) < 2:
        return []
    edges: list[dict[str, Any]] = []
    for k, i in enumerate(idxs):
        j = idxs[(k + 1) % len(idxs)]
        if i == j:
            continue
        span = (j - i) % n
        a = _score_pt(axes, i, key)
        b = _score_pt(axes, j, key)
        if a is None or b is None:
            continue
        edges.append(
            {
                "from": i,
                "to": j,
                "adjacent": span == 1,
                "p1": a,
                "p2": b,
            }
        )
    return edges


def _polygon_past(axes: list[dict[str, Any]], key: str) -> list[tuple[float, float]]:
    """Past outline uses measured-only vertices (no centre stubs)."""
    pts: list[tuple[float, float]] = []
    for i in measured_indices(axes, key):
        pt = _score_pt(axes, i, key)
        if pt is not None:
            pts.append(pt)
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

    for ring in RINGS:
        pts = [_pt(i, n, R * ring / 100.0) for i in range(n)]
        edge = ring == 100
        out.append(
            f'<polygon class="perf-radar-ring" data-ring="{ring}" points="{_points(pts)}" '
            f'fill="{"#f7f9fd" if edge else "none"}" stroke="{"#dfe5f1" if edge else "#e6ebf5"}" '
            f'stroke-width="{"1.5" if edge else "1"}"/>'
        )
        if ring in (50, 75):
            tx, ty = _pt(0, n, R * ring / 100.0)
            out.append(
                f'<text class="perf-radar-ring-label" x="{_fmt(tx - 14)}" y="{_fmt(ty + 4)}" '
                f'font-family="JetBrains Mono, monospace" font-size="10" fill="{COLOR_MUTED}">{ring}</text>'
            )

    for i, a in enumerate(axes):
        x, y = _pt(i, n, R)
        if a.get("never_measured"):
            out.append(
                f'<line class="perf-radar-spoke perf-radar-spoke--missing" data-axis="{a["axis"]}" '
                f'x1="{_fmt(CX)}" y1="{_fmt(CY)}" x2="{_fmt(x)}" y2="{_fmt(y)}" '
                f'stroke="{COLOR_SPOKE_MISS}" stroke-dasharray="4 4"/>'
            )
        else:
            out.append(
                f'<line class="perf-radar-spoke" data-axis="{a["axis"]}" '
                f'x1="{_fmt(CX)}" y1="{_fmt(CY)}" x2="{_fmt(x)}" y2="{_fmt(y)}" stroke="#e6ebf5"/>'
            )

    past_n = sum(1 for a in axes if a.get("score_28d_ago") is not None)
    past = _polygon_past(axes, "score_28d_ago")
    if past_n >= 2 and len(past) >= 2:
        tag = "polygon" if len(past) >= 3 else "polyline"
        out.append(
            f'<{tag} class="perf-radar-past" points="{_points(past)}" fill="none" stroke="#a3adc2" '
            f'stroke-width="1.5"/>'
        )
        for i, a in enumerate(axes):
            if a.get("score_28d_ago") is None:
                continue
            x, y = _score_pt(axes, i, "score_28d_ago")
            out.append(
                f'<circle class="perf-radar-past-point" cx="{_fmt(x)}" cy="{_fmt(y)}" r="3" '
                f'fill="#a3adc2"/>'
            )

    measured = measured_indices(axes, "score")
    now_pts = [_score_pt(axes, i, "score") for i in measured]
    now_pts = [p for p in now_pts if p is not None]
    if len(now_pts) >= 3:
        out.append(
            f'<polygon class="perf-radar-now" points="{_points(now_pts)}" fill="rgba(31,59,138,0.16)" '
            f'stroke="none"/>'
        )
    for edge in now_edges(axes, "score"):
        x1, y1 = edge["p1"]
        x2, y2 = edge["p2"]
        if edge["adjacent"]:
            out.append(
                f'<line class="perf-radar-now-edge" data-adjacent="1" '
                f'x1="{_fmt(x1)}" y1="{_fmt(y1)}" x2="{_fmt(x2)}" y2="{_fmt(y2)}" '
                f'stroke="{COLOR_BLUE}" stroke-width="3" stroke-linecap="round"/>'
            )
        else:
            out.append(
                f'<line class="perf-radar-now-edge" data-adjacent="0" '
                f'x1="{_fmt(x1)}" y1="{_fmt(y1)}" x2="{_fmt(x2)}" y2="{_fmt(y2)}" '
                f'stroke="{COLOR_EDGE_SKIP}" stroke-width="2" stroke-dasharray="5 5" '
                f'stroke-linecap="round"/>'
            )

    for i, a in enumerate(axes):
        if a.get("never_measured"):
            x, y = _pt(i, n, R)
            out.append(
                f'<circle class="perf-radar-point perf-radar-point--missing" data-axis="{a["axis"]}" '
                f'cx="{_fmt(x)}" cy="{_fmt(y)}" r="{_fmt(PLUS_R)}" fill="#ffffff" '
                f'stroke="{COLOR_SPOKE_MISS}" stroke-width="1.5" stroke-dasharray="3 3"/>'
            )
            arm = 4.0
            out.append(
                f'<line class="perf-radar-plus" data-axis="{a["axis"]}" '
                f'x1="{_fmt(x - arm)}" y1="{_fmt(y)}" x2="{_fmt(x + arm)}" y2="{_fmt(y)}" '
                f'stroke="{COLOR_MUTED}" stroke-width="1.6" stroke-linecap="round"/>'
            )
            out.append(
                f'<line class="perf-radar-plus" data-axis="{a["axis"]}" '
                f'x1="{_fmt(x)}" y1="{_fmt(y - arm)}" x2="{_fmt(x)}" y2="{_fmt(y + arm)}" '
                f'stroke="{COLOR_MUTED}" stroke-width="1.6" stroke-linecap="round"/>'
            )
            continue
        x, y = _score_pt(axes, i, "score")
        if x is None:
            continue
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

    for i, a in enumerate(axes):
        lx, ly = _pt(i, n, R + LABEL_GAP)
        dx = lx - CX
        anchor = "middle" if abs(dx) < 12 else ("start" if dx > 0 else "end")
        label = escape(a["label"])
        focus = a["focus"]
        never = bool(a.get("never_measured"))
        color = COLOR_MUTED if never else (COLOR_AMBER_INK if focus else COLOR_INK)
        weight = "800" if focus and not never else "700"
        out.append(
            f'<text class="perf-radar-label" data-axis="{a["axis"]}" x="{_fmt(lx)}" y="{_fmt(ly)}" '
            f'font-size="21" font-weight="{weight}" fill="{color}" text-anchor="{anchor}">{label}</text>'
        )
        if never:
            action = escape(str(a.get("action_label") or "Not measured yet"))
            href = a.get("action_href") or ""
            y2 = ly + 18
            if href:
                out.append(
                    f'<a class="perf-radar-action" data-axis="{a["axis"]}" href="{escape(str(href))}">'
                    f'<text x="{_fmt(lx)}" y="{_fmt(y2)}" font-size="13" font-weight="700" '
                    f'fill="{COLOR_BLUE}" text-anchor="{anchor}">{action}</text></a>'
                )
            else:
                out.append(
                    f'<text class="perf-radar-action" data-axis="{a["axis"]}" x="{_fmt(lx)}" y="{_fmt(y2)}" '
                    f'font-size="13" font-weight="600" fill="{COLOR_BLUE}" text-anchor="{anchor}">{action}</text>'
                )
        else:
            bits = [fmt_score(a["score"])]
            if a.get("status"):
                bits.append(escape(str(a["status"])))
            sub = " · ".join(bits)
            out.append(
                f'<text class="perf-radar-status" data-axis="{a["axis"]}" x="{_fmt(lx)}" y="{_fmt(ly + 20)}" '
                f'font-size="16" font-family="JetBrains Mono, monospace" font-weight="600" '
                f'fill="{COLOR_AMBER_INK if focus else COLOR_MUTED}" text-anchor="{anchor}">{sub}</text>'
            )
    out.append("</svg>")
    return "".join(out)
