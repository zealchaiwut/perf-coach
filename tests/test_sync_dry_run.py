"""TDD tests for issue #377: GET /api/sync/strava/dry-run preview endpoint.

Each test is anchored to one Acceptance Criterion item.
"""
import uuid
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from backend.services.workout_reconcile import strava_activities_dry_run


def _make_uid():
    return uuid.uuid4()


def _strava_act(uid, start_time, activity_type="Run", name="Morning Run",
                distance_km=10.0, is_stryd_synced=False, strava_activity_id=None):
    act = MagicMock()
    act.id = uuid.uuid4()
    act.user_id = uid
    act.strava_activity_id = strava_activity_id or (abs(hash(act.id)) % 100000 + 10000)
    act.start_time = start_time
    act.name = name
    act.activity_type = activity_type
    act.distance_km = distance_km
    act.is_stryd_synced = is_stryd_synced
    return act


def _workout(uid, workout_date, start_time=None, source="manual", strava_activity_pk=None):
    w = MagicMock()
    w.id = uuid.uuid4()
    w.user_id = uid
    w.workout_date = workout_date
    w.start_time = start_time
    w.source = source
    w.strava_activity_pk = strava_activity_pk
    return w


def _make_session(strava_acts, existing_workouts):
    session = MagicMock()
    session.__enter__ = lambda s: s
    session.__exit__ = MagicMock(return_value=False)

    def query_side_effect(model_or_col):
        from backend.models import StravaActivity, Workout

        q = MagicMock()
        q.filter.return_value = q
        q.order_by.return_value = q
        q.limit.return_value = q
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
    return session


# ── (a) Dry-run does NOT insert any rows ──────────────────────────────────────

def test_a_dry_run_does_not_insert_rows():
    """AC (a): dry-run must not call session.add() or session.commit() for data rows."""
    uid = _make_uid()
    t = datetime(2024, 1, 15, 7, 30, 0, tzinfo=timezone.utc)
    acts = [_strava_act(uid, t) for _ in range(3)]
    session = _make_session(acts, [])

    with patch("backend.services.workout_reconcile._Session", return_value=session):
        result = strava_activities_dry_run(uid)

    session.add.assert_not_called()
    assert "preview" in result
    assert "would_fetch_estimate" in result


# ── (b) Preview contains correct match info ───────────────────────────────────

def test_b_preview_contains_correct_match_info():
    """AC (b): matched activity shows would_create_new=False with correct workout id/date;
    unmatched shows would_create_new=True with null ids."""
    uid = _make_uid()
    t_matched = datetime(2024, 1, 15, 7, 30, 0, tzinfo=timezone.utc)
    t_unmatched = datetime(2024, 1, 16, 8, 0, 0, tzinfo=timezone.utc)
    d_matched = date(2024, 1, 15)
    d_unmatched = date(2024, 1, 16)

    act_matched = _strava_act(uid, t_matched, strava_activity_id=12345)
    act_unmatched = _strava_act(uid, t_unmatched, strava_activity_id=99999)

    w = _workout(uid, d_matched, start_time=t_matched)
    session = _make_session([act_matched, act_unmatched], [w])

    with patch("backend.services.workout_reconcile._Session", return_value=session):
        result = strava_activities_dry_run(uid)

    preview = {p["strava_activity_id"]: p for p in result["preview"]}

    matched_item = preview[12345]
    assert matched_item["would_create_new"] is False
    assert matched_item["would_match_existing_workout_id"] == str(w.id)
    assert matched_item["would_match_workout_date"] == "2024-01-15"

    unmatched_item = preview[99999]
    assert unmatched_item["would_create_new"] is True
    assert unmatched_item["would_match_existing_workout_id"] is None
    assert unmatched_item["would_match_workout_date"] is None


# ── (c) limit param is respected ─────────────────────────────────────────────

def test_c_limit_param_respected():
    """AC (c): preview has at most `limit` items; would_fetch_estimate shows N+ when more exist."""
    uid = _make_uid()
    t_base = datetime(2024, 1, 1, 8, 0, 0, tzinfo=timezone.utc)
    # Return limit+1 activities to simulate there being more
    acts = [_strava_act(uid, t_base, strava_activity_id=i) for i in range(6)]
    session = _make_session(acts, [])

    with patch("backend.services.workout_reconcile._Session", return_value=session):
        result = strava_activities_dry_run(uid, limit=5)

    assert len(result["preview"]) <= 5
    assert result["would_fetch_estimate"] == "5+"


def test_c_limit_exact_when_fewer_than_limit():
    """AC (c): would_fetch_estimate is exact N (not N+) when activities < limit."""
    uid = _make_uid()
    t = datetime(2024, 1, 1, 8, 0, 0, tzinfo=timezone.utc)
    acts = [_strava_act(uid, t, strava_activity_id=i) for i in range(3)]
    session = _make_session(acts, [])

    with patch("backend.services.workout_reconcile._Session", return_value=session):
        result = strava_activities_dry_run(uid, limit=10)

    assert len(result["preview"]) == 3
    assert result["would_fetch_estimate"] == "3"


# ── (d) since_date filter is applied correctly ────────────────────────────────

def test_d_since_date_filter_applied():
    """AC (d): only activities on/after since_date appear in preview.

    The mock returns only the post-since_date activity (simulating DB filter),
    and we verify the preview reflects that correctly.
    """
    uid = _make_uid()
    since = date(2024, 6, 1)

    # Only return the activity after since_date (simulating DB-side filter)
    late_act = _strava_act(uid, datetime(2024, 6, 15, 9, 0, 0, tzinfo=timezone.utc),
                           strava_activity_id=77777)
    session = _make_session([late_act], [])

    with patch("backend.services.workout_reconcile._Session", return_value=session):
        result = strava_activities_dry_run(uid, since_date=since)

    assert len(result["preview"]) == 1
    assert result["preview"][0]["strava_activity_id"] == 77777
    start_ts = datetime.fromisoformat(result["preview"][0]["start_time"].replace("Z", "+00:00"))
    assert start_ts.date() >= since
