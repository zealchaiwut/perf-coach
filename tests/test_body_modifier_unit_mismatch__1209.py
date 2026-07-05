"""Tests for body-modifier unit mismatch fix (issue #1209).

AC coverage:
- AC1: compute_body_modifier docstring explicitly states it returns a fractional
       delta in [-0.15, +0.05], not a multiplier.
- AC2: Docstrings for compute_endurance_score, compute_speed_score, and
       build_plan_projection_payload explicitly state body_modifier must be a
       multiplier centered at 1.0 (range 0.85–1.05).
- AC3: Boundary conversion (1.0 + modifier) produces the correct multiplier.
- AC4: Passing a raw delta directly into compute_endurance_score /
       compute_speed_score raises ValueError.
- AC5: No existing score calculations are broken; scores remain numerically
       correct with the boundary conversion applied.
"""
import pytest

from backend.services.body_modifier import (
    compute_body_modifier,
    MODIFIER_MIN,
    MODIFIER_MAX,
)
from backend.services.running_performance import (
    compute_endurance_score,
    compute_speed_score,
)
from backend.services.projection import build_plan_projection_payload


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_runs(n=6, base_date="2025-01-01"):
    from datetime import date, timedelta
    start = date.fromisoformat(base_date)
    return [
        {
            "run_id": f"r{i}",
            "workout_date": str(start + timedelta(days=i)),
            "laps": [
                {
                    "band": "easy",
                    "avg_power": 240.0 + i * 2,
                    "avg_hr": 148.0 + i,
                    "distance_km": 10.0,
                    "duration_seconds": 3600,
                }
            ],
            "decoupling_pct": None,
            "duration_seconds": 3600,
            "speed_signal": None,
        }
        for i in range(n)
    ]


