"""Phase B — bundle merges (week-bundle, home summary v2, Perf boot)."""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MAIN = (REPO / "backend" / "main.py").read_text(encoding="utf-8")
PLAN_JS = (REPO / "frontend" / "js" / "training-plan.js").read_text(encoding="utf-8")
HOME_JS = (REPO / "frontend" / "js" / "home.js").read_text(encoding="utf-8")
HOME_RTS = (REPO / "frontend" / "js" / "home-readiness-training-sleep.js").read_text(encoding="utf-8")
HOME_RACE = (REPO / "frontend" / "js" / "home-race-card.js").read_text(encoding="utf-8")
PERF_JS = (REPO / "frontend" / "js" / "training-performance.js").read_text(encoding="utf-8")


def test_week_bundle_route_exists():
    assert 'def get_plan_week_bundle' in MAIN
    assert '"/api/plan/week-bundle"' in MAIN or "'/api/plan/week-bundle'" in MAIN
    assert "include_load_plan" in MAIN


def test_plan_fe_uses_week_bundle():
    assert "/api/plan/week-bundle" in PLAN_JS
    assert "function _applyWeekBundle" in PLAN_JS
    # init should not separately call load-plan anymore
    init = PLAN_JS[PLAN_JS.find("init: function ()") : PLAN_JS.find("init: function ()") + 900]
    assert "_loadLoadPlan()" not in init


def test_home_summary_has_phase_b_fields():
    assert '"week_days": week_days' in MAIN
    assert '"race": race_block' in MAIN
    assert "def _home_slim_primary_race" in MAIN
    assert 'readiness_block["training_load"]' in MAIN or "training_load" in MAIN


def test_home_fe_uses_summary_week_days_and_race():
    assert "summary.week_days" in HOME_JS
    assert "summary.race" in HOME_JS
    assert "HomeRaceCard.render" in HOME_JS


def test_home_rts_prefers_summary_performance_and_training_load():
    assert "training_load" in HOME_RTS
    assert "summary && summary.performance" in HOME_RTS or "summary.performance" in HOME_RTS


def test_home_race_accepts_primary_arg():
    assert "function render(host, primary)" in HOME_RACE
    assert "_paintPrimary" in HOME_RACE


def test_perf_bundle_carries_boot_fields():
    assert '"performance": perf' in MAIN
    assert '"prs": prs' in MAIN
    assert '"workout_meta": workout_meta' in MAIN
    assert '"timezone"' in MAIN


def test_perf_fe_applies_bundle_boot_fields():
    assert "_applyPerfScoresFromBundle" in PERF_JS
    assert "bundle.workout_meta" in PERF_JS
    assert "bundle.performance" in PERF_JS
    # _perfBoot must not fan out prefs/scores/feeds/prs itself
    boot = PERF_JS[PERF_JS.find("function _perfBoot") : PERF_JS.find("function _perfBoot") + 700]
    assert "/api/user-preferences" not in boot
    assert "_loadPerfScores" not in boot
