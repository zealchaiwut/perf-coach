"""Sprint 138 slice B — day detail, week matrix, sidebar (WC-24..WC-26)."""
from __future__ import annotations


def test_checklist_habits_day_detail_markup():
    page = open("frontend/js/checklist-habits-page.js", encoding="utf-8").read()
    shared = open("frontend/js/checklist-shared.js", encoding="utf-8").read()
    assert "_sessionCardHtml" in page
    assert "ChecklistShared" in page
    assert "itemRowHtml" in shared
    assert "clh-section-title" in page
    assert "clh-auto-tag" in shared


def test_checklist_habits_week_matrix():
    src = open("frontend/js/checklist-habits-page.js", encoding="utf-8").read()
    assert "_matrixHtml" in src
    assert "_matrixRows" in src
    assert "clh-matrix" in src
    assert "clh-mx-col" in src
    assert "matrixRows" in src  # exported for tests


def test_checklist_habits_sidebar_enriched():
    src = open("frontend/js/checklist-habits-page.js", encoding="utf-8").read()
    assert "clh-build-phase" in src
    assert "week_phase_reason" in src
    assert "What moves" in src


def test_checklist_ui_exports_wire_items():
    src = open("frontend/js/checklist-ui.js", encoding="utf-8").read()
    assert "wireItems" in src
    assert "stateClass" in src


def test_checklist_habits_css_slice_b():
    css = open("frontend/css/checklist-habits.css", encoding="utf-8").read()
    assert ".clh-session-card" in css
    assert ".clh-fuel-grid" in css
    assert ".clh-matrix" in css


def test_checklist_habits_wires_ticks():
    src = open("frontend/js/checklist-habits-page.js", encoding="utf-8").read()
    assert "ChecklistUI.wireItems" in src
    assert "onRefresh" in src
