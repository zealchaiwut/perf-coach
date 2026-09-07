"""Tests for issue #1762: polled changes feed for recent races.

Acceptance criteria verified:
AC1: An endpoint returns races whose result or status changed since a caller-supplied timestamp or cursor.
AC2: A newly reconciled race result appears in the feed, covered by a test.
AC3: A newly detected personal record appears in the feed too.
AC4: The polling contract is documented: cursor semantics, expected poll frequency, and how far back the feed retains changes.
"""
import uuid
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch
from urllib.parse import quote as _quote

import pytest
from fastapi.testclient import TestClient

from backend.auth import resolve_user
from backend.main import app

_UID = uuid.UUID("00000000-0000-0000-0000-000000001762")
_RACE_ID = uuid.UUID("11111111-1111-1111-1111-111111111762")
_PR_ID = uuid.UUID("22222222-2222-2222-2222-222222221762")

_NOW = datetime(2026, 9, 7, 12, 0, 0, tzinfo=timezone.utc)
_CURSOR = datetime(2026, 9, 7, 0, 0, 0, tzinfo=timezone.utc)


class _FakeUser:
    id = _UID
    name = "test-user-1762"
    is_admin = False
    is_active = True


@pytest.fixture(autouse=True)
def _patch_resolve_user():
    app.dependency_overrides[resolve_user] = lambda: _FakeUser()
    yield
    app.dependency_overrides.pop(resolve_user, None)


def _client() -> TestClient:
    return TestClient(app, raise_server_exceptions=True)


def _make_race(
    race_id=_RACE_ID,
    user_id=_UID,
    name="Boston Marathon",
    race_date=date(2026, 9, 6),
    distance_km=Decimal("42.195"),
    priority="A",
    status="done",
    goal_time_seconds=10800,
    actual_time_seconds=11100,
    updated_at=None,
):
    r = MagicMock()
    r.id = race_id
    r.user_id = user_id
    r.name = name
    r.race_date = race_date
    r.distance_km = distance_km
    r.priority = priority
    r.status = status
    r.goal_time_seconds = goal_time_seconds
    r.actual_time_seconds = actual_time_seconds
    r.updated_at = updated_at or _CURSOR + timedelta(hours=1)
    return r


def _make_pr(
    pr_id=_PR_ID,
    user_id=_UID,
    track_key="marathon",
    track_name="Marathon",
    value_numeric=Decimal("11100"),
    achieved_on=date(2026, 9, 6),
    created_at=None,
):
    pr = MagicMock()
    pr.id = pr_id
    pr.user_id = user_id
    pr.track_key = track_key
    pr.track_name = track_name
    pr.value_numeric = value_numeric
    pr.achieved_on = achieved_on
    pr.created_at = created_at or _CURSOR + timedelta(hours=2)
    return pr


def _mock_session(races=None, prs=None):
    """Build a context-manager Session mock for the changes-feed endpoint."""
    mock_sess = MagicMock()
    mock_sess.__enter__ = MagicMock(return_value=mock_sess)
    mock_sess.__exit__ = MagicMock(return_value=False)

    def _query_side_effect(model):
        from backend.models import Race, PersonalRecord
        q = MagicMock()
        if model is Race:
            q.filter.return_value.order_by.return_value.all.return_value = races or []
        elif model is PersonalRecord:
            q.filter.return_value.order_by.return_value.all.return_value = prs or []
        return q

    mock_sess.query.side_effect = _query_side_effect

    mock_session_cls = MagicMock()
    mock_session_cls.return_value = mock_sess
    return mock_session_cls


def _get_feed(since=None, session_mock=None):
    if session_mock is None:
        session_mock = _mock_session()
    url = "/api/races/changes"
    if since is not None:
        url = f"{url}?since={_quote(since)}"
    with patch("backend.main.Session", session_mock):
        return _client().get(url)


# ── AC1: endpoint contract ────────────────────────────────────────────────────


def test_changes_feed_returns_200():
    """AC1: Endpoint returns 200 when authenticated."""
    resp = _get_feed(since=_CURSOR.isoformat())
    assert resp.status_code == 200


def test_changes_feed_requires_auth():
    """AC1: Unauthenticated request returns 401."""
    app.dependency_overrides.pop(resolve_user, None)
    try:
        resp = _client().get(f"/api/races/changes?since={_quote('2026-01-01T00:00:00+00:00')}")
        assert resp.status_code == 401
    finally:
        app.dependency_overrides[resolve_user] = lambda: _FakeUser()


def test_changes_feed_requires_since_param():
    """AC1: Missing `since` parameter returns 422."""
    with patch("backend.main.Session", _mock_session()):
        resp = _client().get("/api/races/changes")
    assert resp.status_code == 422


def test_changes_feed_rejects_invalid_since():
    """AC1: A non-ISO `since` value returns 400."""
    resp = _get_feed(since="not-a-timestamp")
    assert resp.status_code == 400


def test_changes_feed_response_has_version():
    """AC1: Response carries a 'version' field."""
    resp = _get_feed(since=_CURSOR.isoformat())
    assert resp.json()["version"] == "1"


def test_changes_feed_response_has_cursor_next():
    """AC1: Response carries a 'cursor_next' for the caller to store and reuse."""
    resp = _get_feed(since=_CURSOR.isoformat())
    body = resp.json()
    assert "cursor_next" in body
    assert body["cursor_next"] is not None


def test_changes_feed_response_has_races_list():
    """AC1: Response carries a 'races' list."""
    resp = _get_feed(since=_CURSOR.isoformat())
    assert "races" in resp.json()
    assert isinstance(resp.json()["races"], list)


