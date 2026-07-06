"""Tests for issue #541: Dedicated endpoint for volume chart weekly aggregations.

Acceptance Criteria:
  AC1 - GET /api/training-load/weekly exists and accepts from and to query params.
  AC2 - Response contains only weekly summary aggregates (week_start,
        total_distance_km, total_tss per week); no full workout serialization.
  AC3 - renderVolumeChart() in training-log.js calls /api/training-load/weekly
        instead of /api/training-log for its data fetch.
  AC4 - renderVolumeChart() does NOT trigger a second /api/training-log request
        (the redundant fetch is eliminated).
  AC5 - Volume chart renders correctly with new endpoint data (run_tss /
        strength_tss / total_distance_km fields are used by renderVolumeChart).
"""
import re
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.main import app, resolve_user

_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000541")
_REPO = Path(__file__).resolve().parent.parent
_JS = (_REPO / "frontend" / "js" / "training-log.js").read_text()


# ── Test client helpers ───────────────────────────────────────────────────────

def _make_client():
    u = MagicMock()
    u.id = _USER_ID

    async def _fake_resolve():
        return u

    app.dependency_overrides[resolve_user] = _fake_resolve
    return TestClient(app)


def _teardown():
    app.dependency_overrides.pop(resolve_user, None)


def _week_monday(workout_date_str: str) -> datetime:
    """Return the Monday of the ISO week containing workout_date_str."""
    d = date.fromisoformat(workout_date_str)
    mon = d - __import__("datetime").timedelta(days=d.weekday())
    return datetime(mon.year, mon.month, mon.day, tzinfo=timezone.utc)


def _make_row(
    workout_type: str,
    tss: float,
    distance_km: float,
    workout_date: str,
):
    """Create a mock GROUP BY row matching the new SQL aggregation query shape.

    The endpoint now runs:
      SELECT date_trunc('week', workout_date), workout_type,
             SUM(tss), SUM(distance_km)
      FROM workouts ... GROUP BY week, workout_type

    Each row has: week_mon (datetime), workout_type (str), sum_tss, sum_dist.
    """
    return SimpleNamespace(
        week_mon=_week_monday(workout_date),
        workout_type=workout_type,
        sum_tss=tss,
        sum_dist=distance_km,
    )


# Legacy alias so existing test bodies don't need rewriting: _make_workout now
# creates a GROUP BY row (same interface as before for single-type tests).
def _make_workout(
    workout_type: str,
    tss: float,
    distance_km: float,
    workout_date: str,
    uid=_USER_ID,
):
    return _make_row(workout_type, tss, distance_km, workout_date)


def _mock_session(rows):
    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)
    # Endpoint now uses: session.query(...).filter(...).group_by(...).all()
    mock_session.query.return_value.filter.return_value.group_by.return_value.all.return_value = rows
    return mock_session


# ── AC1: endpoint exists and accepts from/to params ──────────────────────────

def test_weekly_endpoint_returns_200_with_valid_range():
    """AC1: GET /api/training-load/weekly with valid from/to returns 200."""
    client = _make_client()
    try:
        with patch("backend.main.Session") as mock_cls:
            mock_cls.return_value = _mock_session([])
            resp = client.get(
                "/api/training-load/weekly?from=2025-01-01&to=2025-03-31"
            )
        assert resp.status_code == 200
    finally:
        _teardown()


def test_weekly_endpoint_requires_auth():
    """AC1: unauthenticated request returns 401."""
    resp = TestClient(app).get(
        "/api/training-load/weekly?from=2025-01-01&to=2025-03-31"
    )
    assert resp.status_code == 401


def test_weekly_endpoint_rejects_invalid_from_date():
    """AC1: invalid from date returns 422."""
    client = _make_client()
    try:
        resp = client.get("/api/training-load/weekly?from=not-a-date&to=2025-03-31")
        assert resp.status_code == 422
    finally:
        _teardown()


def test_weekly_endpoint_rejects_invalid_to_date():
    """AC1: invalid to date returns 422."""
    client = _make_client()
    try:
        resp = client.get("/api/training-load/weekly?from=2025-01-01&to=not-a-date")
        assert resp.status_code == 422
    finally:
        _teardown()


