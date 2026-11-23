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
    assert "Log it late" in LOG_JS


def test_log_list_css_grid_and_week_header():
    assert "grid-template-columns: 56px minmax(0, 1fr) auto 170px" in CSS
    assert "rv-session-dot--run" in CSS
    assert "rv-planned-empty" in CSS
    assert "padding: 16px 20px" in CSS
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


def test_plan_page_order_is_road_then_board_beside_rail():
    assert 'id="v2-plan-week-head"' in PLAN_HTML
    assert 'id="v2-plan-week-board"' in PLAN_HTML
    assert 'id="v2-plan-rail"' in PLAN_HTML
    assert "rv-plan-main" not in PLAN_HTML
    road_i = PLAN_HTML.find('id="v2-plan-road"')
    load_i = PLAN_HTML.find('id="v2-plan-week-load"')
    head_i = PLAN_HTML.find('id="v2-plan-week-head"')
    board_i = PLAN_HTML.find('id="v2-plan-week-board"')
    rail_i = PLAN_HTML.find('id="v2-plan-rail"')
    assert road_i < load_i < head_i < board_i < rail_i
    assert "minmax(0, 1fr) 316px" in CSS
    assert "position: sticky" not in CSS.split("body.rv-page .rv-plan-rail")[1][:80]
    assert "v2-plan-week-head" in BOARD_JS
    assert "rv-week-board-card" in BOARD_JS
    assert "v2-week-export" in BOARD_JS


def test_plan_generic_mode_hides_phase_ribbon_and_week_hint():
    assert "if (!generic)" in PLAN_JS
    assert "Recent load · " in PLAN_JS
    assert "28-day chronic" in PLAN_JS
    assert "BOX * 0.88" in PLAN_JS
    assert "rv-rule-row" in PLAN_JS
    assert "rv-rule-state--ok" in PLAN_JS
    assert "rv-plan-next-bar" in PLAN_JS
    assert "wl.plan_hint" not in PLAN_JS
    assert "data.plan_hint" in PLAN_JS
    assert 'phase = wl.mode === \'generic\' ? \'general\'' in PLAN_JS or 'wl.mode === \'generic\' ? \'general\'' in PLAN_JS


def test_toolbar_segnav_active_is_white():
    assert "rv-toolbar-left" in PLAN_HTML
    assert "rv-toolbar-left" in LOG_HTML
    assert 'a[aria-current="page"]:visited' in CSS
    assert "flex-direction: row" in CSS


def test_toolbar_sync_now_label_and_nav_dot_only():
    toolbar = (ROOT / "frontend" / "js" / "lib" / "v2-sync-toolbar.js").read_text(encoding="utf-8")
    status = (ROOT / "frontend" / "js" / "v2-sync-status.js").read_text(encoding="utf-8")
    assert "Sync now" in toolbar
    assert "v2-sync-now-spin" in toolbar
    assert "label.hidden = true" in status
    assert "synced " in toolbar
