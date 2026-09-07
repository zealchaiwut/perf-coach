"""Tests for issue #1760: Races CSV export with goal-vs-actual and fitness context.

Acceptance criteria verified:
AC1: Races CSV returns one row per race with required columns (date, distance, priority,
     status, goal time, finish time, goal-vs-finish delta).
AC2: Each row carries fitness context at race day (CTL, ATL, TSB from training-load snapshot).
AC3: Column names and order are a documented stability contract for downstream consumers.
AC4: Workouts export gains an is_pr flag column.
"""
import csv
import io
import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.auth import resolve_user
from backend.main import app, _RACES_EXPORT_COLUMNS

_UID = uuid.UUID("00000000-0000-0000-0000-000000001760")


class _FakeUser:
    id = _UID
    name = "test-user-1760"
    is_admin = False
    is_active = True


@pytest.fixture(autouse=True)
def _patch_resolve_user():
    app.dependency_overrides[resolve_user] = lambda: _FakeUser()
    yield
    app.dependency_overrides.pop(resolve_user, None)


def _client() -> TestClient:
    return TestClient(app, raise_server_exceptions=True)


def _parse_csv(text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(text)))


def _make_race(
    race_date=date(2026, 5, 1),
    name="Test Race",
    race_type="race",
    priority="A",
    status="done",
    distance_km=Decimal("42.195"),
    goal_time_seconds=10800,
    actual_time_seconds=11100,
):
    r = MagicMock()
    r.race_date = race_date
    r.name = name
    r.race_type = race_type
    r.priority = priority
    r.status = status
    r.distance_km = distance_km
    r.goal_time_seconds = goal_time_seconds
    r.actual_time_seconds = actual_time_seconds
    return r


def _make_snapshot(snapshot_date=date(2026, 5, 1), ctl=55.0, atl=48.0, tsb=7.0):
    s = MagicMock()
    s.snapshot_date = snapshot_date
    s.ctl = ctl
    s.atl = atl
    s.tsb = tsb
    return s


def _mock_session(races, snapshots=None):
    """Return a context-manager mock for backend.main.Session that serves the given races and snapshots."""
    mock_sess = MagicMock()
    mock_sess.__enter__ = MagicMock(return_value=mock_sess)
    mock_sess.__exit__ = MagicMock(return_value=False)

    def _query_side_effect(model):
        from backend.models import Race, TrainingLoadSnapshot, PersonalRecord
        q = MagicMock()
        if model is Race:
            q.filter.return_value.order_by.return_value.all.return_value = races
        elif model is TrainingLoadSnapshot:
            q.filter.return_value.all.return_value = snapshots or []
        elif model is PersonalRecord:
            q.filter.return_value.all.return_value = []
        else:
            q.filter.return_value.order_by.return_value.all.return_value = []
            q.filter.return_value.all.return_value = []
        return q

    mock_sess.query.side_effect = _query_side_effect

    mock_session_cls = MagicMock()
    mock_session_cls.return_value = mock_sess
    return mock_session_cls


# ── AC3: stability contract module-level constant exists ─────────────────────

def test_races_export_columns_constant_exists():
    """AC3: _RACES_EXPORT_COLUMNS is exported from backend.main as the stability contract."""
    assert isinstance(_RACES_EXPORT_COLUMNS, list)
    assert len(_RACES_EXPORT_COLUMNS) >= 1


def test_races_export_columns_contains_required_fields():
    """AC3: Stability contract includes every required field from the acceptance criteria."""
    required = {
        "race_date", "distance_km", "priority", "status",
        "goal_time_seconds", "finish_time_seconds", "goal_vs_finish_delta_seconds",
        "ctl", "atl", "tsb",
    }
    assert required.issubset(set(_RACES_EXPORT_COLUMNS)), (
        f"Missing from contract: {required - set(_RACES_EXPORT_COLUMNS)}"
    )


# ── AC1: races CSV returns correct headers (the stability contract) ───────────

def test_races_csv_headers_match_stability_contract():
    """AC1/AC3: CSV header row matches _RACES_EXPORT_COLUMNS exactly."""
    with patch("backend.main.Session", _mock_session([])):
        resp = _client().get("/api/exports/races")
    assert resp.status_code == 200
    assert "text/csv" in resp.headers["content-type"]
    rows = _parse_csv(resp.text)
    assert rows[0] == _RACES_EXPORT_COLUMNS


def test_races_csv_empty_returns_headers_only():
    """AC1: No races → header row only, no data rows."""
    with patch("backend.main.Session", _mock_session([])):
        resp = _client().get("/api/exports/races")
    assert resp.status_code == 200
    rows = _parse_csv(resp.text)
    assert len(rows) == 1
    assert rows[0][0] == "race_date"


# ── AC1: one row per race, core fields present ───────────────────────────────

