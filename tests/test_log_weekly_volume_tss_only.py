"""Log weekly volume chart: TSS-only, app palette."""
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LOG_JS = (REPO / "frontend" / "js" / "v2-training-log.js").read_text(encoding="utf-8")
LOG_HTML = (REPO / "frontend" / "pages" / "v2-training-log.html").read_text(encoding="utf-8")
CSS = (REPO / "frontend" / "css" / "revamp.css").read_text(encoding="utf-8")


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


def test_chart_has_no_distance_scale_or_orange():
    chart = _fn(LOG_JS, "drawChart")
    assert "maxKm" not in chart
    assert "yKm" not in chart
    assert "polyline" not in chart
    assert "<circle" not in chart
    assert "#d97706" not in chart
    assert "#bfd3f8" not in chart
    assert "#3b6fe0" not in chart
    assert "Distance" not in LOG_HTML.split("id=\"v2-chart-legend\"")[1][:400]


def test_chart_palette_and_target_line():
    chart = _fn(LOG_JS, "drawChart")
    assert "#1f3b8a" in chart
    assert "#b45309" in chart
    assert "#8b6fe0" in chart
    assert "#d4e400" in chart
    assert "#0b1530" in chart
    assert "stroke-dasharray=\"6 5\"" in chart
    assert "var BAR_W = 48" in chart
    assert 'viewBox="0 0 1160 240"' in chart
    assert "maxTss * 1.12" in chart
    assert ">RACE</text>" in chart
    assert "#7a3a10" in chart
    assert "#8792a8" in chart
    assert "#f3f6fd" in chart
    assert "rv-vol-vallabel" in chart


def test_legend_is_painted_from_js_and_conditional():
    legend = _fn(LOG_JS, "paintChartLegend")
    html_legend = LOG_HTML
    assert 'id="v2-chart-legend"' in html_legend
    assert "Run TSS" not in html_legend.split('id="v2-chart-legend"')[1][:200]
    assert "paintChartLegend" in _fn(LOG_JS, "drawChart")
    assert "Lift TSS" in legend
    assert "Over target" in legend
    assert "chartRace" in legend
    assert "Target " in legend
    assert "rv-swatch--target" in legend
    assert "rv-swatch--target" in CSS
    assert "rv-swatch--line" not in legend
    assert "Planned" not in legend


def test_hit_rect_keeps_keyboard_jump_and_title():
    chart = _fn(LOG_JS, "drawChart")
    assert 'role="button"' in chart
    assert 'tabindex="0"' in chart
    assert "data-week" in chart
    assert "<title>" in chart
    assert "over target" in chart
    assert "expandWeek" in chart
    assert "Enter" in chart
    assert "rv-vol-vallabel" in CSS
