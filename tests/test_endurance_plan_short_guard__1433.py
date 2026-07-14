"""Tests for issue #1433: plan-relative 'cut materially short of plan' guard.

Acceptance Criteria (from #1364 follow-up):
  AC1: If the run dict includes ``planned_duration_seconds`` and actual
       duration < ``PLAN_SHORT_CUT_RATIO * planned_duration_seconds``, the
       session is excluded from the endurance pool (plan-relative guard).
  AC2: If actual duration >= ``PLAN_SHORT_CUT_RATIO * planned_duration_seconds``,
       the session is admitted to the pool as normal.
  AC3: If ``planned_duration_seconds`` is absent / None, the absolute-duration
       guard (MIN_ENDURANCE_QUALIFYING_SESSION_SECONDS) remains the sole check
       — existing behaviour is unchanged.
  AC4: ``PLAN_SHORT_CUT_RATIO`` is a named constant exported from
       running_performance (not a magic number).
  AC5: Sessions with null top-level ``duration_seconds`` (even when
       ``planned_duration_seconds`` is provided) are excluded — this is
       confirmed intentional (mirrors endurance_signal.py; no lap-level
       duration fallback is used for the guard).
"""
import sys
import os
from datetime import date, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.services.running_performance import (
    compute_endurance_score,
    MIN_ENDURANCE_QUALIFYING_SESSION_SECONDS,
    PLAN_SHORT_CUT_RATIO,
)
from backend.services.zone_constants import make_zone_constants

_TODAY = date.today()
_THRESHOLD_HR = 165.0
_MIN_RUNS = 3


def _prefs():
    return {
        "ftp_w": 200,
        "threshold_hr": _THRESHOLD_HR,
        "threshold_pace_seconds_per_km": 300,
        "duration_curve_bests": None,
        "aerobic_decoupling_threshold": 8.0,
    }


def _zc():
    return make_zone_constants()


def _long_easy_run(run_id: str, days_ago: int, total_duration_s: float = 3000.0,
                   planned_duration_s: float | None = None) -> dict:
    """Easy run with optional planned_duration_seconds field."""
    dist_km = total_duration_s / 360.0  # pace 360 s/km
    lap_dur = total_duration_s
    d = (_TODAY - timedelta(days=days_ago)).isoformat()
    run = {
        "run_id": run_id,
        "workout_date": d,
        "laps": [
            {
                "band": "easy",
                "avg_power": 170.0,
                "avg_hr": 140.0,
                "distance_km": dist_km,
                "duration_seconds": lap_dur,
            }
        ],
        "decoupling_pct": 5.0,
        "avg_power": 170.0,
        "avg_hr": 140.0,
        "distance_km": dist_km,
        "duration_seconds": total_duration_s,
    }
    if planned_duration_s is not None:
        run["planned_duration_seconds"] = planned_duration_s
    return run


def _baseline_runs() -> list[dict]:
    """Three long easy runs that form a stable baseline."""
    return [
        _long_easy_run(f"base{i}", days_ago=10 + i * 7)
        for i in range(_MIN_RUNS)
    ]


# ---------------------------------------------------------------------------
# AC4: PLAN_SHORT_CUT_RATIO constant exists and is a sensible value
# ---------------------------------------------------------------------------

class TestPlanShortCutRatioConstant:
    """AC4: PLAN_SHORT_CUT_RATIO is a named constant in running_performance."""

    def test_constant_exists(self):
        """PLAN_SHORT_CUT_RATIO must be importable from running_performance."""
        assert PLAN_SHORT_CUT_RATIO is not None

    def test_constant_is_float_in_valid_range(self):
        """Ratio must be in (0, 1) — a fraction of planned duration."""
        assert isinstance(PLAN_SHORT_CUT_RATIO, float)
        assert 0.0 < PLAN_SHORT_CUT_RATIO < 1.0

    def test_constant_is_0_75(self):
        """Ratio is 0.75 — an athlete must complete ≥75% of plan to qualify."""
        assert PLAN_SHORT_CUT_RATIO == 0.75


# ---------------------------------------------------------------------------
# AC1: Plan-relative guard excludes sessions cut short of plan
# ---------------------------------------------------------------------------

