"""Tests for issue #1364: Endurance score re-anchor + aborted-session guard.

Acceptance Criteria:
  AC1: Endurance score anchored absolutely (VDOT band, not window-relative).
  AC2: Aborted-session guard — sessions at or below MIN_ENDURANCE_QUALIFYING_SESSION_SECONDS
       are excluded from the endurance/durability signal.
  AC3: Regression: Endurance does not rise from an aborted interval session.
  AC4: Detraining decay — stale history scores lower than fresh history.
  AC5: formula_version bumped from vdot-v11 (cache-busting for history rows).
  AC6: Anchoring math: guard boundary (just above / just below min duration).
"""
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.services.running_performance import (  # noqa: E402
    compute_endurance_score,
    MIN_ENDURANCE_QUALIFYING_SESSION_SECONDS,
)
from backend.services.zone_constants import make_zone_constants  # noqa: E402


_TODAY = date.today()
_THRESHOLD_HR = 165.0
_MIN_RUNS = 3  # top-K anchor requires at least 3 qualifying runs


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


def _easy_run(
    run_id: str,
    days_ago: int,
    pace_s_per_km: float = 360.0,
    avg_hr: float = 140.0,
    dist_km: float = 8.0,
    total_duration_s: float | None = None,
    decoupling_pct: float = 5.0,
):
    """Easy run long enough to pass the aborted-session guard by default."""
    lap_dur = pace_s_per_km * dist_km
    # Total session duration defaults to lap duration (same run); tests can
    # override to test the guard boundary independently of lap content.
    session_dur = total_duration_s if total_duration_s is not None else lap_dur
    d = (_TODAY - timedelta(days=days_ago)).isoformat()
    return {
        "run_id": run_id,
        "workout_date": d,
        "laps": [
            {
                "band": "easy",
                "avg_power": 175.0,
                "avg_hr": avg_hr,
                "distance_km": dist_km,
                "duration_seconds": lap_dur,
            }
        ],
        "decoupling_pct": decoupling_pct,
        "avg_power": 175.0,
        "avg_hr": avg_hr,
        "distance_km": dist_km,
        "duration_seconds": session_dur,
    }


def _three_baseline_runs(days_offset: int = 0) -> list[dict]:
    """Three easy long runs that form a stable endurance baseline."""
    return [
        _easy_run(f"base{i}", days_ago=days_offset + 5 + i * 7)
        for i in range(_MIN_RUNS)
    ]


# ---------------------------------------------------------------------------
# AC2: Aborted-session guard boundary (just above / just below min duration)
# ---------------------------------------------------------------------------

class TestAbortedSessionGuardBoundary:
    """Guard constant exists and the threshold boundary is respected exactly."""

    def test_constant_is_2400(self):
        """Guard threshold must be 2400 s (40 min) — matches endurance_signal.py."""
        assert MIN_ENDURANCE_QUALIFYING_SESSION_SECONDS == 2400

    def test_run_at_threshold_is_excluded(self):
        """A session whose total duration == threshold must NOT qualify."""
        # 3 baseline runs to ensure the pool already has candidates.
        baseline = _three_baseline_runs()
        threshold_run = _easy_run(
            "at-threshold",
            days_ago=1,
            dist_km=10.0,
            total_duration_s=float(MIN_ENDURANCE_QUALIFYING_SESSION_SECONDS),
        )
        score_without = compute_endurance_score(baseline, _prefs(), _zc())["score"]
        result_with = compute_endurance_score(
            baseline + [threshold_run], _prefs(), _zc()
        )
        score_with = result_with["score"]
        # The threshold run must not enter the pool — score unchanged.
        assert score_without == score_with
        # The pool is unchanged so the run_contributions for this id should NOT appear.
        assert "at-threshold" not in result_with.get("run_contributions", {})

    def test_run_below_threshold_is_excluded(self):
        """A session duration < threshold must not contribute to the endurance pool."""
        baseline = _three_baseline_runs()
        short_run = _easy_run(
            "too-short",
            days_ago=1,
            dist_km=2.0,
            total_duration_s=float(MIN_ENDURANCE_QUALIFYING_SESSION_SECONDS) - 1.0,
        )
        result = compute_endurance_score(baseline + [short_run], _prefs(), _zc())
        assert "too-short" not in result.get("run_contributions", {})

    def test_run_just_above_threshold_qualifies(self):
        """A session duration strictly > threshold must be allowed into the pool."""
        baseline = _three_baseline_runs()
        long_run = _easy_run(
            "just-above",
            days_ago=1,
            # pace 360 s/km × 7 km = 2520 s > 2400
            dist_km=7.0,
            pace_s_per_km=360.0,
        )
        assert long_run["duration_seconds"] > MIN_ENDURANCE_QUALIFYING_SESSION_SECONDS
        result = compute_endurance_score(baseline + [long_run], _prefs(), _zc())
        assert "just-above" in result.get("run_contributions", {})