def test_races_csv_one_row_per_race():
    """AC1: Two races → two data rows."""
    races = [
        _make_race(race_date=date(2026, 4, 1), name="Spring 5K", distance_km=Decimal("5.0")),
        _make_race(race_date=date(2026, 8, 15), name="Summer 10K", distance_km=Decimal("10.0")),
    ]
    with patch("backend.main.Session", _mock_session(races)):
        resp = _client().get("/api/exports/races")
    rows = _parse_csv(resp.text)
    assert len(rows) == 3  # header + 2 data rows


def test_races_csv_contains_required_column_values():
    """AC1: Core fields (date, distance, priority, status, goal, finish, delta) are present."""
    race = _make_race(
        race_date=date(2026, 5, 1),
        name="Marathon",
        race_type="race",
        priority="A",
        status="done",
        distance_km=Decimal("42.195"),
        goal_time_seconds=10800,
        actual_time_seconds=11100,
    )
    with patch("backend.main.Session", _mock_session([race])):
        resp = _client().get("/api/exports/races")
    rows = _parse_csv(resp.text)
    headers = rows[0]
    data = rows[1]
    assert data[headers.index("race_date")] == "2026-05-01"
    assert data[headers.index("priority")] == "A"
    assert data[headers.index("status")] == "done"
    assert data[headers.index("distance_km")] != ""
    assert data[headers.index("goal_time_seconds")] == "10800"
    assert data[headers.index("finish_time_seconds")] == "11100"


def test_races_csv_goal_vs_finish_delta_positive_when_slower():
    """AC1: delta = finish - goal is positive when finish > goal (slower than goal)."""
    race = _make_race(goal_time_seconds=10800, actual_time_seconds=11100)
    with patch("backend.main.Session", _mock_session([race])):
        resp = _client().get("/api/exports/races")
    rows = _parse_csv(resp.text)
    headers = rows[0]
    data = rows[1]
    delta_str = data[headers.index("goal_vs_finish_delta_seconds")]
    assert delta_str == "300"  # 11100 - 10800


def test_races_csv_goal_vs_finish_delta_negative_when_faster():
    """AC1: delta is negative when finish < goal (faster than goal)."""
    race = _make_race(goal_time_seconds=10800, actual_time_seconds=10500)
    with patch("backend.main.Session", _mock_session([race])):
        resp = _client().get("/api/exports/races")
    rows = _parse_csv(resp.text)
    headers = rows[0]
    data = rows[1]
    delta_str = data[headers.index("goal_vs_finish_delta_seconds")]
    assert delta_str == "-300"


def test_races_csv_delta_empty_when_no_finish_time():
    """AC1: delta is empty when actual_time_seconds is NULL (future/unfinished race)."""
    race = _make_race(goal_time_seconds=10800, actual_time_seconds=None)
    with patch("backend.main.Session", _mock_session([race])):
        resp = _client().get("/api/exports/races")
    rows = _parse_csv(resp.text)
    headers = rows[0]
    data = rows[1]
    assert data[headers.index("goal_vs_finish_delta_seconds")] == ""
    assert data[headers.index("finish_time_seconds")] == ""


def test_races_csv_delta_empty_when_no_goal_time():
    """AC1: delta is empty when goal_time_seconds is NULL."""
    race = _make_race(goal_time_seconds=None, actual_time_seconds=11100)
    with patch("backend.main.Session", _mock_session([race])):
        resp = _client().get("/api/exports/races")
    rows = _parse_csv(resp.text)
    headers = rows[0]
    data = rows[1]
    assert data[headers.index("goal_vs_finish_delta_seconds")] == ""


# ── AC2: fitness context columns from training-load snapshot ──────────────────

def test_races_csv_includes_ctl_atl_tsb_from_snapshot():
    """AC2: CTL/ATL/TSB are populated from the training-load snapshot for race_date."""
    race = _make_race(race_date=date(2026, 5, 1))
    snap = _make_snapshot(snapshot_date=date(2026, 5, 1), ctl=62.5, atl=55.0, tsb=7.5)
    with patch("backend.main.Session", _mock_session([race], [snap])):
        resp = _client().get("/api/exports/races")
    rows = _parse_csv(resp.text)
    headers = rows[0]
    data = rows[1]
    assert data[headers.index("ctl")] == "62.5"
    assert data[headers.index("atl")] == "55.0"
    assert data[headers.index("tsb")] == "7.5"


def test_races_csv_fitness_columns_empty_when_no_snapshot():
    """AC2: CTL/ATL/TSB are empty strings when no snapshot exists for race_date."""
    race = _make_race(race_date=date(2026, 5, 1))
    with patch("backend.main.Session", _mock_session([race], [])):
        resp = _client().get("/api/exports/races")
    rows = _parse_csv(resp.text)
    headers = rows[0]
    data = rows[1]
    assert data[headers.index("ctl")] == ""
    assert data[headers.index("atl")] == ""
    assert data[headers.index("tsb")] == ""