class TestPlanRelativeGuardExcludes:
    """AC1: actual < ratio * planned → session excluded from endurance pool."""

    def test_session_below_ratio_excluded_from_pool(self):
        """If actual < 0.75 * planned, the run must not appear in run_contributions."""
        baseline = _baseline_runs()
        # planned 4000 s, actual 2800 s = 70% of plan < 75% threshold
        short_of_plan = _long_easy_run(
            "plan-short",
            days_ago=1,
            total_duration_s=2800.0,
            planned_duration_s=4000.0,
        )
        assert short_of_plan["duration_seconds"] > MIN_ENDURANCE_QUALIFYING_SESSION_SECONDS
        result = compute_endurance_score(baseline + [short_of_plan], _prefs(), _zc())
        assert "plan-short" not in result.get("run_contributions", {}), (
            "Session cut short of plan should not appear in run_contributions"
        )

    def test_session_below_ratio_does_not_raise_score(self):
        """Adding a plan-short session must not increase the endurance score."""
        baseline = _baseline_runs()
        score_before = compute_endurance_score(baseline, _prefs(), _zc())["score"]
        short_of_plan = _long_easy_run(
            "plan-short2",
            days_ago=1,
            total_duration_s=2700.0,   # 67% of 4000 s plan
            planned_duration_s=4000.0,
        )
        score_after = compute_endurance_score(
            baseline + [short_of_plan], _prefs(), _zc()
        )["score"]
        assert score_after <= score_before + 0.01, (
            f"Plan-short session raised Endurance: {score_before} → {score_after}"
        )

    def test_session_at_exactly_below_boundary_excluded(self):
        """Actual = ratio * planned - 1 second → excluded (strict less-than)."""
        baseline = _baseline_runs()
        planned = 4000.0
        # exactly 1 second below the threshold
        actual = PLAN_SHORT_CUT_RATIO * planned - 1.0
        short_run = _long_easy_run(
            "plan-boundary-below",
            days_ago=1,
            total_duration_s=actual,
            planned_duration_s=planned,
        )
        result = compute_endurance_score(baseline + [short_run], _prefs(), _zc())
        assert "plan-boundary-below" not in result.get("run_contributions", {})


# ---------------------------------------------------------------------------
# AC2: Plan-relative guard admits sessions that meet or exceed ratio
# ---------------------------------------------------------------------------

class TestPlanRelativeGuardAdmits:
    """AC2: actual >= ratio * planned → session admitted to the pool."""

    def test_session_at_exact_ratio_admitted(self):
        """Actual = 0.75 * planned exactly → session IS admitted."""
        baseline = _baseline_runs()
        planned = 4000.0
        actual = PLAN_SHORT_CUT_RATIO * planned  # exactly 75%
        on_ratio_run = _long_easy_run(
            "plan-at-ratio",
            days_ago=1,
            total_duration_s=actual,
            planned_duration_s=planned,
        )
        result = compute_endurance_score(baseline + [on_ratio_run], _prefs(), _zc())
        assert "plan-at-ratio" in result.get("run_contributions", {}), (
            "Session at exactly ratio * planned must be admitted"
        )

    def test_session_above_ratio_admitted(self):
        """Actual > 0.75 * planned → session admitted."""
        baseline = _baseline_runs()
        planned = 3600.0
        actual = planned  # ran exactly as planned (100%)
        full_run = _long_easy_run(
            "plan-full",
            days_ago=1,
            total_duration_s=actual,
            planned_duration_s=planned,
        )
        result = compute_endurance_score(baseline + [full_run], _prefs(), _zc())
        assert "plan-full" in result.get("run_contributions", {}), (
            "Session completing full plan must be admitted"
        )

    def test_session_well_above_plan_admitted(self):
        """If athlete ran longer than planned, the session is definitely admitted."""
        baseline = _baseline_runs()
        over_run = _long_easy_run(
            "plan-over",
            days_ago=1,
            total_duration_s=5000.0,  # 125% of 4000 s plan
            planned_duration_s=4000.0,
        )
        result = compute_endurance_score(baseline + [over_run], _prefs(), _zc())
        assert "plan-over" in result.get("run_contributions", {})


# ---------------------------------------------------------------------------
# AC3: No planned_duration_seconds → absolute threshold only (existing behaviour)
# ---------------------------------------------------------------------------

