"""Phase A — memory / SoT quick wins (chore/phase-a-memory-quickwins).

Static + unit contracts:
  1. Perf "Projected now" uses race-day proj[-1], not proj[0]
  2. Plan/home session TSS trusts API estimated_tss (no client pin re-prefer)
  3. Plan skips /api/plan/pipeline while drafts parked; no double week-load on init
  4. Log repeat probe uses workouts?limit=1
  5. get_projection + performance/chart batch splits; projection caps run history
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PERF_JS = (REPO / "frontend" / "js" / "training-performance.js").read_text(encoding="utf-8")
PLAN_JS = (REPO / "frontend" / "js" / "training-plan.js").read_text(encoding="utf-8")
HOME_WEEK = (REPO / "frontend" / "js" / "home-brief-week-plan-card.js").read_text(encoding="utf-8")
LOG_JS = (REPO / "frontend" / "js" / "training-log.js").read_text(encoding="utf-8")
MAIN = (REPO / "backend" / "main.py").read_text(encoding="utf-8")
HELPERS = (REPO / "backend" / "services" / "workout_perf_helpers.py").read_text(encoding="utf-8")


def _fn_body(src: str, name: str) -> str:
    marker = f"function {name}"
    i = src.find(marker)
    assert i >= 0, f"{name} not found"
    # Take until the next top-level "function " at column 2 (training-*.js style)
    rest = src[i:]
    nxt = rest.find("\n  function ", 10)
    return rest if nxt < 0 else rest[:nxt]


def test_current_estimate_uses_last_projection_sample():
    body = _fn_body(PERF_JS, "_currentEstimate")
    assert "proj[proj.length - 1]" in body or "proj.length - 1" in body
    assert "proj[0]" not in body


def test_plan_session_tss_does_not_reprefer_pin():
    body = _fn_body(PLAN_JS, "_sessionTss")
    assert "target_tss" not in body
    assert "estimated_tss" in body


def test_home_week_session_tss_does_not_reprefer_pin():
    body = _fn_body(HOME_WEEK, "_sessionTss")
    assert "target_tss" not in body
    assert "estimated_tss" in body


def test_plan_skips_pipeline_fetch_while_drafts_parked():
    body = _fn_body(PLAN_JS, "_loadPipelineThenWeek")
    assert "/api/plan/pipeline" not in body
    assert "_loadWeek(onDone)" in body


def test_plan_init_does_not_double_fetch_week_load():
    init = _fn_body(PLAN_JS, "init") if "function init" in PLAN_JS else ""
    # init is TrainingPlan.init object method — locate via "init: function"
    i = PLAN_JS.find("init: function ()")
    assert i >= 0
    chunk = PLAN_JS[i : i + 1200]
    # week-load must not be called from init; _loadWeek success path owns it
    assert "_loadWeekLoad" not in chunk


def test_log_repeat_uses_limit_one():
    body = _fn_body(LOG_JS, "refreshRepeatAvailability")
    assert "limit=1" in body
    assert "/api/workouts?from=" in body


def test_splits_by_workout_map_helper_exists():
    assert "def splits_by_workout_map" in HELPERS
    assert "WorkoutSplit.workout_id.in_" in HELPERS


def test_get_projection_caps_history_and_batches_splits():
    i = MAIN.find("def get_projection")
    assert i >= 0
    # Take a generous slice of the function
    chunk = MAIN[i : i + 12000]
    assert "_RUN_HISTORY_CAP_DAYS" in chunk
    assert "_splits_by_workout_map" in chunk
    # No per-workout N+1 filter left in the run loop
    assert "filter(WorkoutSplit.workout_id == workout.id)" not in chunk


def test_performance_chart_batches_splits():
    i = MAIN.find("def get_performance_chart")
    assert i >= 0
    chunk = MAIN[i : i + 8000]
    assert "_splits_by_workout_map" in chunk
    assert "filter(WorkoutSplit.workout_id == w.id)" not in chunk


def test_workouts_endpoint_accepts_limit():
    i = MAIN.find("def get_workouts")
    assert i >= 0
    chunk = MAIN[i : i + 2500]
    assert "limit: Optional[int]" in chunk
    assert "limit == 1" in chunk


def test_splits_by_workout_map_empty():
    from backend.services.workout_perf_helpers import splits_by_workout_map

    class _S:
        def query(self, *_a, **_k):
            raise AssertionError("empty ids must not query")

    assert splits_by_workout_map(_S(), []) == {}
