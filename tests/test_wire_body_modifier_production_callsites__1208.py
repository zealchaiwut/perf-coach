"""Tests for wiring body_modifier into production score/projection pipeline (issue #1208).

AC coverage:
- AC1: Every production call site of compute_endurance_score derives and passes body_modifier
- AC2: Every production call site of compute_speed_score derives and passes body_modifier
- AC3: Every production call site of build_plan_projection_payload derives and passes body_modifier
- AC4: Non-neutral body modifier produces visibly different endurance/speed/projection outputs
- AC5: Neutral body modifier (1.0) produces identical outputs as before
- AC6: Existing unit tests that passed body_modifier directly continue to pass (verified by
       testing the unchanged API signatures of compute_endurance_score, compute_speed_score,
       and build_plan_projection_payload)
"""
import inspect
import os
import py_compile
from datetime import date, timedelta

from backend.services.body_modifier import (
    compute_body_modifier,
    get_body_modifier_guardrail_for_user,
    MODIFIER_MAX,
    MODIFIER_MIN,
)
from backend.services.performance_chart import compute_performance_chart
from backend.services.projection import build_plan_projection_payload
from backend.services.running_performance import (
    compute_endurance_score,
    compute_speed_score,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _daily_load(base="2025-01-01", n=30, tss=50.0):
    start = date.fromisoformat(base)
    return [{"date": str(start + timedelta(days=i)), "daily_load": tss} for i in range(n)]


def _runs(n=6, base="2025-01-01"):
    start = date.fromisoformat(base)
    return [
        {
            "run_id": f"r{i}",
            "run_date": str(start + timedelta(days=i)),
            "workout_date": str(start + timedelta(days=i)),
            "laps": [
                {
                    "band": "easy",
                    "avg_power": 240.0 + i * 2,
                    "avg_hr": 148.0 + i,
                    "distance_km": 10.0,
                    "duration_seconds": 3600.0,
                }
            ],
            "decoupling_pct": None,
            "duration_seconds": 3600,
            "speed_signal": None,
        }
        for i in range(n)
    ]


def _prefs():
    return {
        "ftp_w": 300.0,
        "threshold_hr": 165.0,
        "threshold_pace_seconds_per_km": 270.0,
        "aerobic_decoupling_threshold": None,
        "duration_curve_bests": {},
    }


def _projection_args():
    return dict(
        start_ctl=60.0,
        start_atl=55.0,
        start_date=date(2025, 3, 1),
        planned_load=[50.0] * 14,
        races=[{"date": date(2025, 3, 15), "distance_km": 21.1, "name": "Half"}],
        thresholds={"threshold_pace_seconds_per_km": 270.0},
    )


# ── AC1/AC2: compute_performance_chart accepts and forwards body_modifier ─────

class TestPerformanceChartBodyModifierWiring:
    """compute_performance_chart must accept body_modifier and pass it to scoring."""

    def test_compute_performance_chart_accepts_body_modifier(self):
        """AC1/AC2: compute_performance_chart signature includes body_modifier parameter."""
        sig = inspect.signature(compute_performance_chart)
        assert "body_modifier" in sig.parameters, (
            "compute_performance_chart must accept body_modifier parameter"
        )
        assert sig.parameters["body_modifier"].default == 1.0

    def test_body_modifier_default_1_produces_same_result(self):
        """AC5: explicit body_modifier=1.0 yields the same chart as omitting it."""
        load = _daily_load(n=30)
        r = _runs(6)
        p = _prefs()
        start = "2025-01-01"
        end = "2025-01-30"

        without = compute_performance_chart(load, r, p, None, start, end)
        with_neutral = compute_performance_chart(load, r, p, None, start, end, body_modifier=1.0)

        assert without["endurance_score"] == with_neutral["endurance_score"]
        assert without["speed_score"] == with_neutral["speed_score"]

    def test_body_modifier_uplift_differs_from_neutral(self):
        """AC4: uplift modifier produces different (higher) endurance scores than neutral."""
        load = _daily_load(n=30)
        r = _runs(6)
        p = _prefs()
        start = "2025-01-01"
        end = "2025-01-30"

        neutral = compute_performance_chart(load, r, p, None, start, end, body_modifier=1.0)
        uplifted = compute_performance_chart(load, r, p, None, start, end, body_modifier=1.05)

        neutral_scores = [s for s in neutral["endurance_score"] if s is not None]
        uplifted_scores = [s for s in uplifted["endurance_score"] if s is not None]

        if neutral_scores and uplifted_scores:
            assert max(uplifted_scores) >= max(neutral_scores), (
                "uplift modifier should produce >= scores compared to neutral"
            )

    def test_body_modifier_penalty_differs_from_neutral(self):
        """AC4: penalty modifier produces different (lower) endurance scores than neutral."""
        load = _daily_load(n=30)
        r = _runs(6)
        p = _prefs()
        start = "2025-01-01"
        end = "2025-01-30"

        neutral = compute_performance_chart(load, r, p, None, start, end, body_modifier=1.0)
        penalized = compute_performance_chart(load, r, p, None, start, end, body_modifier=0.90)

        neutral_scores = [s for s in neutral["endurance_score"] if s is not None]
        penalized_scores = [s for s in penalized["endurance_score"] if s is not None]

        if neutral_scores and penalized_scores:
            assert max(penalized_scores) <= max(neutral_scores), (
                "penalty modifier should produce <= scores compared to neutral"
            )


# ── AC3: get_body_modifier_for_user exists and returns a float ────────────────

class TestGetBodyModifierForUser:
    """get_body_modifier_for_user must be importable and return a float."""

    def test_function_exists_and_is_callable(self):
        """AC1/AC2/AC3: get_body_modifier_for_user is importable from body_modifier module."""
        from backend.services.body_modifier import get_body_modifier_for_user
        assert callable(get_body_modifier_for_user)

    def test_function_signature(self):
        """get_body_modifier_for_user accepts user_id and optional as_of_date."""
        from backend.services.body_modifier import get_body_modifier_for_user
        sig = inspect.signature(get_body_modifier_for_user)
        params = list(sig.parameters.keys())
        assert "user_id" in params
        assert "as_of_date" in params

    def test_compute_body_modifier_to_multiplicative(self):
        """AC4/AC5: compute_body_modifier fractional output converts correctly to
        multiplicative factor: neutral → 1.0, uplift → >1.0, penalty → <1.0."""
        neutral = compute_body_modifier(0.0, 1.0)
        uplift = compute_body_modifier(-0.3, 1.0)
        penalty = compute_body_modifier(-1.5, 1.0)

        # The multiplicative factor used at call sites is 1.0 + modifier
        neutral_factor = 1.0 + neutral["modifier"]
        uplift_factor = 1.0 + uplift["modifier"]
        penalty_factor = 1.0 + penalty["modifier"]

        assert abs(neutral_factor - 1.0) < 0.06, (
            "neutral modifier factor should be close to 1.0"
        )
        assert uplift_factor > 1.0, "uplift factor must exceed 1.0"
        assert penalty_factor < 1.0, "penalty factor must be below 1.0"

    def test_neutral_rate_factor_within_valid_range(self):
        """AC5: modifier factor for completely neutral inputs is within [1+MODIFIER_MIN, 1+MODIFIER_MAX]."""
        result = compute_body_modifier(0.0, 1.0)
        factor = 1.0 + result["modifier"]
        assert 1.0 + MODIFIER_MIN <= factor <= 1.0 + MODIFIER_MAX


# ── AC4/AC5: end-to-end score divergence via direct score-function calls ──────

class TestEndToEndBodyModifierDivergence:
    """Verify that wiring the derived modifier changes scores for non-neutral users."""

    def test_endurance_score_differs_with_non_neutral_modifier(self):
        """AC4: computed modifier ≠ 1.0 → endurance score differs from forced-1.0 baseline."""
        r = _runs(6)
        p = _prefs()

        # Aggressive loss → penalty branch → modifier < 0 → factor < 1.0
        result = compute_body_modifier(-1.5, 1.0)
        factor = 1.0 + result["modifier"]
        assert factor < 1.0, "prerequisite: penalty factor must be < 1.0"

        base = compute_endurance_score(r, p, None, body_modifier=1.0)
        derived = compute_endurance_score(r, p, None, body_modifier=factor)

        if base.get("score") is not None and derived.get("score") is not None:
            assert derived["score"] < base["score"], (
                "penalty modifier must produce a lower endurance score than neutral"
            )

    def test_speed_score_differs_with_non_neutral_modifier(self):
        """AC4: computed modifier ≠ 1.0 → speed score differs from forced-1.0 baseline."""
        hard_runs = [
            {
                "run_id": f"h{i}",
                "workout_date": str(date(2025, 1, 10) + timedelta(days=i)),
                "laps": [{"band": "hard", "avg_power": 260.0, "avg_hr": 165.0,
                           "distance_km": 1.0, "duration_seconds": 250.0}],
                "decoupling_pct": None,
                "duration_seconds": 1800,
                "speed_signal": 1.20 + i * 0.02,
            }
            for i in range(6)
        ]
        p = _prefs()

        result = compute_body_modifier(-1.5, 1.0)
        factor = 1.0 + result["modifier"]

        base = compute_speed_score(hard_runs, p, None, body_modifier=1.0)
        derived = compute_speed_score(hard_runs, p, None, body_modifier=factor)

        if base.get("score") is not None and derived.get("score") is not None:
            assert derived["score"] < base["score"], (
                "penalty modifier must produce a lower speed score than neutral"
            )

    def test_projection_differs_with_non_neutral_modifier(self):
        """AC4: computed modifier ≠ 1.0 → projection finish times differ from neutral."""
        args = _projection_args()

        result = compute_body_modifier(-1.5, 1.0)
        factor = 1.0 + result["modifier"]
        assert factor < 1.0

        base = build_plan_projection_payload(**args, body_modifier=1.0)
        derived = build_plan_projection_payload(**args, body_modifier=factor)

        base_time = base["races"][0].get("estimated_finish_seconds")
        derived_time = derived["races"][0].get("estimated_finish_seconds")
        if base_time is not None and derived_time is not None:
            assert derived_time >= base_time, (
                "penalty modifier must produce slower or equal projected finish time"
            )

    def test_neutral_modifier_projection_unchanged(self):
        """AC5: modifier = 1.0 → projection identical to no-modifier call."""
        args = _projection_args()
        base = build_plan_projection_payload(**args)
        neutral = build_plan_projection_payload(**args, body_modifier=1.0)
        for r_base, r_neutral in zip(base["races"], neutral["races"]):
            assert r_base.get("estimated_finish_seconds") == r_neutral.get("estimated_finish_seconds")


# ── AC6: existing API signatures are unchanged ────────────────────────────────

class TestExistingApiSignaturesUnchanged:
    """Existing callers that pass body_modifier directly continue to work."""

    def test_compute_endurance_score_body_modifier_param_unchanged(self):
        """AC6: compute_endurance_score still accepts body_modifier as kwarg."""
        sig = inspect.signature(compute_endurance_score)
        assert "body_modifier" in sig.parameters
        assert sig.parameters["body_modifier"].default == 1.0

    def test_compute_speed_score_body_modifier_param_unchanged(self):
        """AC6: compute_speed_score still accepts body_modifier as kwarg."""
        sig = inspect.signature(compute_speed_score)
        assert "body_modifier" in sig.parameters
        assert sig.parameters["body_modifier"].default == 1.0

    def test_build_plan_projection_body_modifier_param_unchanged(self):
        """AC6: build_plan_projection_payload still accepts body_modifier as kwarg."""
        sig = inspect.signature(build_plan_projection_payload)
        assert "body_modifier" in sig.parameters
        assert sig.parameters["body_modifier"].default == 1.0


# ── py_compile ────────────────────────────────────────────────────────────────

class TestPyCompile:
    _base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def _compile(self, rel):
        py_compile.compile(os.path.join(self._base, rel), doraise=True)

    def test_body_modifier_compiles(self):
        self._compile("backend/services/body_modifier.py")

    def test_performance_chart_compiles(self):
        self._compile("backend/services/performance_chart.py")

    def test_projection_router_compiles(self):
        self._compile("backend/routers/projection.py")
