"""Sprint 138 — Plan tab (WC-18) and Performance tab (WC-19) checklist gaps."""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
UI = (REPO / "frontend/js/checklist-ui.js").read_text(encoding="utf-8")
PLAN = (REPO / "frontend/js/training-plan.js").read_text(encoding="utf-8")
PERF = (REPO / "frontend/js/training-performance.js").read_text(encoding="utf-8")
PAGE = (REPO / "frontend/pages/training-log.html").read_text(encoding="utf-8")
CSS = (REPO / "frontend/css/checklist.css").read_text(encoding="utf-8")


def test_plan_tab_checklist_strip_and_columns():
    assert "renderPlanWeekHeader" in UI
    assert "cl-plan-week-hdr" in UI
    assert "cl-plan-cols" in UI
    assert "cl-day-chip" in UI
    assert "cl-race-strip--light" in CSS
    assert "light: true" in UI or "opts.light" in UI
    assert "_loadChecklistForPlan" in PLAN
    assert "_checklistRaceDates" in PLAN
    assert 'id="cl-plan-strip"' in PLAN
    assert ".cl-plan-week-hdr" in CSS


def test_plan_tab_day_chip_labels():
    assert "TODAY" in UI
    assert "RACE DAY" in UI
    assert "PLANNED" in UI
    assert "Session" in UI and "Mobility" in UI and "Fuel" in UI


def test_performance_unified_a_race_hero():
    assert "pm-hero-stats" in PERF
    assert "pm-hero-stat-k" in PERF
    assert "Race-specific" in PERF
    assert "Estimate" in PERF
    assert 'id="plan-race-header-content"' in PAGE
    assert ".pm-hero-stats" in PAGE


def test_performance_what_moves_sidebar_and_race_order():
    assert "renderWhatMoves" in UI
    assert "What moves the A-race estimate" in PERF
    assert 'id="plan-what-moves"' in PAGE
    assert "pm-what-moves-sidebar" in PAGE
    assert "Needs a result" in PERF
    # Needs-a-result section is rendered before Upcoming and Completed.
    idx_needs = PERF.index('"Needs a result"')
    idx_upcoming = PERF.index('"Upcoming"')
    idx_completed = PERF.index('"Completed"')
    assert idx_needs < idx_upcoming < idx_completed


def test_training_log_cache_bust_wc18_wc19():
    assert "training-plan.js?v=20260929e" in PAGE
    assert "training-performance.js?v=20260929n" in PAGE
    assert "checklist-ui.js?v=20260929e" in PAGE


def test_race_save_recomputes_stale_plan_bundle():
    assert "function _refreshAfterRaceMutation()" in PERF
    assert "stale computed_cache" in PERF
    assert "suggested_actual_time_seconds" in PERF
    assert "_refreshAfterRaceMutation();" in PERF
