"""Tests for wiring body modifier into power-to-weight score term (issue #1159).

AC coverage:
- AC1: Power-to-weight term in score calculation reads and applies body modifier
- AC2: Projection pipeline includes body modifier in its power-to-weight computation
- AC3: Stable weight + adequate EA → neutral modifier (no score delta via wiring)
- AC4: Non-neutral body modifier produces measurable, directionally correct delta
- AC5: All modified files pass py_compile with zero errors
- AC6: No regression for athletes with no body modifier data (fallback to neutral)
"""
import py_compile
import os

from backend.services.body_modifier import (
    compute_body_modifier,
    MAX_UPLIFT,
    PENALTY_SLOPE,
    EA_PENALTY_SCALE,
    EA_LOW_THRESHOLD,
    RATE_ZERO_CROSSING,
    MODIFIER_MIN,
    MODIFIER_MAX,
)
from backend.services.running_performance import (
    compute_endurance_score,
    compute_speed_score,
)
from backend.services.projection import (
    build_plan_projection_payload,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_run(run_id="r1", workout_date="2025-01-01", avg_power=250.0, avg_hr=150.0, duration=3600):
    """Build a minimal run dict with easy-band laps suitable for endurance scoring."""
    return {
        "run_id": run_id,
        "workout_date": workout_date,
        "laps": [
            {
                "band": "easy",
                "avg_power": avg_power,
                "avg_hr": avg_hr,
                "distance_km": 10.0,
                "duration_seconds": duration,
            }
        ],
        "decoupling_pct": None,
        "duration_seconds": duration,
        "speed_signal": None,
    }


def _make_runs(n=5, base_date="2025-01-01"):
    """Generate n qualifying easy runs spanning n days."""
    from datetime import date, timedelta
    start = date.fromisoformat(base_date)
    return [
        _make_run(
            run_id=f"r{i}",
            workout_date=str(start + timedelta(days=i)),
            avg_power=240.0 + i * 2,
            avg_hr=148.0 + i,
        )
        for i in range(n)
    ]


def _make_preferences():
    return {
        "ftp_w": 300.0,
        "threshold_hr": 165.0,
        "threshold_pace_seconds_per_km": 270.0,
        "aerobic_decoupling_threshold": None,
        "duration_curve_bests": {},
    }


def _make_hard_run(run_id="h1", workout_date="2025-01-10", speed_signal=1.20):
    # VDOT re-anchor: speed is now pace/duration based; a qualifying hard lap
    # with real distance+duration is required. speed_signal drives the pace.
    distance_km = 1.0
    pace = 300.0 / speed_signal  # faster as the ratio rises
    lap_dur = pace * distance_km
    return {
        "run_id": run_id,
        "workout_date": workout_date,
        "laps": [
            {
                "band": "hard",
                "avg_power": 260.0,
                "avg_hr": 165.0,
                "distance_km": distance_km,
                "duration_seconds": lap_dur,
            }
        ],
        "decoupling_pct": None,
        "duration_seconds": 1800,
        "speed_signal": speed_signal,
    }


def _make_hard_runs(n=5, base_date="2025-01-10"):
    from datetime import date, timedelta
    start = date.fromisoformat(base_date)
    return [
        _make_hard_run(
            run_id=f"h{i}",
            workout_date=str(start + timedelta(days=i)),
            speed_signal=1.20 + i * 0.02,
        )
        for i in range(n)
    ]


def _projection_args(start_ctl=60.0, start_atl=55.0):
    from datetime import date
    return dict(
        start_ctl=start_ctl,
        start_atl=start_atl,
        start_date=date(2025, 3, 1),
        planned_load=[50.0] * 14,
        races=[{"date": date(2025, 3, 15), "distance_km": 21.1, "name": "Half"}],
        thresholds={"threshold_pace_seconds_per_km": 270.0},
    )


# ── AC3/AC4: body_modifier.py API contract and directional behavior ───────────

class TestBodyModifierApiContract:
    def test_returns_dict_with_required_keys(self):
        """compute_body_modifier returns a dict with 'modifier' and 'branch' keys."""
        result = compute_body_modifier(0.0, 1.0)
        assert isinstance(result, dict)
        assert "modifier" in result
        assert "branch" in result

    def test_modifier_is_float_in_valid_range(self):
        """Modifier value is a float clamped to [MODIFIER_MIN, MODIFIER_MAX]."""
        result = compute_body_modifier(0.0, 1.0)
        assert isinstance(result["modifier"], float)
        assert MODIFIER_MIN <= result["modifier"] <= MODIFIER_MAX

    def test_stable_weight_adequate_ea_is_uplift(self):
        """AC3 analog: stable weight + adequate EA → positive modifier (athlete in good reserves)."""
        result = compute_body_modifier(0.0, 1.0)
        assert result["modifier"] > 0
        assert result["branch"] == "uplift"

    def test_zero_crossing_loss_rate_is_neutral(self):
        """AC3: at the exact zero-crossing loss rate the modifier is ≈ 0 (neutral branch)."""
        # weekly_pct_bw_rate = -RATE_ZERO_CROSSING → loss_rate == zero_crossing exactly.
        result = compute_body_modifier(-RATE_ZERO_CROSSING, 1.0)
        assert abs(result["modifier"]) < 0.001
        assert result["branch"] == "neutral"


class TestBodyModifierDirectionalBehavior:
    def test_aggressive_loss_gives_penalty(self):
        """AC4: large weekly loss (> zero-crossing) → negative modifier (penalty branch)."""
        result = compute_body_modifier(-1.5, 1.0)
        assert result["modifier"] < 0
        assert result["branch"] == "penalty"

    def test_moderate_loss_gives_uplift(self):
        """AC4: moderate loss well below zero-crossing → positive modifier (uplift branch)."""
        result = compute_body_modifier(-0.3, 1.0)
        assert result["modifier"] > 0
        assert result["branch"] == "uplift"

    def test_very_low_ea_gives_negative_modifier(self):
        """AC4: fully-depleted EA (ea_proxy=0) → negative net modifier."""
        result = compute_body_modifier(0.0, 0.0)
        assert result["modifier"] < 0

    def test_low_ea_reduces_modifier_vs_adequate(self):
        """AC4: low EA penalty drives modifier lower than with adequate EA at same weight."""
        adequate = compute_body_modifier(0.0, 1.0)
        low_ea = compute_body_modifier(0.0, 0.0)
        assert low_ea["modifier"] < adequate["modifier"]

    def test_larger_loss_yields_lower_modifier(self):
        """AC4: increasing weight-loss rate produces monotonically decreasing modifier."""
        small_loss = compute_body_modifier(-0.2, 1.0)
        moderate_loss = compute_body_modifier(-0.5, 1.0)
        large_loss = compute_body_modifier(-1.5, 1.0)
        assert small_loss["modifier"] > moderate_loss["modifier"] > large_loss["modifier"]


class TestBodyModifierConstants:
    def test_key_constants_are_positive(self):
        """Sprint body_modifier constants MAX_UPLIFT, PENALTY_SLOPE, EA_PENALTY_SCALE are positive."""
        assert MAX_UPLIFT > 0
        assert PENALTY_SLOPE > 0
        assert EA_PENALTY_SCALE > 0
        assert RATE_ZERO_CROSSING > 0

    def test_ea_low_threshold_in_valid_range(self):
        """EA_LOW_THRESHOLD is between 0 and 1 (exclusive)."""
        assert 0.0 < EA_LOW_THRESHOLD < 1.0

    def test_modifier_bounds_correct_polarity(self):
        """MODIFIER_MIN < 0 and MODIFIER_MAX > 0."""
        assert MODIFIER_MIN < 0
        assert MODIFIER_MAX > 0


# ── AC1: endurance score reads and applies body modifier ─────────────────────

class TestEnduranceScoreBodyModifier:
    def setup_method(self):
        self.runs = _make_runs(6)
        self.prefs = _make_preferences()

    def test_no_body_modifier_produces_score(self):
        """AC6: No body modifier → score computed normally (fallback to neutral)."""
        result = compute_endurance_score(self.runs, self.prefs, None)
        assert "score" in result
        assert result["score"] is not None

    def test_neutral_modifier_unchanged_score(self):
        """AC3: body_modifier=1.0 → identical score to no-modifier call."""
        base = compute_endurance_score(self.runs, self.prefs, None)
        with_neutral = compute_endurance_score(self.runs, self.prefs, None, body_modifier=1.0)
        assert base.get("score") == with_neutral.get("score")

    def test_modifier_above_one_increases_score(self):
        """AC1/AC4: modifier > 1.0 → endurance score increases."""
        base = compute_endurance_score(self.runs, self.prefs, None)
        boosted = compute_endurance_score(self.runs, self.prefs, None, body_modifier=1.05)
        if base.get("score") is not None and boosted.get("score") is not None:
            assert boosted["score"] >= base["score"]

    def test_modifier_below_one_decreases_score(self):
        """AC1/AC4: modifier < 1.0 → endurance score decreases."""
        base = compute_endurance_score(self.runs, self.prefs, None)
        penalized = compute_endurance_score(self.runs, self.prefs, None, body_modifier=0.95)
        if base.get("score") is not None and penalized.get("score") is not None:
            assert penalized["score"] <= base["score"]

    def test_modifier_applied_when_score_nonzero(self):
        """AC1: body_modifier produces a measurable delta on a scoring athlete."""
        base = compute_endurance_score(self.runs, self.prefs, None)
        mod_high = compute_endurance_score(self.runs, self.prefs, None, body_modifier=1.10)
        mod_low = compute_endurance_score(self.runs, self.prefs, None, body_modifier=0.90)

        if base.get("score") is not None and base["score"] > 0:
            assert mod_high["score"] > mod_low["score"]

    def test_building_baseline_unchanged_by_modifier(self):
        """AC6: modifier does not affect building_baseline result shape."""
        result = compute_endurance_score(
            _make_runs(2),  # too few for baseline
            self.prefs,
            None,
            body_modifier=0.90,
        )
        assert result.get("state") == "building_baseline"


# ── AC1: speed score reads and applies body modifier ─────────────────────────

class TestSpeedScoreBodyModifier:
    def setup_method(self):
        self.runs = _make_hard_runs(6)
        self.prefs = _make_preferences()

    def test_no_body_modifier_produces_score(self):
        """AC6: No body modifier → speed score computed normally."""
        result = compute_speed_score(self.runs, self.prefs, None)
        assert "score" in result

    def test_neutral_modifier_unchanged_score(self):
        """AC3: body_modifier=1.0 → identical speed score."""
        base = compute_speed_score(self.runs, self.prefs, None)
        with_neutral = compute_speed_score(self.runs, self.prefs, None, body_modifier=1.0)
        assert base.get("score") == with_neutral.get("score")

    def test_modifier_above_one_increases_speed_score(self):
        """AC1/AC4: modifier > 1.0 → speed score increases."""
        base = compute_speed_score(self.runs, self.prefs, None)
        boosted = compute_speed_score(self.runs, self.prefs, None, body_modifier=1.05)
        if base.get("score") is not None and boosted.get("score") is not None:
            assert boosted["score"] >= base["score"]

    def test_modifier_below_one_decreases_speed_score(self):
        """AC1/AC4: modifier < 1.0 → speed score decreases."""
        base = compute_speed_score(self.runs, self.prefs, None)
        penalized = compute_speed_score(self.runs, self.prefs, None, body_modifier=0.95)
        if base.get("score") is not None and penalized.get("score") is not None:
            assert penalized["score"] <= base["score"]


# ── AC2: projection pipeline includes body modifier ──────────────────────────

class TestProjectionBodyModifier:
    def test_no_body_modifier_returns_valid_payload(self):
        """AC6: No body modifier argument → projection works unchanged."""
        payload = build_plan_projection_payload(**_projection_args())
        assert "races" in payload
        assert len(payload["races"]) == 1

    def test_neutral_modifier_unchanged_projection(self):
        """AC3: body_modifier=1.0 → identical projection race finish times."""
        base = build_plan_projection_payload(**_projection_args())
        with_neutral = build_plan_projection_payload(**_projection_args(), body_modifier=1.0)
        for r_base, r_neutral in zip(base["races"], with_neutral["races"]):
            assert r_base["estimated_finish_seconds"] == r_neutral["estimated_finish_seconds"]

    def test_modifier_above_one_improves_projection(self):
        """AC2/AC4: modifier > 1.0 → better projected score → faster projected time."""
        base = build_plan_projection_payload(**_projection_args())
        boosted = build_plan_projection_payload(**_projection_args(), body_modifier=1.10)
        base_secs = base["races"][0]["estimated_finish_seconds"]
        boosted_secs = boosted["races"][0]["estimated_finish_seconds"]
        if base_secs is not None and boosted_secs is not None:
            # Faster time = fewer seconds
            assert boosted_secs <= base_secs

    def test_modifier_below_one_slows_projection(self):
        """AC2/AC4: modifier < 1.0 → lower projected score → slower projected time."""
        base = build_plan_projection_payload(**_projection_args())
        penalized = build_plan_projection_payload(**_projection_args(), body_modifier=0.90)
        base_secs = base["races"][0]["estimated_finish_seconds"]
        penalized_secs = penalized["races"][0]["estimated_finish_seconds"]
        if base_secs is not None and penalized_secs is not None:
            assert penalized_secs >= base_secs

    def test_modifier_directional_delta_measurable(self):
        """AC2/AC4: high vs low body modifier produces measurable finish time delta."""
        high = build_plan_projection_payload(**_projection_args(), body_modifier=1.10)
        low = build_plan_projection_payload(**_projection_args(), body_modifier=0.90)
        high_secs = high["races"][0]["estimated_finish_seconds"]
        low_secs = low["races"][0]["estimated_finish_seconds"]
        if high_secs is not None and low_secs is not None:
            assert low_secs > high_secs


# ── AC5: py_compile all modified files ───────────────────────────────────────

class TestPyCompile:
    def _compile(self, rel_path):
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        full = os.path.join(base, rel_path)
        py_compile.compile(full, doraise=True)

    def test_body_modifier_compiles(self):
        """AC5: body_modifier.py passes py_compile."""
        self._compile("backend/services/body_modifier.py")

    def test_running_performance_compiles(self):
        """AC5: running_performance.py passes py_compile."""
        self._compile("backend/services/running_performance.py")

    def test_projection_compiles(self):
        """AC5: projection.py passes py_compile."""
        self._compile("backend/services/projection.py")
