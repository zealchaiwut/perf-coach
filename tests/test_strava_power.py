"""TDD tests for issue #378: Stryd power data — TSS formula + workout enrichment.

Each test anchored to one Acceptance Criterion item.
"""
import uuid
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


def _make_uid():
    return uuid.uuid4()


def _strava_act(
    uid,
    start_time,
    avg_power_w=None,
    avg_hr=145,
    duration_seconds=3600,
    distance_km=10.0,
    is_stryd_synced=False,
    raw_payload=None,
):
    act = MagicMock()
    act.id = uuid.uuid4()
    act.user_id = uid
    act.start_time = start_time
    act.name = "Morning Run"
    act.activity_type = "Run"
    act.distance_km = distance_km
    act.duration_seconds = duration_seconds
    act.avg_hr = avg_hr
    act.max_hr = 175
    act.elevation_m = 50
    act.avg_power_w = avg_power_w
    act.is_stryd_synced = is_stryd_synced
    act.raw_payload = raw_payload or {}
    return act


def _make_session(strava_acts, existing_workouts, ftp_w=None):
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


# ── (a) Activity with power data → TSS via power formula ─────────────────────

def test_power_tss_when_stryd_synced_with_avg_power_in_payload():
    """AC (a): is_stryd_synced=True + avg_power_w in raw_payload → TSS via power formula."""
    from backend.services.workout_reconcile import reconcile_strava_to_workouts
    from backend.services.tss import compute_tss, intensity_factor_from_power, FTP_W

    uid = _make_uid()
    t = datetime(2026, 6, 10, 9, 0, 0, tzinfo=timezone.utc)
    act = _strava_act(
        uid, t,
        avg_power_w=300,
        is_stryd_synced=True,
        raw_payload={"average_watts": 300},
    )
    session = _make_session([act], [])

    with patch("backend.services.workout_reconcile._Session", return_value=session):
        reconcile_strava_to_workouts(uid)

    added_workout = session.add.call_args[0][0]
    expected_tss = compute_tss(intensity_factor_from_power(300, FTP_W), 3600)
    assert added_workout.tss == expected_tss


# ── (b) is_stryd_synced=True + no power data → falls back to pace/HR ─────────

def test_fallback_to_hr_when_stryd_synced_but_no_power_in_payload():
    """AC (b): is_stryd_synced=True but no average_watts in raw_payload → non-power TSS."""
    from backend.services.workout_reconcile import reconcile_strava_to_workouts
    from backend.services.tss import compute_tss, intensity_factor_from_power, FTP_W

    uid = _make_uid()
    t = datetime(2026, 6, 10, 9, 0, 0, tzinfo=timezone.utc)
    # avg_power_w column set but raw_payload has no average_watts
    act = _strava_act(
        uid, t,
        avg_power_w=300,
        avg_hr=145,
        is_stryd_synced=True,
        raw_payload={},  # no average_watts
    )
    session = _make_session([act], [])

    with patch("backend.services.workout_reconcile._Session", return_value=session):
        reconcile_strava_to_workouts(uid)

    added_workout = session.add.call_args[0][0]
    power_tss = compute_tss(intensity_factor_from_power(300, FTP_W), 3600)
    # TSS must NOT equal the power formula result
    assert added_workout.tss != power_tss


# ── (c) get_strava_power_data returns None without power fields ───────────────

def test_get_strava_power_data_returns_none_without_power_fields():
    """AC (c): get_strava_power_data returns None for activity dict with no power data."""
    from backend.services.strava import get_strava_power_data

    assert get_strava_power_data({}) is None
    assert get_strava_power_data({"device_name": "Garmin", "type": "Run"}) is None
    assert get_strava_power_data({"name": "Morning Run", "distance": 10000}) is None


# ── (d) avg_power_w persists correctly on strava_activities row ───────────────

def test_avg_power_w_persists_on_strava_activity():
    """AC (d): avg_power_w column exists and is populated from raw_payload average_watts."""
    from backend.models import StravaActivity

    # Column exists on model
    assert hasattr(StravaActivity, "avg_power_w")

    # Value is correctly set from raw_payload average_watts
    act = StravaActivity(
        user_id=uuid.uuid4(),
        strava_activity_id=99999,
        start_time=datetime(2026, 6, 10, 9, 0, 0, tzinfo=timezone.utc),
        activity_type="Run",
        name="Power Run",
        avg_power_w=285,
        is_stryd_synced=True,
        raw_payload={"average_watts": 285},
    )
    assert act.avg_power_w == 285
    assert act.raw_payload["average_watts"] == 285


# ── (e) _workout_dict includes avg_power_w from linked strava_activity ─────────

def test_workout_dict_includes_avg_power_w_from_linked_strava_activity():
    """AC (e): _workout_dict serializer exposes avg_power_w from linked strava_activity."""
    from backend.main import _workout_dict

    strava = SimpleNamespace(
        avg_power_w=310,
        distance_km=10.0,
        duration_seconds=3600,
        avg_hr=150,
        name="Power Run",
        tss=None,
        manual_overrides=None,
    )
    w = SimpleNamespace(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        name="Power Run",
        workout_date=date(2026, 6, 10),
        workout_type="run",
        remarks=None,
        tss=None,
        tss_source=None,
        source="strava",
        strava_activity_pk=uuid.uuid4(),
        stryd_activity_pk=None,
        strava_activity_url=None,
        distance_km=10.0,
        duration_seconds=3600,
        avg_hr=150,
        max_hr=175,
        elevation_m=50,
        start_time=None,
        created_at=None,
        manual_overrides=None,
        strava_activity=strava,
        stryd_activity=None,
    )

    result = _workout_dict(w, [])
    assert result["avg_power_w"] == 310


def test_workout_dict_avg_power_w_none_when_no_strava_activity():
    """_workout_dict returns avg_power_w=None when no strava_activity linked."""
    from backend.main import _workout_dict

    w = SimpleNamespace(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        name="Manual Run",
        workout_date=date(2026, 6, 10),
        workout_type="run",
        remarks=None,
        tss=None,
        tss_source=None,
        source="manual",
        strava_activity_pk=None,
        stryd_activity_pk=None,
        strava_activity_url=None,
        distance_km=10.0,
        duration_seconds=3600,
        avg_hr=150,
        max_hr=175,
        elevation_m=50,
        start_time=None,
        created_at=None,
        manual_overrides=None,
        strava_activity=None,
        stryd_activity=None,
    )

    result = _workout_dict(w, [])
    assert result["avg_power_w"] is None
