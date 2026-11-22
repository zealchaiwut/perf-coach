"""Static contracts: Training Log chart/list and Plan mock match."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG_HTML = (ROOT / "frontend" / "pages" / "v2-training-log.html").read_text(encoding="utf-8")
LOG_JS = (ROOT / "frontend" / "js" / "v2-training-log.js").read_text(encoding="utf-8")
PLAN_HTML = (ROOT / "frontend" / "pages" / "v2-training-plan.html").read_text(encoding="utf-8")
PLAN_JS = (ROOT / "frontend" / "js" / "v2-training-plan.js").read_text(encoding="utf-8")
BOARD_JS = (ROOT / "frontend" / "js" / "v2-plan-week-board.js").read_text(encoding="utf-8")
CSS = (ROOT / "frontend" / "css" / "revamp.css").read_text(encoding="utf-8")


def test_log_chart_header_and_legend_in_markup():
    assert 'id="v2-chart-section"' in LOG_HTML
    assert "rv-chart-head" in LOG_HTML
    assert "rv-chart-legend" in LOG_HTML
    assert "Click a week, here or in the calendar, to jump to it in the list" in LOG_HTML
    assert "Run TSS" in LOG_HTML
    assert "Lift TSS" in LOG_HTML
    assert 'id="rv-training-subtitle"' in LOG_HTML


def test_log_chart_svg_layout_matches_mock():
    assert 'viewBox="0 0 1000 220"' in LOG_JS
    assert "height:240px" in LOG_JS
    assert 'y1="20"' in LOG_JS
    assert 'y1="105"' in LOG_JS
    assert 'y1="190"' in LOG_JS
    assert "var BAR_W = 56" in LOG_JS
    assert "var SLOT = 111" in LOG_JS
    assert "var FIRST_CX = 55" in LOG_JS
    assert "stroke-dasharray=\"5 4\"" in LOG_JS
    assert "fmtDayMonth" in LOG_JS
    assert "topRoundRect" in LOG_JS


def test_log_list_drops_visible_sessions_title():
    assert 'id="v2-list-h" class="sr-only"' in LOG_HTML
    assert "Runs" in LOG_JS
    assert "Search sessions" in LOG_JS
    assert 'for="v2-search"' in LOG_JS
    assert 'for="v2-range"' in LOG_JS
    assert "fmtHms" in LOG_JS
    assert "HR " in LOG_JS
    assert "rv-session-row--today" in LOG_JS
    assert "rv-week-more" in LOG_JS
    assert "open in Plan" in LOG_JS
    assert "Review in Plan" in LOG_JS


def test_log_list_css_grid_and_week_header():
    assert "grid-template-columns: 58px 10px minmax(0, 1fr) auto auto" in CSS
    assert "rv-session-dot--run" in CSS
    assert "rv-planned-empty" in CSS
    assert "padding: 20px 6px 8px" in CSS
    assert "rv-chart-head" in CSS


def test_plan_warnings_host_is_in_main_and_hidden_empty():
    assert 'id="v2-plan-warnings"' in PLAN_HTML
    assert "rv-plan-warnings[hidden]" in CSS
    assert "insertBefore" not in PLAN_JS
    assert "Add an A race" in PLAN_JS
    assert "rv-road-grid" in PLAN_JS
    assert "rv-plan-formula-grid" in PLAN_JS
    assert "emptyPlanCard" in PLAN_JS


def test_plan_week_nav_uses_week_of_not_iso_only():
    assert "Week of " in BOARD_JS
    assert "rv-week-nav" in BOARD_JS
    assert "v2-week-new" in BOARD_JS
    assert "rv-suggest-banner" in BOARD_JS
    assert "rv-sess-who" in BOARD_JS
    assert "Rest day" in BOARD_JS
