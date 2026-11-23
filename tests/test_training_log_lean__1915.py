"""Issue #1915 — training-log lean canonical totals + one planned-TSS estimate."""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from backend.auth import resolve_user
from backend.main import app
from backend.models import User

UID = uuid.uuid4()
TODAY = date(2026, 11, 23)


def _client():
    app.dependency_overrides[resolve_user] = lambda: User(id=UID, name="t")
    return TestClient(app)


def _teardown():
    app.dependency_overrides.pop(resolve_user, None)


def _session_mock():
    sess = MagicMock()
    sess.__enter__.return_value = sess
    sess.__exit__.return_value = False
    q = sess.query.return_value
    q.filter.return_value = q
    q.order_by.return_value = q
    q.distinct.return_value = q
    q.group_by.return_value = q
    q.all.return_value = []
    q.first.return_value = None
    q.count.return_value = 0
    return sess


def _week_rollup(ws: date):
    we = ws + timedelta(days=6)
    return {
        "week_start": ws.isoformat(),
        "week_end": we.isoformat(),
        "tss_total": 10,
        "distance_km": 8,
        "hours": 1.0,
        "session_count": 1,
        "planned_tss": 20,
        "target_tss": 300,
    }


def test_canonical_totals_calls_batched_rollups_once():
    sess = _session_mock()
    calls = []

    def fake_rollups(uid, fw, tw, **kw):
        calls.append({"fw": fw, "tw": tw, "session": kw.get("session")})
        out = []
        d = fw
        while d <= tw:
            out.append(_week_rollup(d))
            d += timedelta(days=7)
        return out

    client = _client()
    try:
        with (
            patch("backend.main.Session", return_value=sess),
            patch("backend.services.weekly_rollup.weekly_rollups", side_effect=fake_rollups) as batched,
            patch("backend.services.weekly_rollup.weekly_rollup") as per_week,
        ):
            res = client.get(
                "/api/training-log?from=2026-10-05&to=2026-11-23&canonical_week_totals=1"
            )
        assert res.status_code == 200, res.text
        assert batched.call_count == 1
        assert per_week.call_count == 0
        assert calls[0]["session"] is sess
        body = res.json()
        assert "weeks" in body
        # empty workouts → no week rows, but batched still ran for the range
        assert calls[0]["fw"] <= calls[0]["tw"]
    finally:
        _teardown()


def test_canonical_flag_off_skips_rollup():
    sess = _session_mock()
    client = _client()
    try:
        with (
            patch("backend.main.Session", return_value=sess),
            patch("backend.services.weekly_rollup.weekly_rollups") as batched,
            patch("backend.services.weekly_rollup.weekly_rollup") as per_week,
        ):
            res = client.get("/api/training-log?from=2026-11-10&to=2026-11-23")
        assert res.status_code == 200, res.text
        assert batched.call_count == 0
        assert per_week.call_count == 0
        weeks = res.json()["weeks"]
        for w in weeks:
            assert "rollup" not in w
    finally:
        _teardown()


def test_week_row_shape_with_canonical_totals():
    w = MagicMock()
    w.id = uuid.uuid4()
    w.workout_date = date(2026, 11, 18)
    w.workout_type = "run"
    w.run_subtype = None
    w.name = "Easy"
    w.duration_seconds = 3600
    w.distance_km = 8.0
    w.avg_hr = 140
    w.elevation_m = None
    w.tss = 40
    w.source = "manual"
    w.tss_source = None
    w.strava_activity_url = None
    w.stryd_activity_pk = None
    w.strava_activity_pk = None
    w.remarks = ""
    w.feeling = None
    w.speed_signal = None
    w.speed_signal_basis = None
    w.start_time = None
    w.avg_power = None
    sess = _session_mock()
    sess.query.return_value.filter.return_value.order_by.return_value.all.return_value = [w]
    sess.query.return_value.filter.return_value.first.return_value = None

    def fake_rollups(*_a, **_k):
        return [_week_rollup(date(2026, 11, 16))]

    client = _client()
    try:
        with (
            patch("backend.main.Session", return_value=sess),
            patch("backend.main._workout_list_tss", return_value=40),
            patch("backend.main._plan_match_map", return_value={}),
            patch("backend.services.weekly_rollup.weekly_rollups", side_effect=fake_rollups),
        ):
            res = client.get(
                "/api/training-log?from=2026-11-17&to=2026-11-23&canonical_week_totals=1"
            )
        assert res.status_code == 200, res.text
        week = res.json()["weeks"][0]
        assert set(week.keys()) >= {"week_start", "week_end", "label", "entries", "workouts", "summary", "rollup"}
        assert set(week["summary"].keys()) >= {
            "workout_count",
            "total_distance_km",
            "total_tss",
            "total_time_minutes",
            "planned_tss",
            "target_tss",
        }
        assert week["rollup"]["week_start"] == "2026-11-16"
        assert week["summary"]["total_tss"] == 10
    finally:
        _teardown()


def test_planned_tss_estimate_once_per_missed_row():
    from backend.models import PlannedSession

    sess = _session_mock()
    planned = SimpleNamespace(
        id=uuid.uuid4(),
        planned_date=date(2026, 11, 18),
        session_type="run",
        name="Missed easy",
        notes="",
        matched_workout_id=None,
        status="planned",
        structure={},
    )

    def _query(model):
        q = MagicMock()
        q.filter.return_value = q
        q.order_by.return_value = q
        q.distinct.return_value = q
        q.group_by.return_value = q
        q.first.return_value = None
        q.count.return_value = 0
        q.all.return_value = [planned] if model is PlannedSession else []
        return q

    sess.query.side_effect = _query
    estimates = []

    def fake_est(session, row):
        estimates.append(row)
        return 33.0

    client = _client()
    try:
        with (
            patch("backend.main.Session", return_value=sess),
            patch("backend.main._is_missed_planned", return_value=True),
            patch("backend.main._planned_item_status", return_value="missed"),
            patch("backend.main._planned_source", return_value="plan"),
            patch("backend.main._planned_tss_estimate", side_effect=fake_est),
        ):
            res = client.get(
                "/api/training-log?from=2026-11-17&to=2026-11-23&include_plan=true"
            )
        assert res.status_code == 200, res.text
        assert len(estimates) == 1
        weeks = res.json()["weeks"]
        row = weeks[0]["entries"][0]
        assert row["tss"] == 33.0
        assert row["plan_match"]["planned_tss"] == 33.0
    finally:
        _teardown()


def test_canonical_query_bound_independent_of_week_count():
    """Batched rollup is one call for 4 weeks and for 8 weeks."""
    sess = _session_mock()
    client = _client()
    counts = []
    try:
        with (
            patch("backend.main.Session", return_value=sess),
            patch(
                "backend.services.weekly_rollup.weekly_rollups",
                side_effect=lambda uid, fw, tw, **kw: counts.append((fw, tw)) or [
                    _week_rollup(fw)
                ],
            ),
        ):
            r4 = client.get(
                "/api/training-log?from=2026-10-26&to=2026-11-16&canonical_week_totals=1"
            )
            n4 = len(counts)
            r8 = client.get(
                "/api/training-log?from=2026-09-28&to=2026-11-16&canonical_week_totals=1"
            )
            n8 = len(counts) - n4
        assert r4.status_code == 200 and r8.status_code == 200
        assert n4 == 1 and n8 == 1
    finally:
        _teardown()