def test_changes_feed_response_has_personal_records_list():
    """AC3: Response carries a 'personal_records' list."""
    resp = _get_feed(since=_CURSOR.isoformat())
    assert "personal_records" in resp.json()
    assert isinstance(resp.json()["personal_records"], list)


# ── AC1/AC2: race result changes in the feed ─────────────────────────────────


def test_changes_feed_includes_race_updated_after_cursor():
    """AC2: A race updated after the cursor appears in the feed."""
    race = _make_race(updated_at=_CURSOR + timedelta(hours=1))
    resp = _get_feed(since=_CURSOR.isoformat(), session_mock=_mock_session(races=[race]))
    body = resp.json()
    assert len(body["races"]) == 1
    assert body["races"][0]["id"] == str(_RACE_ID)


def test_changes_feed_race_entry_has_required_fields():
    """AC2: Each race entry includes id, name, race_date, status, updated_at."""
    race = _make_race()
    resp = _get_feed(since=_CURSOR.isoformat(), session_mock=_mock_session(races=[race]))
    entry = resp.json()["races"][0]
    for field in ("id", "name", "race_date", "status", "updated_at", "distance_km", "priority"):
        assert field in entry, f"missing field: {field}"


def test_changes_feed_race_entry_has_result_fields():
    """AC2: Each race entry includes goal_time_seconds and actual_time_seconds for result tracking."""
    race = _make_race(goal_time_seconds=10800, actual_time_seconds=11100)
    resp = _get_feed(since=_CURSOR.isoformat(), session_mock=_mock_session(races=[race]))
    entry = resp.json()["races"][0]
    assert entry["goal_time_seconds"] == 10800
    assert entry["actual_time_seconds"] == 11100


def test_changes_feed_done_race_with_result_has_result_change_type():
    """AC2: A 'done' race with actual_time_seconds set has change_type 'result'."""
    race = _make_race(status="done", actual_time_seconds=11100)
    resp = _get_feed(since=_CURSOR.isoformat(), session_mock=_mock_session(races=[race]))
    assert resp.json()["races"][0]["change_type"] == "result"


def test_changes_feed_abandoned_race_has_status_change_type():
    """AC1: An 'abandoned' race (no result) has change_type 'status'."""
    race = _make_race(status="abandoned", actual_time_seconds=None)
    resp = _get_feed(since=_CURSOR.isoformat(), session_mock=_mock_session(races=[race]))
    assert resp.json()["races"][0]["change_type"] == "status"


def test_changes_feed_empty_when_no_changes():
    """AC1: Empty lists when no races or PRs changed since the cursor."""
    resp = _get_feed(since=_CURSOR.isoformat(), session_mock=_mock_session(races=[], prs=[]))
    body = resp.json()
    assert body["races"] == []
    assert body["personal_records"] == []


# ── AC3: personal records in the feed ────────────────────────────────────────


def test_changes_feed_includes_pr_created_after_cursor():
    """AC3: A personal record created after the cursor appears in the feed."""
    pr = _make_pr(created_at=_CURSOR + timedelta(hours=2))
    resp = _get_feed(since=_CURSOR.isoformat(), session_mock=_mock_session(prs=[pr]))
    body = resp.json()
    assert len(body["personal_records"]) == 1
    assert body["personal_records"][0]["id"] == str(_PR_ID)


def test_changes_feed_pr_entry_has_required_fields():
    """AC3: Each PR entry includes id, track_key, track_name, value_numeric, achieved_on, created_at."""
    pr = _make_pr()
    resp = _get_feed(since=_CURSOR.isoformat(), session_mock=_mock_session(prs=[pr]))
    entry = resp.json()["personal_records"][0]
    for field in ("id", "track_key", "track_name", "value_numeric", "achieved_on", "created_at"):
        assert field in entry, f"missing field: {field}"


def test_changes_feed_pr_value_numeric_is_float():
    """AC3: value_numeric is returned as a float (not Decimal string)."""
    pr = _make_pr(value_numeric=Decimal("11100"))
    resp = _get_feed(since=_CURSOR.isoformat(), session_mock=_mock_session(prs=[pr]))
    val = resp.json()["personal_records"][0]["value_numeric"]
    assert isinstance(val, float)
    assert val == pytest.approx(11100.0)


def test_changes_feed_multiple_prs_returned():
    """AC3: Multiple PRs created after the cursor are all returned."""
    prs = [
        _make_pr(pr_id=uuid.UUID("22222222-2222-2222-2222-00000000000" + str(i)), track_key=f"dist_{i}")
        for i in range(1, 4)
    ]
    resp = _get_feed(since=_CURSOR.isoformat(), session_mock=_mock_session(prs=prs))
    assert len(resp.json()["personal_records"]) == 3


# ── AC4: polling contract ─────────────────────────────────────────────────────


def test_changes_feed_cursor_next_is_iso_string():
    """AC4: cursor_next is an ISO 8601 string parseable as a datetime."""
    resp = _get_feed(since=_CURSOR.isoformat())
    cursor_next = resp.json()["cursor_next"]
    # Must be parseable
    dt = datetime.fromisoformat(cursor_next)
    assert dt is not None


def test_changes_feed_response_has_retention_days():
    """AC4: Response documents the retention window in 'retention_days'."""
    resp = _get_feed(since=_CURSOR.isoformat())
    body = resp.json()
    assert "retention_days" in body
    assert isinstance(body["retention_days"], int)
    assert body["retention_days"] > 0


def test_changes_feed_response_has_poll_interval_seconds():
    """AC4: Response documents recommended poll frequency in 'poll_interval_seconds'."""
    resp = _get_feed(since=_CURSOR.isoformat())
    body = resp.json()
    assert "poll_interval_seconds" in body
    assert isinstance(body["poll_interval_seconds"], int)
    assert body["poll_interval_seconds"] > 0
