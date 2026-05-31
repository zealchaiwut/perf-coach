"""Tests for issue #196: compute_best_values and find_matching_workout."""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock


# ── compute_best_values ────────────────────────────────────────────────────────

def test_compute_best_values_manual_only():
    from backend.services.workout_merge import compute_best_values

    w = SimpleNamespace(
        manual_overrides=None,
        strava_activity=None,
        stryd_activity=None,
        distance_km=10.5,
        duration_seconds=3600,
        avg_hr=145,
        tss=80.0,
        name="Morning Run",
    )
    result = compute_best_values(w)
    assert result["best_distance_km"] == 10.5
    assert result["best_duration_seconds"] == 3600
    assert result["best_avg_hr"] == 145
    assert result["best_tss"] == 80.0
    assert result["best_name"] == "Morning Run"
    assert result["best_avg_power_w"] is None


def test_compute_best_values_strava_linked():
    from backend.services.workout_merge import compute_best_values

    strava = SimpleNamespace(
        distance_km=11.0,
        duration_seconds=3700,
        avg_hr=150,
        avg_power_w=220,
        name="Strava Run",
    )
    w = SimpleNamespace(
        manual_overrides=None,
        strava_activity=strava,
        stryd_activity=None,
        distance_km=10.5,
        duration_seconds=3600,
        avg_hr=145,
        tss=80.0,
        name="Morning Run",
    )
    result = compute_best_values(w)
    assert result["best_distance_km"] == 11.0
    assert result["best_duration_seconds"] == 3700
    assert result["best_avg_hr"] == 150
    assert result["best_avg_power_w"] == 220
    assert result["best_tss"] == 80.0
    assert result["best_name"] == "Strava Run"


def test_compute_best_values_both_strava_wins():
    from backend.services.workout_merge import compute_best_values

    strava = SimpleNamespace(distance_km=11.0, duration_seconds=3700, avg_hr=150, avg_power_w=220, name="Strava Run")
    stryd = SimpleNamespace(distance_km=10.8, duration_seconds=3650, avg_hr=148, avg_power_w=210, tss=85, name="Stryd Run")
    w = SimpleNamespace(
        manual_overrides=None,
        strava_activity=strava,
        stryd_activity=stryd,
        distance_km=10.5,
        duration_seconds=3600,
        avg_hr=145,
        tss=80.0,
        name="Morning Run",
    )
    result = compute_best_values(w)
    assert result["best_distance_km"] == 11.0
    assert result["best_duration_seconds"] == 3700
    assert result["best_avg_hr"] == 150
    assert result["best_avg_power_w"] == 220
    assert result["best_tss"] == 85
    assert result["best_name"] == "Strava Run"


def test_compute_best_values_manual_overrides_wins():
    from backend.services.workout_merge import compute_best_values

    strava = SimpleNamespace(distance_km=11.0, duration_seconds=3700, avg_hr=150, avg_power_w=220, name="Strava Run")
    w = SimpleNamespace(
        manual_overrides={"distance_km": 12.0, "name": "My Override"},
        strava_activity=strava,
        stryd_activity=None,
        distance_km=10.5,
        duration_seconds=3600,
        avg_hr=145,
        tss=80.0,
        name="Morning Run",
    )
    result = compute_best_values(w)
    assert result["best_distance_km"] == 12.0
    assert result["best_name"] == "My Override"
    assert result["best_duration_seconds"] == 3700
    assert result["best_avg_hr"] == 150


def test_compute_best_values_null_fallthrough():
    from backend.services.workout_merge import compute_best_values

    strava = SimpleNamespace(distance_km=None, duration_seconds=3700, avg_hr=None, avg_power_w=220, name="Strava Run")
    stryd = SimpleNamespace(distance_km=10.8, duration_seconds=None, avg_hr=148, avg_power_w=None, tss=85, name=None)
    w = SimpleNamespace(
        manual_overrides=None,
        strava_activity=strava,
        stryd_activity=stryd,
        distance_km=10.5,
        duration_seconds=3600,
        avg_hr=145,
        tss=80.0,
        name="Legacy Run",
    )
    result = compute_best_values(w)
    assert result["best_distance_km"] == 10.8
    assert result["best_duration_seconds"] == 3700
    assert result["best_avg_hr"] == 148
    assert result["best_avg_power_w"] == 220
    assert result["best_tss"] == 85
    assert result["best_name"] == "Strava Run"


# ── find_matching_workout ──────────────────────────────────────────────────────

TEST_USER_ID = "00000000-0000-0000-0000-000000000196"


def _mock_session(workouts):
    session = MagicMock()
    session.query.return_value.filter.return_value.all.return_value = workouts
    return session


def _make_workout(dt):
    w = MagicMock()
    w.start_time = dt
    return w


def test_find_matching_workout_within_tolerance():
    from backend.services.workout_merge import find_matching_workout

    target = datetime(2026, 5, 30, 9, 0, 0, tzinfo=timezone.utc)
    w = _make_workout(datetime(2026, 5, 30, 9, 3, 0, tzinfo=timezone.utc))
    result = find_matching_workout(target, TEST_USER_ID, session=_mock_session([w]))
    assert result is w


def test_find_matching_workout_outside_tolerance():
    from backend.services.workout_merge import find_matching_workout

    target = datetime(2026, 5, 30, 9, 0, 0, tzinfo=timezone.utc)
    result = find_matching_workout(target, TEST_USER_ID, session=_mock_session([]))
    assert result is None


def test_find_matching_workout_closest_of_multiple():
    from backend.services.workout_merge import find_matching_workout

    target = datetime(2026, 5, 30, 9, 0, 0, tzinfo=timezone.utc)
    w1 = _make_workout(datetime(2026, 5, 30, 9, 4, 0, tzinfo=timezone.utc))
    w2 = _make_workout(datetime(2026, 5, 30, 8, 58, 0, tzinfo=timezone.utc))
    result = find_matching_workout(target, TEST_USER_ID, session=_mock_session([w1, w2]))
    assert result is w2