# ---------------------------------------------------------------------------
# AC3: Regression — aborted interval session must not raise Endurance
# ---------------------------------------------------------------------------

class TestAbortedIntervalSessionDoesNotRaiseEndurance:
    """The a1d6a936 scenario: aborted interval session must leave Endurance unchanged."""

    def _aborted_interval_run(self) -> dict:
        """Interval session cut short: total 15 min, has a hard lap + easy warmup."""
        d = (_TODAY - timedelta(days=1)).isoformat()
        return {
            "run_id": "aborted-interval",
            "workout_date": d,
            "laps": [
                # Easy warmup lap — would contribute to Endurance pool if admitted.
                {
                    "band": "easy",
                    "avg_power": 170.0,
                    "avg_hr": 130.0,
                    "distance_km": 1.5,
                    "duration_seconds": 540.0,  # 9 min
                },
                # Hard interval lap cut short.
                {
                    "band": "hard",
                    "avg_power": 280.0,
                    "avg_hr": 175.0,
                    "distance_km": 1.0,
                    "duration_seconds": 360.0,  # 6 min
                },
            ],
            "decoupling_pct": None,
            "avg_power": 225.0,
            "avg_hr": 152.0,
            "distance_km": 2.5,
            "duration_seconds": 900.0,  # 15 min total — below 40 min guard
        }

    def test_endurance_does_not_rise_from_aborted_session(self):
        """Adding an aborted session must not increase the Endurance score."""
        baseline = _three_baseline_runs()
        score_before = compute_endurance_score(baseline, _prefs(), _zc())["score"]
        score_after = compute_endurance_score(
            baseline + [self._aborted_interval_run()], _prefs(), _zc()
        )["score"]
        assert score_after <= score_before + 0.01, (
            f"Endurance rose from aborted session: {score_before} → {score_after}"
        )

    def test_aborted_session_not_in_pool(self):
        """Aborted interval run must not appear in run_contributions."""
        baseline = _three_baseline_runs()
        result = compute_endurance_score(
            baseline + [self._aborted_interval_run()], _prefs(), _zc()
        )
        assert "aborted-interval" not in result.get("run_contributions", {})

    def test_endurance_score_still_present_and_valid(self):
        """Endurance score remains valid (not building_baseline) after aborted session."""
        baseline = _three_baseline_runs()
        result = compute_endurance_score(
            baseline + [self._aborted_interval_run()], _prefs(), _zc()
        )
        assert "score" in result
        assert result.get("state") != "building_baseline"
        assert 0 <= result["score"] <= 100


# ---------------------------------------------------------------------------
# AC4: Detraining decay — stale history scores lower
# ---------------------------------------------------------------------------

class TestEnduranceDetrainingDecay:
    """Stale runs decay and the Endurance score falls below the fresh-run level."""

    def _runs_at_age(self, days_ago_base: int) -> list[dict]:
        """Three identical easy long runs, all at the given age offset."""
        return [
            _easy_run(f"d{i}", days_ago=days_ago_base + i * 7)
            for i in range(_MIN_RUNS)
        ]

    def test_fresh_runs_score_higher_than_stale(self):
        """Fresh runs (within grace) score higher than the same runs after decay."""
        score_fresh = compute_endurance_score(
            self._runs_at_age(days_ago_base=1), _prefs(), _zc()
        )["score"]
        score_stale = compute_endurance_score(
            self._runs_at_age(days_ago_base=35), _prefs(), _zc()
        )["score"]
        assert score_stale < score_fresh, (
            f"stale score {score_stale} should be < fresh score {score_fresh}"
        )

    def test_score_flat_within_grace_window(self):
        """Inside the 2-week grace, the score should barely move."""
        s1 = compute_endurance_score(self._runs_at_age(1), _prefs(), _zc())["score"]
        s2 = compute_endurance_score(self._runs_at_age(14), _prefs(), _zc())["score"]
        # Grace ± 1 pt tolerance; the consistency bonus can change slightly
        # because sessions are aging out of the 28-day window.
        assert abs(s1 - s2) < 2.5, f"too much movement inside grace: {s1} vs {s2}"

    def test_score_falls_after_grace(self):
        """Score at 3 weeks must be below score at 2 weeks (grace boundary)."""
        s_grace = compute_endurance_score(self._runs_at_age(14), _prefs(), _zc())["score"]
        s_past = compute_endurance_score(self._runs_at_age(21), _prefs(), _zc())["score"]
        assert s_past < s_grace, (
            f"Endurance should fall after grace: grace={s_grace}, 3wk={s_past}"
        )

    def test_anchor_decay_rate_endurance(self):
        """Anchor decay is ~1.5 pts/week once the consistency bonus has faded.

        We compare weeks 5→6 where the 28-day consistency window is empty for
        both, isolating the pure anchor decay (1.5 pts/week by design).
        """
        s_5wk = compute_endurance_score(self._runs_at_age(35), _prefs(), _zc())["score"]
        s_6wk = compute_endurance_score(self._runs_at_age(42), _prefs(), _zc())["score"]
        assert abs((s_5wk - s_6wk) - 1.5) < 0.5, (
            f"anchor decay off: 5wk={s_5wk}, 6wk={s_6wk}, diff={s_5wk - s_6wk}"
        )


