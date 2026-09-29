"""Sprint 138 Home wiring — Today session, checklist share, layout order."""
from __future__ import annotations

import pathlib

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_HOME_HTML = (_ROOT / "frontend/pages/home.html").read_text(encoding="utf-8")
_HOME_JS = (_ROOT / "frontend/js/home.js").read_text(encoding="utf-8")
_TODAY_SESSION = (_ROOT / "frontend/js/home-today-session.js").read_text(encoding="utf-8")
_TODAY_CHECKLIST = (_ROOT / "frontend/js/home-today-checklist.js").read_text(encoding="utf-8")
_WEEK_PLAN = (_ROOT / "frontend/js/home-brief-week-plan-card.js").read_text(encoding="utf-8")
_RTS = (_ROOT / "frontend/js/home-readiness-training-sleep.js").read_text(encoding="utf-8")


def test_home_js_wires_today_session():
    assert "HomeTodaySession" in _HOME_JS
    assert "HomeTodaySession.render" in _HOME_JS
    assert "NextUpCard" not in _HOME_JS


def test_home_html_loads_today_session_before_home_js():
    sess_idx = _HOME_HTML.find("home-today-session.js")
    home_idx = _HOME_HTML.find('src="js/home.js')
    assert sess_idx != -1 and home_idx != -1
    assert sess_idx < home_idx


def test_home_html_no_duplicate_checklist_script():
    loads = [
        line for line in _HOME_HTML.splitlines()
        if "home-today-checklist.js" in line and "<script" in line
    ]
    assert len(loads) == 1


def test_home_js_fetches_checklist_once():
    assert "_fetchChecklistWeek" in _HOME_JS
    assert "checklistWeek" in _HOME_JS
    assert "checklist_enabled" not in _HOME_JS


def test_home_js_passes_checklist_to_week_plan():
    assert "HomeBriefWeekPlanCard.render(weekPlanEl, weekDays, checklistWeek)" in _HOME_JS


def test_today_checklist_has_loading_and_status_codes():
    assert "showLoading" in _TODAY_CHECKLIST
    assert "return 'ok'" in _TODAY_CHECKLIST
    assert "return 'error'" in _TODAY_CHECKLIST


def test_week_plan_day_type_and_phase():
    assert "hpl-day-type" in _WEEK_PLAN
    assert "hpl-phase" in _WEEK_PLAN
    assert "_weekPlanSubtitle" in _WEEK_PLAN


def test_performance_overall_label():
    assert "Performance · overall" in _RTS


def test_layout_race_before_weight():
    race_pos = _HOME_HTML.find('id="home-race-card"')
    weight_pos = _HOME_HTML.find('id="home-weight-trend"')
    assert race_pos < weight_pos


def test_layout_week_plan_before_training():
    week_pos = _HOME_HTML.find('id="home-brief-week-plan-card"')
    train_pos = _HOME_HTML.find('id="home-training-card"')
    assert week_pos < train_pos


def test_today_session_exercise_list():
    assert "hts-exercises" in _TODAY_SESSION
    assert "window.HomeTodaySession" in _TODAY_SESSION


def test_sprint138_mock_doc_exists():
    path = _ROOT / "docs/mocks/home-sprint138-checklist.html"
    assert path.is_file(), "docs/mocks/home-sprint138-checklist.html must exist"
