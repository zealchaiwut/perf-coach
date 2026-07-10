"""Tests for the score-anchored blended race estimator (Performance tab,
unit 5) — the estimate must reconcile with the End/Spd scores the athlete
sees: higher scores can never predict a slower race.

Pure functions only. See race_finish_estimator.blended_scores_estimate.
"""
from __future__ import annotations

import pytest

from backend.services.race_calibration import (
    CORRECTION_PLAUSIBLE_RANGE,
    combined_correction,
)
from backend.services.race_finish_estimator import (
    SPEED_WEIGHT_MAX,
    SPEED_WEIGHT_MIN,
    blended_scores_estimate,
    speed_weight_for_distance,
)

_THRESH = {"threshold_pace_seconds_per_km": 330}


def test_speed_weight_half_is_midpoint():
    assert speed_weight_for_distance(21.1) == pytest.approx(0.5, abs=0.01)


def test_speed_weight_leans_speed_for_short_endurance_for_long():
    assert speed_weight_for_distance(10.0) > 0.5
    assert speed_weight_for_distance(42.2) < 0.5
    assert SPEED_WEIGHT_MIN <= speed_weight_for_distance(1.0) <= SPEED_WEIGHT_MAX
    assert SPEED_WEIGHT_MIN <= speed_weight_for_distance(100.0) <= SPEED_WEIGHT_MAX


def test_higher_scores_never_predict_slower():
    """The reported paradox class: End 36/Spd 49 must estimate FASTER than
    End 32/Spd 35 at the same distance — monotonicity in both scores."""
    low = blended_scores_estimate(32, 35, 21.1, _THRESH)
    high = blended_scores_estimate(36, 49, 21.1, _THRESH)
    assert high["estimated_finish_seconds"] < low["estimated_finish_seconds"]


def test_operator_scenario_backtest_is_near_actual():
    """At the May 31 race the athlete's scores were End 32 / Spd 35 and the
    actual result was 2:19:26 (8366 s) over 21.45 km. The score-anchored
    estimate must land in the same neighbourhood (raw model within ~10%;
    the calibration correction then absorbs the residual)."""
    r = blended_scores_estimate(32, 35, 21.45, _THRESH)
    assert r["estimated_finish_seconds"] == pytest.approx(8366, rel=0.10)


def test_basis_decomposition_is_returned_and_consistent():
    r = blended_scores_estimate(36, 49, 21.1, _THRESH)
    b = r["basis"]
    assert b is not None
    # Speed pace faster than endurance pace (higher score, shorter-effort anchor).
    assert b["speed_pace_seconds_per_km"] < b["endurance_pace_seconds_per_km"]
    # Blended pace strictly between the two anchors.
    assert b["speed_pace_seconds_per_km"] < b["blended_pace_seconds_per_km"] < b["endurance_pace_seconds_per_km"]
    # finish == blended pace × distance (within rounding).
    assert r["estimated_finish_seconds"] == pytest.approx(b["blended_pace_seconds_per_km"] * 21.1, rel=0.01)


def test_missing_speed_score_degenerates_to_endurance_only():
    r = blended_scores_estimate(36, None, 21.1, _THRESH)
    b = r["basis"]
    assert b["speed_weight"] == 0.0
    assert r["estimated_finish_seconds"] == pytest.approx(b["endurance_pace_seconds_per_km"] * 21.1, rel=0.01)


def test_missing_endurance_score_returns_null():
    r = blended_scores_estimate(None, 49, 21.1, _THRESH)
    assert r["estimated_finish_seconds"] is None


# ── Outlier guard on calibration corrections ─────────────────────────────────

def test_implausible_correction_excluded_from_blend():
    """A cold-start backcast disaster (seen live: predicted 2:42, actual
    1:51 → correction 0.69) must not enter the blend — it measures a broken
    backcast, not model bias."""
    from datetime import date, timedelta
    today = date(2026, 7, 10)
    cals = [
        {"race_date": today - timedelta(days=40), "distance_km": 21.45, "correction": 0.959},
        {"race_date": today - timedelta(days=55), "distance_km": 16.64, "correction": 0.686},  # outside range
    ]
    assert not (CORRECTION_PLAUSIBLE_RANGE[0] <= 0.686)
    out = combined_correction(cals, 21.1, today=today)
    assert out["n"] == 1
    assert out["correction"] == pytest.approx(0.959, abs=0.005)