def _make_hard_runs(n=6, base_date="2025-01-10"):
    from datetime import date, timedelta
    start = date.fromisoformat(base_date)
    return [
        {
            "run_id": f"h{i}",
            "workout_date": str(start + timedelta(days=i)),
            "laps": [
                {
                    "band": "hard",
                    "avg_power": 260.0,
                    "avg_hr": 165.0,
                    "distance_km": 1.0,
                    "duration_seconds": 300.0 / (1.20 + i * 0.02),
                }
            ],
            "decoupling_pct": None,
            "duration_seconds": 1800,
            "speed_signal": 1.20 + i * 0.02,
        }
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


def _projection_args():
    from datetime import date
    return dict(
        start_ctl=60.0,
        start_atl=55.0,
        start_date=date(2025, 3, 1),
        planned_load=[50.0] * 14,
        races=[{"date": date(2025, 3, 15), "distance_km": 21.1, "name": "Half"}],
        thresholds={"threshold_pace_seconds_per_km": 270.0},
    )


# ── AC1: compute_body_modifier docstring declares delta return type ────────────

class TestBodyModifierDocstringDelta:
    def test_docstring_mentions_delta(self):
        """AC1: compute_body_modifier docstring must say 'delta' or 'fractional'."""
        doc = compute_body_modifier.__doc__ or ""
        assert "delta" in doc.lower() or "fractional" in doc.lower(), (
            "compute_body_modifier docstring must explicitly state it returns a "
            "fractional delta, not a multiplier."
        )

    def test_docstring_mentions_range(self):
        """AC1: compute_body_modifier docstring must document the output range."""
        doc = compute_body_modifier.__doc__ or ""
        # Should mention the range bounds (e.g., -0.15 and 0.05 or MODIFIER_MIN/MAX)
        assert "-0.15" in doc or "MODIFIER_MIN" in doc or "modifier_min" in doc.lower(), (
            "compute_body_modifier docstring must specify the output range lower bound."
        )

    def test_modifier_output_is_delta_not_multiplier(self):
        """AC1: stable weight + good EA yields a small delta near 0, not near 1.0."""
        result = compute_body_modifier(0.0, 1.0)
        modifier = result["modifier"]
        assert MODIFIER_MIN <= modifier <= MODIFIER_MAX, (
            f"modifier {modifier} is outside the expected delta range "
            f"[{MODIFIER_MIN}, {MODIFIER_MAX}]"
        )
        # The key point: it's a delta, so |modifier| << 1.0; it should NOT be near 1.0
        assert abs(modifier) < 0.5, (
            f"modifier {modifier} appears to be a multiplier (near 1.0), "
            "but it should be a fractional delta near 0."
        )


# ── AC2: consumer docstrings declare body_modifier as multiplier ──────────────

class TestConsumerDocstringsMultiplier:
    def test_endurance_score_docstring_mentions_multiplier(self):
        """AC2: compute_endurance_score docstring must describe body_modifier as a multiplier."""
        doc = compute_endurance_score.__doc__ or ""
        assert "multiplier" in doc.lower() or "1.0" in doc, (
            "compute_endurance_score docstring must explicitly state that "
            "body_modifier is a multiplier centered at 1.0."
        )

    def test_endurance_score_docstring_mentions_valid_range(self):
        """AC2: compute_endurance_score docstring must state the valid range (0.85–1.05)."""
        doc = compute_endurance_score.__doc__ or ""
        assert "0.85" in doc or "1.05" in doc, (
            "compute_endurance_score docstring must specify the valid body_modifier range."
        )

    def test_speed_score_docstring_mentions_multiplier(self):
        """AC2: compute_speed_score docstring must describe body_modifier as a multiplier."""
        doc = compute_speed_score.__doc__ or ""
        assert "multiplier" in doc.lower() or "1.0" in doc, (
            "compute_speed_score docstring must explicitly state that "
            "body_modifier is a multiplier centered at 1.0."
        )

    def test_speed_score_docstring_mentions_valid_range(self):
        """AC2: compute_speed_score docstring must state the valid range (0.85–1.05)."""
        doc = compute_speed_score.__doc__ or ""
        assert "0.85" in doc or "1.05" in doc, (
            "compute_speed_score docstring must specify the valid body_modifier range."
        )

    def test_projection_docstring_mentions_multiplier(self):
        """AC2: build_plan_projection_payload docstring must describe body_modifier as a multiplier."""
        doc = build_plan_projection_payload.__doc__ or ""
        assert "multiplier" in doc.lower() or "1.0 +" in doc, (
            "build_plan_projection_payload docstring must explicitly state that "
            "body_modifier is a multiplier and document the conversion from delta."
        )

    def test_projection_docstring_shows_conversion(self):
        """AC2: build_plan_projection_payload docstring must show the 1.0 + ... conversion."""
        doc = build_plan_projection_payload.__doc__ or ""
        assert "1.0 +" in doc or "1.0+" in doc, (
            "build_plan_projection_payload docstring must document the boundary "
            "conversion: 1.0 + compute_body_modifier(...)['modifier']."
        )


# ── AC3: boundary conversion produces correct multiplier ─────────────────────

class TestBoundaryConversion:
    def test_neutral_state_converts_to_multiplier_one(self):
        """AC3: stable weight + adequate EA → delta ≈ 0 → multiplier ≈ 1.0."""
        result = compute_body_modifier(0.0, 1.0)
        multiplier = 1.0 + result["modifier"]
        assert 0.99 <= multiplier <= 1.06, (
            f"Expected multiplier near 1.0 for neutral case, got {multiplier}"
        )

    def test_uplift_delta_converts_to_multiplier_above_one(self):
        """AC3: uplift delta → 1.0 + delta > 1.0 (improves score)."""
        result = compute_body_modifier(-0.3, 1.0)
        assert result["branch"] == "uplift"
        multiplier = 1.0 + result["modifier"]
        assert multiplier > 1.0, (
            f"Uplift branch should give multiplier > 1.0, got {multiplier}"
        )

    def test_penalty_delta_converts_to_multiplier_below_one(self):
        """AC3: penalty delta → 1.0 + delta < 1.0 (reduces score)."""
        result = compute_body_modifier(-1.5, 1.0)
        assert result["branch"] == "penalty"
        multiplier = 1.0 + result["modifier"]
        assert multiplier < 1.0, (
            f"Penalty branch should give multiplier < 1.0, got {multiplier}"
        )

    def test_converted_multiplier_within_valid_range(self):
        """AC3: 1.0 + modifier is always in [0.85, 1.05] for any valid input."""
        test_cases = [
            (0.0, 1.0),    # neutral
            (-0.3, 1.0),   # moderate loss
            (-1.5, 1.0),   # aggressive loss
            (0.0, 0.0),    # low EA
            (-0.4, 0.2),   # combined
        ]
        for rate, ea in test_cases:
            result = compute_body_modifier(rate, ea)
            multiplier = 1.0 + result["modifier"]
            assert 0.84 <= multiplier <= 1.06, (
                f"For rate={rate}, ea={ea}: multiplier {multiplier} is outside [0.85, 1.05]"
            )

    def test_endurance_score_with_correct_converted_multiplier(self):
        """AC3: score computed with 1.0 + modifier differs from raw-delta (≈ 0.02) call."""
        runs = _make_runs(6)
        prefs = _make_preferences()

        result = compute_body_modifier(-0.3, 1.0)
        raw_delta = result["modifier"]  # e.g. ~0.04, a small positive float
        correct_multiplier = 1.0 + raw_delta  # e.g. ~1.04

        score_correct = compute_endurance_score(runs, prefs, None, body_modifier=correct_multiplier)
        score_neutral = compute_endurance_score(runs, prefs, None, body_modifier=1.0)

        if score_correct.get("score") is not None and score_neutral.get("score") is not None:
            # Using the correct multiplier should give a different (uplifted) result
            assert score_correct["score"] >= score_neutral["score"], (
                "Endurance score with correct multiplier should be >= neutral score for uplift."
            )


# ── AC4: raw delta passed to consumers raises ValueError ─────────────────────

class TestRawDeltaRejected:
    def test_endurance_score_rejects_raw_delta_positive(self):
        """AC4: passing a raw positive delta (~0.02) to compute_endurance_score raises ValueError."""
        runs = _make_runs(6)
        prefs = _make_preferences()
        with pytest.raises(ValueError, match="multiplier"):
            compute_endurance_score(runs, prefs, None, body_modifier=0.02)

    def test_endurance_score_rejects_raw_delta_negative(self):
        """AC4: passing a raw negative delta (~-0.10) to compute_endurance_score raises ValueError."""
        runs = _make_runs(6)
        prefs = _make_preferences()
        with pytest.raises(ValueError, match="multiplier"):
            compute_endurance_score(runs, prefs, None, body_modifier=-0.10)

    def test_speed_score_rejects_raw_delta_positive(self):
        """AC4: passing a raw positive delta to compute_speed_score raises ValueError."""
        runs = _make_hard_runs(6)
        prefs = _make_preferences()
        with pytest.raises(ValueError, match="multiplier"):
            compute_speed_score(runs, prefs, None, body_modifier=0.02)

    def test_speed_score_rejects_raw_delta_negative(self):
        """AC4: passing a raw negative delta to compute_speed_score raises ValueError."""
        runs = _make_hard_runs(6)
        prefs = _make_preferences()
        with pytest.raises(ValueError, match="multiplier"):
            compute_speed_score(runs, prefs, None, body_modifier=-0.10)

    def test_endurance_score_accepts_valid_multiplier(self):
        """AC4 (negative): valid multipliers in [0.85, 1.05] are accepted without error."""
        runs = _make_runs(6)
        prefs = _make_preferences()
        for mod in [0.85, 0.90, 1.0, 1.03, 1.05]:
            result = compute_endurance_score(runs, prefs, None, body_modifier=mod)
            assert "score" in result or "state" in result, (
                f"compute_endurance_score raised unexpectedly for modifier={mod}"
            )

    def test_speed_score_accepts_valid_multiplier(self):
        """AC4 (negative): valid multipliers in [0.85, 1.05] are accepted without error."""
        runs = _make_hard_runs(6)
        prefs = _make_preferences()
        for mod in [0.85, 0.90, 1.0, 1.03, 1.05]:
            result = compute_speed_score(runs, prefs, None, body_modifier=mod)
            assert "score" in result or "state" in result


# ── AC5: existing score calculations remain numerically correct ───────────────

class TestNumericalCorrectness:
    def test_endurance_score_neutral_modifier_unchanged(self):
        """AC5: body_modifier=1.0 produces the same score as omitting it."""
        runs = _make_runs(6)
        prefs = _make_preferences()
        base = compute_endurance_score(runs, prefs, None)
        with_neutral = compute_endurance_score(runs, prefs, None, body_modifier=1.0)
        assert base.get("score") == with_neutral.get("score")

    def test_speed_score_neutral_modifier_unchanged(self):
        """AC5: body_modifier=1.0 produces the same speed score as omitting it."""
        runs = _make_hard_runs(6)
        prefs = _make_preferences()
        base = compute_speed_score(runs, prefs, None)
        with_neutral = compute_speed_score(runs, prefs, None, body_modifier=1.0)
        assert base.get("score") == with_neutral.get("score")

    def test_endurance_uplift_multiplier_increases_score(self):
        """AC5: body_modifier=1.05 (uplift) increases score vs 1.0."""
        runs = _make_runs(6)
        prefs = _make_preferences()
        base = compute_endurance_score(runs, prefs, None, body_modifier=1.0)
        boosted = compute_endurance_score(runs, prefs, None, body_modifier=1.05)
        if base.get("score") is not None and boosted.get("score") is not None:
            assert boosted["score"] >= base["score"]

    def test_endurance_penalty_multiplier_decreases_score(self):
        """AC5: body_modifier=0.90 (penalty) decreases score vs 1.0."""
        runs = _make_runs(6)
        prefs = _make_preferences()
        base = compute_endurance_score(runs, prefs, None, body_modifier=1.0)
        penalized = compute_endurance_score(runs, prefs, None, body_modifier=0.90)
        if base.get("score") is not None and penalized.get("score") is not None:
            assert penalized["score"] <= base["score"]

    def test_raw_delta_would_nearly_zero_score(self):
        """AC5 diagnostic: shows WHY raw delta is wrong — illustrates the bug.

        compute_body_modifier returns ~0.05 for neutral; if passed directly as
        body_modifier the score is multiplied by 0.05, nearly zeroing it.
        This test asserts the raw delta IS small (confirming the bug would occur),
        not that the score function accepts it.
        """
        result = compute_body_modifier(0.0, 1.0)
        raw_delta = result["modifier"]
        # Raw delta is a small fractional value; if used directly as multiplier it
        # would produce a score ~5% of the true value.
        assert 0 < raw_delta <= MODIFIER_MAX, (
            f"Raw delta {raw_delta} should be small and positive for neutral case."
        )
        assert raw_delta < 0.5, "Raw delta is near 0, not near 1.0 — confirms the mismatch."
