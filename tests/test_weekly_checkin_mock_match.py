"""Prompt 10 — weekly check-in mock parity (static)."""
from pathlib import Path

HTML = Path("frontend/pages/v2-weekly-check-in.html").read_text(encoding="utf-8")
JS = Path("frontend/js/v2-weekly-check-in.js").read_text(encoding="utf-8")
CSS = Path("frontend/css/revamp.css").read_text(encoding="utf-8")
CHECKLIST = Path("backend/services/a_race_readiness_checklist.py").read_text(encoding="utf-8")


def test_stepper_labels_and_anchors():
    assert "Last week's changes" in HTML
    assert "Check the week" in HTML
    assert "Three quick scores" in HTML
    assert "Copy · talk · paste back" in HTML
    assert 'href="#step-1"' in HTML
    assert "repeat(4, minmax(0, 1fr))" in CSS


def test_segmented_scores_not_selects():
    assert 'id="wci-feet"' not in JS
    assert "wci-seg" in JS
    assert "aria-pressed" in JS
    assert "0 fine · 3 pain or numbness" in JS
    assert "Copy for Claude" in JS


def test_load_failure_has_retry():
    assert "Could not load this week's check-in" in JS
    assert "Try again" in JS
    assert "fetchWithCsrf" in JS


def test_run_workouts_passes_type_string():
    assert "is_run_workout(w.workout_type or" in CHECKLIST