# ---------------------------------------------------------------------------
# AC5: formula_version bumped
# ---------------------------------------------------------------------------

class TestFormulaVersionBumped:
    """_PERF_FORMULA_VERSION in main.py must be bumped past vdot-v11."""

    def test_formula_version_not_vdot_v11(self):
        """After this issue, the formula version must be past vdot-v11."""
        from backend.main import _PERF_FORMULA_VERSION  # noqa: PLC0415
        assert _PERF_FORMULA_VERSION != "vdot-v11", (
            "Formula version must be bumped from vdot-v11 (issue #1364)"
        )

    def test_formula_version_is_string(self):
        from backend.main import _PERF_FORMULA_VERSION  # noqa: PLC0415
        assert isinstance(_PERF_FORMULA_VERSION, str) and _PERF_FORMULA_VERSION


# ---------------------------------------------------------------------------
# AC6: Anchoring math — proposal examples land in the expected band
# ---------------------------------------------------------------------------

class TestEnduranceAnchoringMath:
    """Endurance VDOT anchoring places real-world easy runs in a sensible spread.

    These are order-of-magnitude sanity checks: a slow aerobic run should score
    lower than a faster one at the same HR, and neither should be ≤ 0 or ≥ 100
    for a typical recreational athlete.
    """

    def _long_easy_run(
        self, run_id: str, days_ago: int, pace_s_per_km: float, avg_hr: float
    ) -> dict:
        """Easy run long enough to pass the guard (10 km at the given pace)."""
        dist_km = 10.0
        dur = pace_s_per_km * dist_km
        d = (_TODAY - timedelta(days=days_ago)).isoformat()
        return {
            "run_id": run_id,
            "workout_date": d,
            "laps": [
                {
                    "band": "easy",
                    "avg_power": 170.0,
                    "avg_hr": avg_hr,
                    "distance_km": dist_km,
                    "duration_seconds": dur,
                }
            ],
            "decoupling_pct": 3.0,
            "avg_power": 170.0,
            "avg_hr": avg_hr,
            "distance_km": dist_km,
            "duration_seconds": dur,
        }

    def test_faster_pace_at_same_hr_scores_higher(self):
        """Faster pace at the same HR → higher HR-extrapolated VDOT → higher score."""
        # Three slow runs, then one fast run at same HR.
        slow_baseline = [
            self._long_easy_run(f"s{i}", days_ago=20 + i * 7, pace_s_per_km=480.0, avg_hr=140.0)
            for i in range(_MIN_RUNS)
        ]
        fast_baseline = [
            self._long_easy_run(f"f{i}", days_ago=20 + i * 7, pace_s_per_km=360.0, avg_hr=140.0)
            for i in range(_MIN_RUNS)
        ]
        score_slow = compute_endurance_score(slow_baseline, _prefs(), _zc())["score"]
        score_fast = compute_endurance_score(fast_baseline, _prefs(), _zc())["score"]
        assert score_fast > score_slow, (
            f"faster pace should score higher: slow={score_slow}, fast={score_fast}"
        )

    def test_lower_hr_at_same_pace_scores_higher(self):
        """Lower HR at the same pace → HR ratio closer to 1.0 → higher VDOT → higher score."""
        low_hr_runs = [
            self._long_easy_run(f"l{i}", days_ago=20 + i * 7, pace_s_per_km=420.0, avg_hr=130.0)
            for i in range(_MIN_RUNS)
        ]
        high_hr_runs = [
            self._long_easy_run(f"h{i}", days_ago=20 + i * 7, pace_s_per_km=420.0, avg_hr=155.0)
            for i in range(_MIN_RUNS)
        ]
        score_low_hr = compute_endurance_score(low_hr_runs, _prefs(), _zc())["score"]
        score_high_hr = compute_endurance_score(high_hr_runs, _prefs(), _zc())["score"]
        assert score_low_hr > score_high_hr, (
            f"lower HR should score higher: low={score_low_hr}, high={score_high_hr}"
        )

    def test_scores_land_in_meaningful_band(self):
        """Typical recreational easy runs score between 5 and 80 (not 0 or 100)."""
        runs = [
            self._long_easy_run(f"r{i}", days_ago=10 + i * 7, pace_s_per_km=420.0, avg_hr=140.0)
            for i in range(_MIN_RUNS)
        ]
        result = compute_endurance_score(runs, _prefs(), _zc())
        assert "score" in result, result.get("state")
        assert 5.0 < result["score"] < 80.0, (
            f"score {result['score']} outside expected recreational band"
        )
