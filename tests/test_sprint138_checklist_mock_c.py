"""Sprint 138 slice C — Home alignment + polish (WC-27..WC-28)."""
from __future__ import annotations


def test_checklist_shared_module():
    src = open("frontend/js/checklist-shared.js", encoding="utf-8").read()
    assert "ChecklistShared" in src
    assert "itemRowHtml" in src
    assert "fuelBoxesHtml" in src
    assert "autoFillLink" in src


def test_home_today_checklist_module():
    src = open("frontend/js/home-today-checklist.js", encoding="utf-8").read()
    assert "HomeTodayChecklist" in src
    assert "ChecklistShared" in src
    assert "/api/checklist/week" in src


def test_home_loads_checklist_modules():
    html = open("frontend/pages/home.html", encoding="utf-8").read()
    assert "checklist-shared.js" in html
    assert "home-today-checklist.js" in html
    assert "htc-card" in html


def test_habits_week_nav_in_mock_page():
    src = open("frontend/js/checklist-habits-page.js", encoding="utf-8").read()
    assert "clh-week-nav" in src
    assert "onWeekPrev" in src
    assert "data-back-current" in src


def test_habits_js_passes_week_callbacks():
    src = open("frontend/js/habits.js", encoding="utf-8").read()
    assert "onWeekPrev" in src
    assert "onBackCurrent" in src


def test_home_refetches_week_after_mark_done():
    src = open("frontend/js/home.js", encoding="utf-8").read()
    assert "_fetchWeekPlannedSessions" in src
    assert "/api/home/summary" in src
    assert "_reloadWeekState" in src
    assert "HomeTodayChecklist" in src


def test_food_portions_for_targets():
    from backend.services.fuel import FOOD, food_portions_for_targets

    fp = food_portions_for_targets(155, 230)
    assert fp["meat_g"] > 0
    assert fp["rice_g"] > 0
    assert fp["rice_carbs_per_100g"] == round(FOOD["rice"]["c"] * 100)


def test_habits_html_loads_checklist_shared():
    html = open("frontend/pages/habits.html", encoding="utf-8").read()
    assert "checklist-shared.js" in html
