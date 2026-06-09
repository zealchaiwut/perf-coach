"""TDD tests for issue #376: workout reconciliation from Strava activities cache.

Each test is anchored to one Acceptance Criterion item.
"""
import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from backend.services.workout_reconcile import (
    _TOLERANCE,
    _map_workout_type,
    reconcile_strava_to_workouts,
)


def _make_uid():
    return uuid.uuid4()


def _strava_act(
    uid,
    start_time,
    activity_type="Run",
    name="Morning Run",
    distance_km=10.0,
    duration_seconds=3600,
    avg_hr=145,
    max_hr=170,
    elevation_m=50,
    avg_power_w=None,
):
    act = MagicMock()
    act.id = uuid.uuid4()
    act.user_id = uid
    act.start_time = start_time
    act.name = name
    act.activity_type = activity_type
    act.distance_km = distance_km
    act.duration_seconds = duration_seconds
    act.avg_hr = avg_hr
    act.max_hr = max_hr
    act.elevation_m = elevation_m
    act.avg_power_w = avg_power_w
    return act


def _workout(uid, workout_date, start_time=None, source="manual", strava_activity_pk=None):
    w = MagicMock()
    w.id = uuid.uuid4()
    w.user_id = uid
    w.workout_date = workout_date
    w.start_time = start_time
    w.source = source
    w.strava_activity_pk = strava_activity_pk
    w.distance_km = None
    w.duration_seconds = None
    w.avg_hr = None
    w.tss = None
    w.tss_source = None
    return w


def _make_session(strava_acts, existing_workouts, ftp_w=None):
    """Build a mock Session for reconcile_strava_to_workouts.

    Handles:
    - session.query(StravaActivity).filter(...).all() -> strava_acts
    - session.query(Workout).filter(...).all()        -> existing_workouts
    - session.execute(text(...)).fetchone()           -> user_preferences row
    """
    session = MagicMock()
    session.__enter__ = lambda s: s
    session.__exit__ = MagicMock(return_value=False)

    def query_side_effect(model_or_col):
        from backend.models import StravaActivity, Workout

        q = MagicMock()
        q.filter.return_value = q
        if model_or_col is StravaActivity:
            q.all.return_value = list(strava_acts)
        elif model_or_col is Workout:
            q.all.return_value = list(existing_workouts)
        else:
            q.all.return_value = []
        return q

    session.query.side_effect = query_side_effect
    session.add = MagicMock()
    session.commit = MagicMock()

    pref_row = None
    if ftp_w is not None:
        pref_row = MagicMock()
        pref_row.ftp_w = ftp_w
        pref_row.threshold_hr = 170
        pref_row.threshold_pace_seconds_per_km = 270
    mock_execute_result = MagicMock()
    mock_execute_result.fetchone.return_value = pref_row
    session.execute.return_value = mock_execute_result

    return session


# ── (a) Creates new workout from unlinked strava_activity ─────────────────────

def test_creates_new_workout_from_unlinked_strava_activity():
    uid = _make_uid()
    t = datetime(2026, 6, 1, 9, 0, 0, tzinfo=timezone.utc)
    act = _strava_act(uid, t)
    session = _make_session([act], [])

    with patch("backend.services.workout_reconcile._Session", return_value=session):
        result = reconcile_strava_to_workouts(uid)

    session.add.assert_called_once()
    assert result["created_new"] == 1
    assert result["matched_to_existing"] == 0
    assert result["total_processed"] == 1


# ── (b) Matches to existing manual workout within ±5 min ─────────────────────

def test_matches_existing_manual_workout_within_tolerance():
    uid = _make_uid()
    d = date(2026, 6, 1)
    t_act = datetime(2026, 6, 1, 9, 0, 0, tzinfo=timezone.utc)
    t_workout = datetime(2026, 6, 1, 9, 3, 0, tzinfo=timezone.utc)  # 3 min — within ±5
    act = _strava_act(uid, t_act)
    w = _workout(uid, d, t_workout, source="manual")
    session = _make_session([act], [w])

    with patch("backend.services.workout_reconcile._Session", return_value=session):
        result = reconcile_strava_to_workouts(uid)

    session.add.assert_not_called()
    assert result["matched_to_existing"] == 1
    assert result["created_new"] == 0
    assert w.strava_activity_pk == act.id


# ── (c) Does NOT match when outside ±5 min tolerance ─────────────────────────

def test_no_match_outside_tolerance():
    uid = _make_uid()
    d = date(2026, 6, 1)
    t_act = datetime(2026, 6, 1, 9, 0, 0, tzinfo=timezone.utc)
    t_workout = datetime(2026, 6, 1, 9, 10, 0, tzinfo=timezone.utc)  # 10 min — outside ±5
    act = _strava_act(uid, t_act)
    w = _workout(uid, d, t_workout, source="manual")
    session = _make_session([act], [w])

    with patch("backend.services.workout_reconcile._Session", return_value=session):
        result = reconcile_strava_to_workouts(uid)

    session.add.assert_called_once()
    assert result["matched_to_existing"] == 0
    assert result["created_new"] == 1


# ── (d) Sets source = "both" when matching a manual workout ──────────────────

def test_source_set_to_both_when_matching_manual_workout():
    uid = _make_uid()
    d = date(2026, 6, 1)
    t = datetime(2026, 6, 1, 9, 0, 0, tzinfo=timezone.utc)
    act = _strava_act(uid, t)
    w = _workout(uid, d, t, source="manual")
    session = _make_session([act], [w])

    with patch("backend.services.workout_reconcile._Session", return_value=session):
        reconcile_strava_to_workouts(uid)

    assert w.source == "both"


# ── (e) Skips strava_activities already linked to a workout ──────────────────

def test_skips_already_linked_strava_activities():
    uid = _make_uid()
    t = datetime(2026, 6, 1, 9, 0, 0, tzinfo=timezone.utc)
    d = date(2026, 6, 1)
    act = _strava_act(uid, t)
    w = _workout(uid, d, t, source="strava", strava_activity_pk=act.id)
    session = _make_session([act], [w])

    with patch("backend.services.workout_reconcile._Session", return_value=session):
        result = reconcile_strava_to_workouts(uid)

    session.add.assert_not_called()
    assert result["total_processed"] == 0
    assert result["matched_to_existing"] == 0
    assert result["created_new"] == 0


# ── (f) workout_type mapping: Run/Ride/WeightTraining/Workout/unknown ─────────

def test_workout_type_mapping():
    assert _map_workout_type("Run") == "run"
    assert _map_workout_type("Ride") == "bike"
    assert _map_workout_type("WeightTraining") == "strength"
    assert _map_workout_type("Workout") == "wod"
    assert _map_workout_type("Swim") == "other"
    assert _map_workout_type("VirtualRide") == "other"
    assert _map_workout_type("Unknown") == "other"


# ── (g) TSS computed from user_preferences FTP when present ──────────────────

def test_tss_computed_from_user_preferences_ftp():
    uid = _make_uid()
    t = datetime(2026, 6, 1, 9, 0, 0, tzinfo=timezone.utc)
    # Cycling activity with known power; FTP=250 → IF=200/250=0.8 → TSS=64
    act = _strava_act(uid, t, activity_type="Ride", avg_power_w=200, duration_seconds=3600)
    session = _make_session([act], [], ftp_w=250)

    with patch("backend.services.workout_reconcile._Session", return_value=session):
        result = reconcile_strava_to_workouts(uid)

    assert result["created_new"] == 1
    added_workout = session.add.call_args[0][0]
    assert added_workout.tss is not None
    assert added_workout.tss > 0
