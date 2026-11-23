"""Issue #1944 — Log list D session row metrics + TSS share of week."""
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LOG_JS = (REPO / "frontend" / "js" / "v2-training-log.js").read_text(encoding="utf-8")
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


def test_row_grid_and_share_bar():
    row = _fn(LOG_JS, "renderSessionRow")
    paint = _fn(LOG_JS, "paintList")
    assert "grid-template-columns: 56px minmax(0, 1fr) auto 170px" in CSS
    assert "rv-session-share" in row
    assert "Math.round((Number(entry.tss) / weekTss) * 100)" in row
    assert "weekTss > 0" in row
    assert "Math.round(entry.tss)" in row
    assert "rv-session-row--race" in row
    assert "rv-chip--race-flag" in _fn(LOG_JS, "badgeChips")
    assert "more sessions this week" in paint
    assert "restTss" in paint


def test_metrics_bold_duration_and_distance():
    meta = _fn(LOG_JS, "sessionMeta")
    assert "fmtHms" in meta
    assert "fmtKm" in meta
    assert "<b>" in meta
    assert "fmtPaceSpk" in meta
    assert "' W'" in meta or "+ ' W'" in meta
    assert "HR " in meta
    assert "font-size: 13.5px" in CSS
    assert "color: #7a869f" in CSS
    assert "color: #0b1530" in CSS


def test_race_row_tokens():
    assert "background: #fbffe0" in CSS
    assert "color: #4a5200" in CSS
    assert "background: #8f9a00" in CSS
    assert "background: #f4ff9e" in CSS
    assert "border: 1px solid #b8c400" in CSS
    assert "width: 110px" in CSS
    assert "height: 6px" in CSS


def test_feel_drops_under_metrics_at_390():
    assert "@media (max-width: 480px)" in CSS
    assert "grid-template-columns: 48px minmax(0, 1fr) 56px" in CSS
    row = _fn(LOG_JS, "renderSessionRow")
    assert "rv-list-feel" in row
    assert "data-feel-id" in row