class TestAbsoluteThresholdFallback:
    """AC3: Absence of planned_duration_seconds keeps the existing absolute guard."""

    def test_run_without_planned_above_absolute_threshold_admitted(self):
        """No planned_duration_seconds + actual > 2400 s → admitted as before."""
        baseline = _baseline_runs()
        run = _long_easy_run("no-plan", days_ago=1, total_duration_s=3000.0)
        assert "planned_duration_seconds" not in run
        result = compute_endurance_score(baseline + [run], _prefs(), _zc())
        assert "no-plan" in result.get("run_contributions", {}), (
            "Run without plan that exceeds absolute threshold must be admitted"
        )

    def test_run_without_planned_below_absolute_threshold_excluded(self):
        """No planned_duration_seconds + actual <= 2400 s → excluded as before."""
        baseline = _baseline_runs()
        run = _long_easy_run("no-plan-short", days_ago=1, total_duration_s=2400.0)
        assert "planned_duration_seconds" not in run
        result = compute_endurance_score(baseline + [run], _prefs(), _zc())
        assert "no-plan-short" not in result.get("run_contributions", {}), (
            "Run without plan below absolute threshold must be excluded"
        )

    def test_run_with_none_planned_uses_absolute_threshold(self):
        """planned_duration_seconds=None is treated the same as absent."""
        baseline = _baseline_runs()
        run = _long_easy_run("none-plan", days_ago=1, total_duration_s=3000.0,
                             planned_duration_s=None)
        # Manually insert None to distinguish from absent key
        run["planned_duration_seconds"] = None
        result = compute_endurance_score(baseline + [run], _prefs(), _zc())
        assert "none-plan" in result.get("run_contributions", {}), (
            "planned_duration_seconds=None must fall back to absolute-threshold check"
        )


# ---------------------------------------------------------------------------
# AC5: Null top-level duration_seconds → excluded even with plan field
# ---------------------------------------------------------------------------

class TestNullDurationExcluded:
    """AC5: null duration_seconds is intentionally excluded regardless of planned field.

    A run whose top-level duration_seconds is None (e.g., loaded before Strava
    enrichment completed) may have valid lap data, but we can't verify it passed
    the minimum-session check — we exclude it to avoid partial data polluting the
    pool.  This mirrors endurance_signal.py's existing >2400 rule.
    """

    def test_null_duration_excluded_even_with_valid_plan(self):
        """duration_seconds=None → excluded, even if planned_duration_seconds set."""
        baseline = _baseline_runs()
        null_dur_run = {
            "run_id": "null-dur",
            "workout_date": (_TODAY - timedelta(days=1)).isoformat(),
            "laps": [
                {
                    "band": "easy",
                    "avg_power": 170.0,
                    "avg_hr": 140.0,
                    "distance_km": 10.0,
                    "duration_seconds": 3600.0,  # laps have duration
                }
            ],
            "decoupling_pct": 5.0,
            "avg_power": 170.0,
            "avg_hr": 140.0,
            "distance_km": 10.0,
            "duration_seconds": None,           # top-level is None
            "planned_duration_seconds": 3600.0, # plan field present
        }
        result = compute_endurance_score(baseline + [null_dur_run], _prefs(), _zc())
        assert "null-dur" not in result.get("run_contributions", {}), (
            "null duration_seconds must exclude the session even with valid laps and plan"
        )

    def test_null_duration_excluded_without_plan(self):
        """duration_seconds=None without planned field is excluded (existing check)."""
        baseline = _baseline_runs()
        null_dur_run = {
            "run_id": "null-dur2",
            "workout_date": (_TODAY - timedelta(days=1)).isoformat(),
            "laps": [
                {
                    "band": "easy",
                    "avg_power": 170.0,
                    "avg_hr": 140.0,
                    "distance_km": 10.0,
                    "duration_seconds": 3600.0,
                }
            ],
            "decoupling_pct": 5.0,
            "avg_power": 170.0,
            "avg_hr": 140.0,
            "distance_km": 10.0,
            "duration_seconds": None,
        }
        result = compute_endurance_score(baseline + [null_dur_run], _prefs(), _zc())
        assert "null-dur2" not in result.get("run_contributions", {})
