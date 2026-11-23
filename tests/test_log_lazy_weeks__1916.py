"""Issue #1916 — Log lazy-loads older weeks; rollup is week-total SoT."""
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


def test_initial_requests_are_rollup_plus_two_week_log():
    chart = _fn(LOG_JS, "loadChart")
    assert "/api/weekly-rollup" in chart
    assert "-7 * 8" in chart
    initial = _fn(LOG_JS, "fetchInitialWeeks")
    assert "/api/training-log?from=" in initial
    assert "include_plan=1" in initial
    assert "canonical_week_totals" not in initial
    assert "newestTwoMondays" in initial
    assert "function fetchWeek" in LOG_JS
    assert "canonical_week_totals" not in _fn(LOG_JS, "fetchWeek")


def test_week_headers_read_rollup_not_entry_summary():
    paint = _fn(LOG_JS, "paintList")
    assert "rollupsByWeek" in LOG_JS
    assert "tss_total" in paint
    assert "headerPlannedTss" in paint
    assert "target_tss" in paint
    assert "wk.summary" not in paint
    assert "sum.total_tss" not in paint


def test_collapsed_older_weeks_are_buttons_from_rollup():
    paint = _fn(LOG_JS, "paintList")
    assert 'aria-expanded="false"' in paint
    assert "data-expand-week" in paint
    assert "rv-week-collapsed" in paint
    assert "data-retry-week" in CSS or "data-retry-week" in paint
    assert "rv-week-collapsed" in CSS


def test_expand_fetches_one_week_and_second_expand_uses_cache():
    fetch = _fn(LOG_JS, "fetchWeek")
    assert "weekEndISO(ws)" in fetch
    assert "/api/training-log?from=" in fetch
    assert "canonical_week_totals" not in fetch
    assert "state.weekCache[ws].loaded && !opts.force" in fetch
    assert "return Promise.resolve(state.weekCache[ws])" in fetch
    expand = _fn(LOG_JS, "expandWeek")
    assert "fetchWeek(ws)" in expand
    assert "scrollIntoView" in expand


def test_intersection_observer_root_margin_200px():
    bind = _fn(LOG_JS, "bindWeekObserver")
    assert "IntersectionObserver" in bind
    assert "rootMargin: '200px'" in bind
    assert "data-expand-week" in bind
    assert "expandWeek(ws, false)" in bind
