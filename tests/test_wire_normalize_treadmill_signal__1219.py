"""Tests for wiring normalize_treadmill_signal into the pipeline (issue #1219).

AC coverage:
  AC1 — normalize_treadmill_signal is called at the single canonical point
         (_apply_stryd_metrics in reconcile.py), not duplicated elsewhere.
  AC2 — After processing a treadmill activity (grade_percent set), the workout
         record contains a non-null flat_equivalent_pace derived from compute_ngp.
  AC3 — Non-treadmill activities (grade_percent absent/None) are unaffected;
         flat_equivalent_pace remains None.
  AC4 — flat_equivalent_pace is persisted on the Workout ORM object.
  AC5 — flat_equivalent_pace appears in the API response (_workout_dict).
  AC6 — Existing unit tests for normalize_treadmill_signal / compute_ngp pass unchanged.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

# ── helpers ───────────────────────────────────────────────────────────────────

def _stryd_act(grade_percent=None, distance_km=5.0, duration_seconds=1800,
               avg_power_w=250, form_metrics=None):
    """Build a SimpleNamespace mimicking a StrydActivity ORM row."""
    return SimpleNamespace(
        avg_power_w=avg_power_w,
        form_metrics=form_metrics or {},
        grade_percent=grade_percent,
        distance_km=distance_km,
        duration_seconds=duration_seconds,
    )


def _workout():
    """Build a minimal mutable namespace mimicking a Workout ORM row."""
    return SimpleNamespace(
        avg_power=None,
        max_power=None,
        np=None,
        avg_cadence_spm=None,
        avg_stride_m=None,
        flat_equivalent_pace=None,
    )


# ── AC1 + AC2: treadmill activity gets flat_equivalent_pace ──────────────────

def test_apply_stryd_metrics_sets_flat_equivalent_pace_for_treadmill():
    """_apply_stryd_metrics must set flat_equivalent_pace when grade_percent is present (AC1, AC2)."""
    from backend.services.reconcile import _apply_stryd_metrics

    # 5 km in 1800 s → 360 s/km average pace, 5% incline
    act = _stryd_act(grade_percent=5.0, distance_km=5.0, duration_seconds=1800)
    workout = _workout()
    _apply_stryd_metrics(workout, act)

    assert workout.flat_equivalent_pace is not None, (
        "flat_equivalent_pace must be set after processing a treadmill activity"
    )
    assert isinstance(workout.flat_equivalent_pace, float)


def test_flat_equivalent_pace_matches_compute_ngp():
    """flat_equivalent_pace must equal compute_ngp(raw_pace, grade) within tolerance (AC2)."""
    from backend.services.reconcile import _apply_stryd_metrics
    from backend.services.treadmill_ngp import compute_ngp

    distance_km = 5.0
    duration_seconds = 1800  # 360 s/km
    grade_percent = 5.0
    raw_pace = float(duration_seconds) / distance_km  # 360.0

    act = _stryd_act(grade_percent=grade_percent, distance_km=distance_km,
                     duration_seconds=duration_seconds)
    workout = _workout()
    _apply_stryd_metrics(workout, act)

    expected = compute_ngp(raw_pace_seconds_per_km=raw_pace, grade_percent=grade_percent)
    assert workout.flat_equivalent_pace == pytest.approx(expected, abs=0.01), (
        f"flat_equivalent_pace {workout.flat_equivalent_pace:.2f} must equal "
        f"compute_ngp({raw_pace}, {grade_percent}) = {expected:.2f}"
    )


def test_flat_equivalent_pace_faster_than_raw_pace_on_incline():
    """flat_equivalent_pace (lower s/km) must be strictly faster than raw pace for positive grade (AC2)."""
    from backend.services.reconcile import _apply_stryd_metrics

    distance_km = 8.0
    duration_seconds = 2880  # 360 s/km
    act = _stryd_act(grade_percent=3.0, distance_km=distance_km, duration_seconds=duration_seconds)
    workout = _workout()
    _apply_stryd_metrics(workout, act)

    raw_pace = float(duration_seconds) / distance_km
    assert workout.flat_equivalent_pace < raw_pace, (
        "flat_equivalent_pace must be faster (lower s/km) than raw pace for a positive incline"
    )


# ── AC3: non-treadmill activity leaves flat_equivalent_pace unchanged ─────────

def test_apply_stryd_metrics_no_grade_leaves_fep_none():
    """Non-treadmill activity (no grade_percent) must not set flat_equivalent_pace (AC3)."""
    from backend.services.reconcile import _apply_stryd_metrics

    act = _stryd_act(grade_percent=None, distance_km=10.0, duration_seconds=3600)
    workout = _workout()
    _apply_stryd_metrics(workout, act)

    assert workout.flat_equivalent_pace is None, (
        "flat_equivalent_pace must remain None for an activity without grade_percent"
    )


def test_apply_stryd_metrics_zero_grade_still_sets_fep():
    """grade_percent=0 (flat treadmill) must set flat_equivalent_pace equal to raw pace (AC2, AC3)."""
    from backend.services.reconcile import _apply_stryd_metrics

    distance_km = 5.0
    duration_seconds = 1800  # 360 s/km
    act = _stryd_act(grade_percent=0.0, distance_km=distance_km, duration_seconds=duration_seconds)
    workout = _workout()
    _apply_stryd_metrics(workout, act)

    raw_pace = float(duration_seconds) / distance_km
    assert workout.flat_equivalent_pace is not None
    assert workout.flat_equivalent_pace == pytest.approx(raw_pace, abs=0.01), (
        "flat treadmill (grade=0) must yield flat_equivalent_pace == raw_pace"
    )


def test_apply_stryd_metrics_missing_distance_skips_fep():
    """Missing distance_km prevents pace computation; flat_equivalent_pace must stay None (AC3 robustness)."""
    from backend.services.reconcile import _apply_stryd_metrics

    act = _stryd_act(grade_percent=5.0, distance_km=None, duration_seconds=1800)
    workout = _workout()
    _apply_stryd_metrics(workout, act)

    assert workout.flat_equivalent_pace is None


def test_apply_stryd_metrics_missing_duration_skips_fep():
    """Missing duration_seconds prevents pace computation; flat_equivalent_pace must stay None (AC3 robustness)."""
    from backend.services.reconcile import _apply_stryd_metrics

    act = _stryd_act(grade_percent=5.0, distance_km=5.0, duration_seconds=None)
    workout = _workout()
    _apply_stryd_metrics(workout, act)

    assert workout.flat_equivalent_pace is None


# ── AC4: persisted on the ORM object ─────────────────────────────────────────

def test_flat_equivalent_pace_written_to_workout_attribute():
    """flat_equivalent_pace is set as an attribute on the Workout object (AC4 persistence contract)."""
    from backend.services.reconcile import _apply_stryd_metrics

    act = _stryd_act(grade_percent=8.0, distance_km=6.0, duration_seconds=1980)
    workout = _workout()
    _apply_stryd_metrics(workout, act)

    assert hasattr(workout, "flat_equivalent_pace")
    assert workout.flat_equivalent_pace is not None


def test_two_treadmill_activities_different_grades_yield_different_fep():
    """Two activities with different grade profiles yield different flat_equivalent_pace values (AC4, UAT4)."""
    from backend.services.reconcile import _apply_stryd_metrics

    # Same raw pace (360 s/km), different inclines
    act_low = _stryd_act(grade_percent=2.0, distance_km=5.0, duration_seconds=1800)
    act_high = _stryd_act(grade_percent=8.0, distance_km=5.0, duration_seconds=1800)

    workout_low = _workout()
    workout_high = _workout()

    _apply_stryd_metrics(workout_low, act_low)
    _apply_stryd_metrics(workout_high, act_high)

    assert workout_low.flat_equivalent_pace is not None
    assert workout_high.flat_equivalent_pace is not None
    assert workout_high.flat_equivalent_pace < workout_low.flat_equivalent_pace, (
        "Steeper incline (8%) must yield a faster (lower) flat_equivalent_pace than 2%"
    )


# ── AC5: exposed in API response ─────────────────────────────────────────────

def test_workout_dict_includes_flat_equivalent_pace_when_set():
    """_workout_dict must include flat_equivalent_pace in its output dict (AC5)."""
    from backend.main import _workout_dict

    _dt = __import__("datetime")

    def _mock_workout(flat_equivalent_pace, workout_id="00000000-0000-0000-0000-000000000001"):
        return SimpleNamespace(
            id=workout_id,
            user_id="00000000-0000-0000-0000-000000000002",
            name="Treadmill Run",
            workout_date=_dt.date(2026, 7, 1),
            workout_type="run",
            run_subtype=None,
            remarks=None,
            tss=None,
            tss_source=None,
            tss_method=None,
            source="stryd",
            strava_activity_pk=None,
            stryd_activity_pk=None,
            strava_activity_url=None,
            distance_km=5.0,
            duration_seconds=1800,
            avg_hr=None,
            max_hr=None,
            elevation_m=None,
            zone2_minutes=None,
            avg_power=250,
            max_power=None,
            np=None,
            avg_cadence_spm=None,
            avg_stride_m=None,
            temperature_c=None,
            humidity_pct=None,
            feeling=None,
            created_at=None,
            strava_activity=None,
            flat_equivalent_pace=flat_equivalent_pace,
            speed_signal=None,
            speed_signal_basis=None,
            speed_signal_window_seconds=None,
            endurance_signal=None,
            decoupling_percent=None,
            efficiency_first_half=None,
            efficiency_second_half=None,
            endurance_signal_source=None,
            manual_overrides=None,
        )

    w = _mock_workout(276.5)
    result = _workout_dict(w, exercises=[])
    assert "flat_equivalent_pace" in result, (
        "flat_equivalent_pace must appear in _workout_dict output"
    )
    assert result["flat_equivalent_pace"] == pytest.approx(276.5, abs=0.01)


def test_workout_dict_flat_equivalent_pace_null_for_non_treadmill():
    """_workout_dict must return flat_equivalent_pace=None for non-treadmill workouts (AC5)."""
    from backend.main import _workout_dict
    import datetime as _dt

    w = SimpleNamespace(
        id="00000000-0000-0000-0000-000000000003",
        user_id="00000000-0000-0000-0000-000000000004",
        name="Outdoor Run",
        workout_date=_dt.date(2026, 7, 2),
        workout_type="run",
        run_subtype=None,
        remarks=None,
        tss=None,
        tss_source=None,
        tss_method=None,
        source="strava",
        strava_activity_pk=None,
        stryd_activity_pk=None,
        strava_activity_url=None,
        distance_km=10.0,
        duration_seconds=3600,
        avg_hr=None,
        max_hr=None,
        elevation_m=None,
        zone2_minutes=None,
        avg_power=None,
        max_power=None,
        np=None,
        avg_cadence_spm=None,
        avg_stride_m=None,
        temperature_c=None,
        humidity_pct=None,
        feeling=None,
        created_at=None,
        strava_activity=None,
        flat_equivalent_pace=None,
        speed_signal=None,
        speed_signal_basis=None,
        speed_signal_window_seconds=None,
        endurance_signal=None,
        decoupling_percent=None,
        efficiency_first_half=None,
        efficiency_second_half=None,
        endurance_signal_source=None,
        manual_overrides=None,
    )

    result = _workout_dict(w, exercises=[])
    assert "flat_equivalent_pace" in result
    assert result["flat_equivalent_pace"] is None


# ── AC6: existing tests still pass (verified by import + call) ────────────────

def test_existing_normalize_treadmill_signal_unchanged():
    """normalize_treadmill_signal and compute_ngp still work exactly as in #1169 tests (AC6)."""
    from backend.services.treadmill_ngp import compute_ngp, normalize_treadmill_signal

    # compute_ngp known value from original tests
    assert round(compute_ngp(360.0, 5.0), 1) == pytest.approx(276.5, abs=0.5)
    assert compute_ngp(360.0, 0.0) == pytest.approx(360.0, abs=0.01)

    # normalize_treadmill_signal with grade passes through correctly
    signal = {"pace_seconds_per_km": 360.0, "grade_percent": 5.0, "heart_rate_bpm": 150.0}
    out = normalize_treadmill_signal(signal)
    assert "flat_equivalent_pace" in out
    assert out["flat_equivalent_pace"] == pytest.approx(compute_ngp(360.0, 5.0), abs=0.01)

    # normalize_treadmill_signal without grade is unchanged
    signal_no_grade = {"pace_seconds_per_km": 360.0}
    out_no_grade = normalize_treadmill_signal(signal_no_grade)
    assert "flat_equivalent_pace" not in out_no_grade