# ── AC2: response shape — no full workout serialization ──────────────────────

def test_weekly_endpoint_response_has_weeks_array():
    """AC2: response body contains a 'weeks' array."""
    client = _make_client()
    try:
        with patch("backend.main.Session") as mock_cls:
            mock_cls.return_value = _mock_session([])
            resp = client.get(
                "/api/training-load/weekly?from=2025-01-06&to=2025-01-12"
            )
        body = resp.json()
        assert "weeks" in body
        assert isinstance(body["weeks"], list)
    finally:
        _teardown()


def test_weekly_endpoint_week_has_required_fields():
    """AC2: each week object has week_start, total_distance_km, total_tss."""
    run = _make_workout("run", tss=50.0, distance_km=10.0, workout_date="2025-01-07")
    client = _make_client()
    try:
        with patch("backend.main.Session") as mock_cls:
            mock_cls.return_value = _mock_session([run])
            resp = client.get(
                "/api/training-load/weekly?from=2025-01-06&to=2025-01-12"
            )
        body = resp.json()
        assert len(body["weeks"]) == 1
        wk = body["weeks"][0]
        assert "week_start" in wk
        assert "total_distance_km" in wk
        assert "total_tss" in wk
    finally:
        _teardown()


def test_weekly_endpoint_no_full_workout_objects_in_response():
    """AC2: response does NOT contain per-workout detail objects (no 'workouts' key
    inside each week, no 'id', 'title', 'duration_seconds' fields)."""
    run = _make_workout("run", tss=50.0, distance_km=10.0, workout_date="2025-01-07")
    client = _make_client()
    try:
        with patch("backend.main.Session") as mock_cls:
            mock_cls.return_value = _mock_session([run])
            resp = client.get(
                "/api/training-load/weekly?from=2025-01-06&to=2025-01-12"
            )
        body = resp.json()
        wk = body["weeks"][0]
        assert "workouts" not in wk, "Full workout list must not be serialized"
        assert "entries" not in wk
        assert "title" not in wk
        assert "duration_seconds" not in wk
    finally:
        _teardown()


def test_weekly_endpoint_aggregates_tss_correctly():
    """AC2: total_tss is the sum of TSS across all workouts in the week."""
    run = _make_workout("run", tss=50.0, distance_km=10.0, workout_date="2025-01-07")
    lift = _make_workout("strength", tss=30.0, distance_km=0.0, workout_date="2025-01-08")
    client = _make_client()
    try:
        with patch("backend.main.Session") as mock_cls:
            mock_cls.return_value = _mock_session([run, lift])
            resp = client.get(
                "/api/training-load/weekly?from=2025-01-06&to=2025-01-12"
            )
        body = resp.json()
        wk = body["weeks"][0]
        assert abs(wk["total_tss"] - 80.0) < 0.01
    finally:
        _teardown()


def test_weekly_endpoint_aggregates_distance_correctly():
    """AC2: total_distance_km sums distance across all workouts in the week."""
    w1 = _make_workout("run", tss=50.0, distance_km=10.5, workout_date="2025-01-07")
    w2 = _make_workout("run", tss=30.0, distance_km=5.0, workout_date="2025-01-09")
    client = _make_client()
    try:
        with patch("backend.main.Session") as mock_cls:
            mock_cls.return_value = _mock_session([w1, w2])
            resp = client.get(
                "/api/training-load/weekly?from=2025-01-06&to=2025-01-12"
            )
        body = resp.json()
        wk = body["weeks"][0]
        assert abs(wk["total_distance_km"] - 15.5) < 0.01
    finally:
        _teardown()


def test_weekly_endpoint_splits_run_and_strength_tss():
    """AC2/AC5: response includes run_tss and strength_tss separately so the
    volume chart can render stacked bars."""
    run = _make_workout("run", tss=50.0, distance_km=10.0, workout_date="2025-01-07")
    lift = _make_workout("strength", tss=30.0, distance_km=0.0, workout_date="2025-01-08")
    client = _make_client()
    try:
        with patch("backend.main.Session") as mock_cls:
            mock_cls.return_value = _mock_session([run, lift])
            resp = client.get(
                "/api/training-load/weekly?from=2025-01-06&to=2025-01-12"
            )
        body = resp.json()
        wk = body["weeks"][0]
        assert "run_tss" in wk
        assert "strength_tss" in wk
        assert abs(wk["run_tss"] - 50.0) < 0.01
        assert abs(wk["strength_tss"] - 30.0) < 0.01
    finally:
        _teardown()


