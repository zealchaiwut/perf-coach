"""HR lap overlay: missing km keep their x slot; polyline splits at holes."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RD = (REPO / "frontend/js/lib/run-detail-view.js").read_text(encoding="utf-8")


def _fn(src: str, name: str) -> str:
    needle = "function " + name + "("
    start = src.find(needle)
    assert start != -1, name
    brace = src.find("{", start)
    depth = 0
    i = brace
    while i < len(src):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[start : i + 1]
        i += 1
    raise AssertionError("unclosed " + name)


def _run(hr_values, weights):
    helper = _fn(RD, "hrOverlayInner")
    script = (
        helper
        + "; const r = hrOverlayInner("
        + json.dumps(hr_values)
        + ", "
        + json.dumps(weights)
        + "); process.stdout.write(r);"
    )
    out = subprocess.check_output(["node", "-e", script], text=True)
    return out


def _points(svg: str) -> list[tuple[float, float]]:
    pts = []
    for chunk in svg.split('d="M')[1:]:
        xy = chunk.split("l0 0")[0].strip().split()
        pts.append((float(xy[0]), float(xy[1])))
    return pts


def _polylines(svg: str) -> list[str]:
    parts = []
    rest = svg
    needle = '<polyline points="'
    while needle in rest:
        rest = rest.split(needle, 1)[1]
        pts, rest = rest.split('"', 1)
        parts.append(pts)
    return parts


def test_live_and_share_charts_share_helper():
    assert "hrOverlayInner(hrs, barDurWeights)" in _fn(RD, "drawChart")
    assert "hrOverlayInner(hrValues, weights)" in _fn(RD, "applyDurationFlexToChart")
    assert "if (hv == null || hv <= 0) return;" not in _fn(RD, "drawChart")
    assert "cum += w" not in _fn(RD, "drawChart")


def test_leading_null_hr_sits_on_later_bars():
    # Easy Run shape: km 1–3 missing, km 4–8 valid, equal bar widths.
    hrs = [None, None, None, 129, 139, 139, 138, 138]
    w = [1 / 8.0] * 8
    svg = _run(hrs, w)
    pts = _points(svg)
    assert len(pts) == 5
    xs = [p[0] for p in pts]
    # First real HR is the center of bar 4 → (3.5 / 8) * 100 = 43.75
    assert abs(xs[0] - 43.75) < 0.05
    assert abs(xs[-1] - 93.75) < 0.05
    assert xs[0] > 40, "must not pack remaining dots onto km 1"
    lines = _polylines(svg)
    assert len(lines) == 1
    assert len(lines[0].split()) == 5


def test_middle_gap_breaks_polyline():
    hrs = [129, 139, None, 138, 138]
    w = [0.2] * 5
    svg = _run(hrs, w)
    pts = _points(svg)
    assert len(pts) == 4
    lines = _polylines(svg)
    assert len(lines) == 2
    assert len(lines[0].split()) == 2
    assert len(lines[1].split()) == 2
    # Hole is bar 3 (center 50). Segments sit on 1–2 and 4–5.
    xs = [p[0] for p in pts]
    assert xs[1] < 45
    assert xs[2] > 55