# ── AC1: map_stryd_activity extracts grade_percent from raw payload ───────────

def test_map_stryd_activity_extracts_grade_percent():
    """map_stryd_activity must populate grade_percent from average_incline in the raw Stryd payload (AC1)."""
    from backend.services.stryd_sync import map_stryd_activity

    import uuid
    user_id = str(uuid.uuid4())
    raw = {
        "id": "12345",
        "timestamp": 1700000000,
        "name": "Treadmill Run",
        "distance": 5000,       # metres
        "moving_time": 1800,    # seconds
        "average_power": 250,
        "average_heart_rate": 150,
        "average_incline": 5.0, # percent
    }
    mapped = map_stryd_activity(raw, user_id)
    assert "grade_percent" in mapped, "grade_percent must be extracted from average_incline"
    assert mapped["grade_percent"] == pytest.approx(5.0, abs=0.01)


def test_map_stryd_activity_grade_percent_none_for_outdoor():
    """map_stryd_activity must set grade_percent=None when average_incline is absent (AC3)."""
    from backend.services.stryd_sync import map_stryd_activity

    import uuid
    user_id = str(uuid.uuid4())
    raw = {
        "id": "99999",
        "timestamp": 1700000000,
        "name": "Outdoor Run",
        "distance": 10000,
        "moving_time": 3600,
        "average_power": 220,
    }
    mapped = map_stryd_activity(raw, user_id)
    assert mapped.get("grade_percent") is None