def test_races_csv_snapshot_matched_by_date():
    """AC2: Snapshot for a different date is not applied to the race row."""
    race = _make_race(race_date=date(2026, 5, 1))
    snap = _make_snapshot(snapshot_date=date(2026, 4, 30), ctl=99.0, atl=99.0, tsb=0.0)
    with patch("backend.main.Session", _mock_session([race], [snap])):
        resp = _client().get("/api/exports/races")
    rows = _parse_csv(resp.text)
    headers = rows[0]
    data = rows[1]
    # Snapshot is for April 30, race is May 1 — must not match
    assert data[headers.index("ctl")] == ""


# ── AC1: content-disposition / auth ──────────────────────────────────────────

def test_races_csv_content_disposition_header():
    """AC1: Response carries Content-Disposition: attachment."""
    with patch("backend.main.Session", _mock_session([])):
        resp = _client().get("/api/exports/races")
    cd = resp.headers.get("content-disposition", "")
    assert "attachment" in cd
    assert "races" in cd


def test_races_csv_requires_auth():
    """AC1: Unauthenticated request returns 401."""
    app.dependency_overrides.pop(resolve_user, None)
    try:
        resp = _client().get("/api/exports/races")
        assert resp.status_code == 401
    finally:
        app.dependency_overrides[resolve_user] = lambda: _FakeUser()


# ── AC4: workouts export is_pr column ────────────────────────────────────────

def _make_workout(workout_date=date(2026, 5, 1), name="Easy run", workout_type="run"):
    w = MagicMock()
    w.workout_date = workout_date
    w.name = name
    w.workout_type = workout_type
    w.distance_km = Decimal("10.0")
    w.duration_seconds = 3600
    w.avg_hr = 145
    w.tss = 60.0
    w.source = "manual"
    w.remarks = None
    return w


def _make_pr_record(achieved_on=date(2026, 5, 1)):
    pr = MagicMock()
    pr.achieved_on = achieved_on
    return pr


def _mock_workouts_session(workouts, pr_records=None):
    """Session mock for the workouts export — handles Workout and PersonalRecord queries."""
    mock_sess = MagicMock()
    mock_sess.__enter__ = MagicMock(return_value=mock_sess)
    mock_sess.__exit__ = MagicMock(return_value=False)

    def _query_side_effect(model):
        from backend.models import Workout, PersonalRecord
        q = MagicMock()
        if model is Workout:
            q2 = MagicMock()
            q2.filter.return_value = q2
            q2.order_by.return_value.all.return_value = workouts
            q.filter.return_value = q2
        elif model is PersonalRecord:
            q.filter.return_value.all.return_value = pr_records or []
        else:
            q.filter.return_value.all.return_value = []
            q.filter.return_value.order_by.return_value.all.return_value = []
        return q

    mock_sess.query.side_effect = _query_side_effect

    mock_session_cls = MagicMock()
    mock_session_cls.return_value = mock_sess
    return mock_session_cls


def test_workouts_csv_includes_is_pr_column():
    """AC4: Workouts CSV header includes 'is_pr' column."""
    workouts = [_make_workout()]
    with patch("backend.main.Session", _mock_workouts_session(workouts)):
        resp = _client().get("/api/exports/workouts")
    assert resp.status_code == 200
    rows = _parse_csv(resp.text)
    assert "is_pr" in rows[0], f"'is_pr' missing from headers: {rows[0]}"


def test_workouts_csv_is_pr_true_when_pr_on_same_date():
    """AC4: is_pr is 'true' when a PersonalRecord was achieved on the workout date."""
    workout_date = date(2026, 5, 1)
    workouts = [_make_workout(workout_date=workout_date)]
    prs = [_make_pr_record(achieved_on=workout_date)]
    with patch("backend.main.Session", _mock_workouts_session(workouts, prs)):
        resp = _client().get("/api/exports/workouts")
    rows = _parse_csv(resp.text)
    headers = rows[0]
    data = rows[1]
    assert data[headers.index("is_pr")] == "true"


def test_workouts_csv_is_pr_false_when_no_pr_on_date():
    """AC4: is_pr is 'false' when no PersonalRecord exists for the workout date."""
    workout_date = date(2026, 5, 1)
    workouts = [_make_workout(workout_date=workout_date)]
    prs = [_make_pr_record(achieved_on=date(2026, 6, 1))]  # different date
    with patch("backend.main.Session", _mock_workouts_session(workouts, prs)):
        resp = _client().get("/api/exports/workouts")
    rows = _parse_csv(resp.text)
    headers = rows[0]
    data = rows[1]
    assert data[headers.index("is_pr")] == "false"


def test_workouts_csv_is_pr_false_when_no_prs_at_all():
    """AC4: is_pr is 'false' for all rows when user has no PersonalRecords."""
    workouts = [_make_workout()]
    with patch("backend.main.Session", _mock_workouts_session(workouts, [])):
        resp = _client().get("/api/exports/workouts")
    rows = _parse_csv(resp.text)
    headers = rows[0]
    data = rows[1]
    assert data[headers.index("is_pr")] == "false"