def test_weekly_endpoint_returns_correct_week_start():
    """AC2: week_start is the ISO date of the Monday that starts the week."""
    run = _make_workout("run", tss=20.0, distance_km=5.0, workout_date="2025-01-09")  # Thursday
    client = _make_client()
    try:
        with patch("backend.main.Session") as mock_cls:
            mock_cls.return_value = _mock_session([run])
            resp = client.get(
                "/api/training-load/weekly?from=2025-01-06&to=2025-01-12"
            )
        body = resp.json()
        assert len(body["weeks"]) == 1
        assert body["weeks"][0]["week_start"] == "2025-01-06"  # Monday
    finally:
        _teardown()


def test_weekly_endpoint_groups_multiple_weeks():
    """AC2: workouts in different weeks appear in separate week buckets."""
    w1 = _make_workout("run", tss=40.0, distance_km=8.0, workout_date="2025-01-07")  # week of Jan 6
    w2 = _make_workout("run", tss=35.0, distance_km=7.0, workout_date="2025-01-14")  # week of Jan 13
    client = _make_client()
    try:
        with patch("backend.main.Session") as mock_cls:
            mock_cls.return_value = _mock_session([w1, w2])
            resp = client.get(
                "/api/training-load/weekly?from=2025-01-06&to=2025-01-20"
            )
        body = resp.json()
        assert len(body["weeks"]) == 2
        starts = {wk["week_start"] for wk in body["weeks"]}
        assert "2025-01-06" in starts
        assert "2025-01-13" in starts
    finally:
        _teardown()


# ── AC3: renderVolumeChart() calls /api/training-load/weekly ─────────────────

def test_render_volume_chart_fetches_weekly_endpoint():
    """AC3: renderVolumeChart() in training-log.js calls /api/training-load/weekly."""
    # Find the renderVolumeChart function body
    m = re.search(
        r'function\s+renderVolumeChart\s*\(\s*\)(.*?)(?=\n  function\s+|\Z)',
        _JS,
        re.DOTALL,
    )
    assert m, "renderVolumeChart() function not found in training-log.js"
    fn_body = m.group(1)
    assert "/api/training-load/weekly" in fn_body, (
        "renderVolumeChart() must call /api/training-load/weekly"
    )


# ── AC4: renderVolumeChart() does NOT call /api/training-log ─────────────────

def test_render_volume_chart_does_not_fetch_training_log():
    """AC4: renderVolumeChart() must NOT make a request to /api/training-log
    (eliminates the redundant second fetch)."""
    m = re.search(
        r'function\s+renderVolumeChart\s*\(\s*\)(.*?)(?=\n  function\s+|\Z)',
        _JS,
        re.DOTALL,
    )
    assert m, "renderVolumeChart() function not found in training-log.js"
    fn_body = m.group(1)
    assert "/api/training-log" not in fn_body, (
        "renderVolumeChart() must NOT call /api/training-log — "
        "that endpoint is for the list only"
    )


# ── AC5: renderVolumeChart uses new field names from the weekly endpoint ──────

def test_render_volume_chart_uses_new_field_names():
    """AC5: renderVolumeChart() reads run_tss / strength_tss / total_distance_km
    from the weekly endpoint response (not the old weekVolumeByType approach)."""
    m = re.search(
        r'function\s+renderVolumeChart\s*\(\s*\)(.*?)(?=\n  function\s+|\Z)',
        _JS,
        re.DOTALL,
    )
    assert m, "renderVolumeChart() not found"
    fn_body = m.group(1)
    assert "run_tss" in fn_body or "strength_tss" in fn_body or "total_distance_km" in fn_body, (
        "renderVolumeChart() must use run_tss / strength_tss / total_distance_km "
        "from the /api/training-load/weekly response"
    )
