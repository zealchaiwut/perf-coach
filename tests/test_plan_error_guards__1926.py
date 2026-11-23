"""Issue #1926 — Plan page: one board mount, per-section retry, stale guards."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLAN_JS = (ROOT / "frontend" / "js" / "v2-training-plan.js").read_text(encoding="utf-8")
BOARD_JS = (ROOT / "frontend" / "js" / "v2-plan-week-board.js").read_text(encoding="utf-8")
CSS = (ROOT / "frontend" / "css" / "revamp.css").read_text(encoding="utf-8")


def test_board_mounted_exactly_once():
    init = PLAN_JS.split("function init()")[-1]
    assert init.count("mountWeekBoard(board,") == 1
    assert "function mountWeekBoard(" in PLAN_JS


def test_section_renderers_accept_data_arguments():
    assert "function renderRoadChart(data, host)" in PLAN_JS
    assert "function renderWeekLoad(card, wl)" in PLAN_JS
    assert "function renderWarnings(host, w)" in PLAN_JS
    assert "function renderRail(rail, data, warnings, wl)" in PLAN_JS
    assert "window.V2TrainingPlan" in PLAN_JS
    assert "sectionError:" in PLAN_JS


def test_section_error_and_retry():
    assert "function sectionError(host, title, message, onRetry)" in PLAN_JS
    assert "data-section-retry" in PLAN_JS
    assert "loadAll" in PLAN_JS
    assert "Could not load this section. Try again." in PLAN_JS
    assert "HTTP 500" not in PLAN_JS
    assert "rv-plan-section-error" in CSS


def test_stale_week_nav_token():
    assert "var loadGen = 0" in BOARD_JS
    assert "var gen = ++loadGen" in BOARD_JS
    assert "if (gen !== loadGen) return null" in BOARD_JS
    assert "id=\"v2-board-retry\"" in BOARD_JS or "id='v2-board-retry'" in BOARD_JS


def test_board_and_week_load_have_error_handling():
    assert "function friendlyBoardError" in BOARD_JS
    assert "showBoardError" in BOARD_JS
    assert "applyWeekLoad" in BOARD_JS
    assert ".catch(function (e)" in BOARD_JS


def test_mutations_surface_non_ok():
    assert "Could not apply suggestions. Try again." in BOARD_JS
    assert "Could not parse coach week. Try again." in BOARD_JS
    assert "Could not reschedule. Try again." in PLAN_JS
