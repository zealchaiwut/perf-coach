"""Tests for issue #471: Add test coverage for habit log date parsing validation.

[follow-up] Context: sprint sprint-86 review of #455 — issue #468 suggested adding explicit
test coverage for invalid date string handling in the habit log endpoint.

AC items:
  (1) Invalid date string 'not-a-date' is rejected with error response (HTTP 400)
  (2) Malformed ISO string '2026-13-45' is rejected with error response (HTTP 400)
  (3) Incomplete date '2026-06' is rejected with error response (HTTP 400)
  (4) Wrong date format '06/11/2026' (MM/DD/YYYY) is rejected with error response (HTTP 400)
  (5) Empty string '' is rejected with error response (HTTP 400)
  (6) Out-of-range month '2026-13-01' is rejected with error response (HTTP 400)
  (7) Out-of-range day '2026-06-32' is rejected with error response (HTTP 400)
  (8) Valid ISO date format '2026-06-11' is accepted and processed successfully (HTTP 201)
"""
import uuid
from datetime import date
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from backend.main import app, resolve_user
from backend.models import Habit, HabitLog

_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000455")
_TODAY = date(2026, 6, 11)
_WEEK_MONDAY = date(2026, 6, 8)


def _make_user():
    u = MagicMock()
    u.id = _USER_ID
    return u


def _make_client():
    mock_user = _make_user()

    async def _fake_resolve():
        return mock_user

    app.dependency_overrides[resolve_user] = _fake_resolve
    return TestClient(app), mock_user


def _teardown():
    app.dependency_overrides.pop(resolve_user, None)


def _make_habit(hid=None):
    h = MagicMock(spec=Habit)
    h.id = hid or uuid.uuid4()
    h.user_id = _USER_ID
    h.tracking_type = "daily_checkmark"
    return h


def _make_log(habit_id, log_date=None):
    log = MagicMock(spec=HabitLog)
    log.id = uuid.uuid4()
    log.habit_id = habit_id
    log.user_id = _USER_ID
    log.log_date = log_date or _TODAY
    log.log_week_start = _WEEK_MONDAY
    log.value = 1.0
    log.notes = None
    log.source = "manual"
    ts = MagicMock()
    ts.isoformat.return_value = "2026-06-11T00:00:00+00:00"
    log.created_at = ts
    log.updated_at = None
    return log


def _make_session(habit, log_after_commit=None, raise_integrity=False):
    sess = MagicMock()
    sess.__enter__ = MagicMock(return_value=sess)
    sess.__exit__ = MagicMock(return_value=False)
    sess.get.return_value = habit
    if raise_integrity:
        sess.commit.side_effect = IntegrityError("", {}, Exception())
    else:
        def _refresh(obj):
            pass
        sess.refresh = _refresh
        if log_after_commit is not None:
            sess.add.side_effect = lambda obj: setattr(obj, "id", log_after_commit.id)
    return sess


# ── AC (1) & (3): POST /api/habits/logs returns 201 on first save ─────────────

class TestAC1_SaveTodayReturns201:
    """AC1 + AC3: valid save of today's habit log returns 201, no 500."""

    def test_first_time_save_returns_201(self):
        client, _ = _make_client()
        habit = _make_habit()
        saved_log = _make_log(habit.id)

        sess = MagicMock()
        sess.__enter__ = MagicMock(return_value=sess)
        sess.__exit__ = MagicMock(return_value=False)
        sess.get.return_value = habit

        created_log = MagicMock(spec=HabitLog)
        created_log.id = saved_log.id
        created_log.habit_id = habit.id
        created_log.user_id = _USER_ID
        created_log.log_date = _TODAY
        created_log.log_week_start = _WEEK_MONDAY
        created_log.value = 1.0
        created_log.notes = None
        created_log.source = "manual"
        ts = MagicMock()
        ts.isoformat.return_value = "2026-06-11T00:00:00+00:00"
        created_log.created_at = ts
        created_log.updated_at = None

        # Capture the HabitLog object added to session and set id on refresh
        added_obj = []

        def _add(obj):
            added_obj.append(obj)

        def _refresh(obj):
            obj.id = saved_log.id
            obj.created_at = ts
            obj.updated_at = None

        sess.add = _add
        sess.refresh = _refresh

        with patch("backend.main.Session", return_value=sess):
            r = client.post(
                "/api/habits/logs",
                json={"habit_id": str(habit.id), "logged_date": _TODAY.isoformat()},
            )
        _teardown()

        assert r.status_code == 201, f"Expected 201, got {r.status_code}: {r.text}"

    def test_response_is_not_500(self):
        """Ensures the endpoint does not raise an internal server error."""
        client, _ = _make_client()
        habit = _make_habit()

        sess = MagicMock()
        sess.__enter__ = MagicMock(return_value=sess)
        sess.__exit__ = MagicMock(return_value=False)
        sess.get.return_value = habit

        ts = MagicMock()
        ts.isoformat.return_value = "2026-06-11T00:00:00+00:00"

        def _refresh(obj):
            obj.id = uuid.uuid4()
            obj.created_at = ts
            obj.updated_at = None

        sess.refresh = _refresh

        with patch("backend.main.Session", return_value=sess):
            r = client.post(
                "/api/habits/logs",
                json={"habit_id": str(habit.id), "logged_date": _TODAY.isoformat()},
            )
        _teardown()

        assert r.status_code != 500, f"Got 500: {r.text}"


# ── AC (2): response includes id so UI can reference the log ──────────────────

class TestAC2_ResponseIncludesId:
    """AC2: saved log id is returned so the frontend can delete it later."""

    def test_response_includes_id(self):
        client, _ = _make_client()
        habit = _make_habit()
        log_id = uuid.uuid4()

        sess = MagicMock()
        sess.__enter__ = MagicMock(return_value=sess)
        sess.__exit__ = MagicMock(return_value=False)
        sess.get.return_value = habit

        ts = MagicMock()
        ts.isoformat.return_value = "2026-06-11T00:00:00+00:00"

        def _refresh(obj):
            obj.id = log_id
            obj.created_at = ts
            obj.updated_at = None

        sess.refresh = _refresh

        with patch("backend.main.Session", return_value=sess):
            r = client.post(
                "/api/habits/logs",
                json={"habit_id": str(habit.id), "logged_date": _TODAY.isoformat()},
            )
        _teardown()

        assert r.status_code == 201
        data = r.json()
        assert "id" in data, f"Response missing 'id': {data}"
        assert data["id"] == str(log_id)


# ── AC (4): unknown habit returns 404 with error detail ───────────────────────

class TestAC4_ValidationError:
    """AC4: saving for a non-existent habit returns 404, not 500."""

    def test_unknown_habit_returns_404(self):
        client, _ = _make_client()
        sess = MagicMock()
        sess.__enter__ = MagicMock(return_value=sess)
        sess.__exit__ = MagicMock(return_value=False)
        sess.get.return_value = None  # habit not found

        with patch("backend.main.Session", return_value=sess):
            r = client.post(
                "/api/habits/logs",
                json={"habit_id": str(uuid.uuid4()), "logged_date": _TODAY.isoformat()},
            )
        _teardown()

        assert r.status_code == 404
        body = r.json()
        assert "detail" in body


# ── AC (5): duplicate entry returns 409, not 500 ─────────────────────────────

class TestAC5_DuplicateEntryReturns409:
    """AC5: saving the same date twice returns 409 conflict, not 500."""

    def test_duplicate_log_returns_409(self):
        client, _ = _make_client()
        habit = _make_habit()

        sess = MagicMock()
        sess.__enter__ = MagicMock(return_value=sess)
        sess.__exit__ = MagicMock(return_value=False)
        sess.get.return_value = habit
        sess.commit.side_effect = IntegrityError("", {}, Exception())

        with patch("backend.main.Session", return_value=sess):
            r = client.post(
                "/api/habits/logs",
                json={"habit_id": str(habit.id), "logged_date": _TODAY.isoformat()},
            )
        _teardown()

        assert r.status_code == 409


# ── AC (5): HabitLog is created with log_date, not logged_date ───────────────

class TestAC5_CorrectFieldNames:
    """AC5: HabitLog is constructed with log_date and log_week_start."""

    def test_habit_log_uses_log_date_not_logged_date(self):
        """Verify that the HabitLog object added to session uses log_date."""
        client, _ = _make_client()
        habit = _make_habit()

        sess = MagicMock()
        sess.__enter__ = MagicMock(return_value=sess)
        sess.__exit__ = MagicMock(return_value=False)
        sess.get.return_value = habit

        ts = MagicMock()
        ts.isoformat.return_value = "2026-06-11T00:00:00+00:00"

        added_obj = []

        def _add(obj):
            added_obj.append(obj)

        def _refresh(obj):
            obj.id = uuid.uuid4()
            obj.created_at = ts
            obj.updated_at = None

        sess.add = _add
        sess.refresh = _refresh

        with patch("backend.main.Session", return_value=sess):
            r = client.post(
                "/api/habits/logs",
                json={"habit_id": str(habit.id), "logged_date": _TODAY.isoformat()},
            )
        _teardown()

        assert r.status_code == 201
        assert len(added_obj) == 1
        obj = added_obj[0]
        assert hasattr(obj, "log_date") or obj.log_date is not None, \
            "HabitLog must be constructed with log_date, not logged_date"
        assert obj.log_date == _TODAY, \
            f"log_date should be {_TODAY}, got {obj.log_date}"
        assert obj.log_week_start == _WEEK_MONDAY, \
            f"log_week_start should be {_WEEK_MONDAY}, got {obj.log_week_start}"


# ── Invalid Date Format Coverage (Issue #471) ────────────────────────────────

class TestInvalidDateFormatParsing:
    """Coverage for date parsing error handling with invalid date strings.

    Tests invalid dates passed to POST /api/habits/logs.
    The endpoint parses logged_date (str) with _date.fromisoformat() in a try/except,
    returning HTTP 400 (Bad Request) for parse failures.
    """

    def test_invalid_date_string_not_a_date(self):
        """Invalid string 'not-a-date' should fail parsing and return 400."""
        client, _ = _make_client()
        habit = _make_habit()

        with patch("backend.main.Session") as mock_session_class:
            mock_session = MagicMock()
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=False)
            mock_session.get.return_value = habit
            mock_session_class.return_value = mock_session

            r = client.post(
                "/api/habits/logs",
                json={"habit_id": str(habit.id), "logged_date": "not-a-date"},
            )
        _teardown()

        assert r.status_code == 400, f"Expected 400 for 'not-a-date', got {r.status_code}: {r.text}"
        body = r.json()
        assert "detail" in body
        assert "Invalid date format" in str(body)

    def test_invalid_date_string_malformed_iso(self):
        """Malformed ISO string '2026-13-45' should fail parsing."""
        client, _ = _make_client()
        habit = _make_habit()

        with patch("backend.main.Session") as mock_session_class:
            mock_session = MagicMock()
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=False)
            mock_session.get.return_value = habit
            mock_session_class.return_value = mock_session

            r = client.post(
                "/api/habits/logs",
                json={"habit_id": str(habit.id), "logged_date": "2026-13-45"},
            )
        _teardown()

        assert r.status_code == 400, f"Expected 400 for '2026-13-45', got {r.status_code}: {r.text}"
        body = r.json()
        assert "Invalid date format" in str(body)

    def test_invalid_date_string_missing_components(self):
        """Incomplete date '2026-06' should fail parsing."""
        client, _ = _make_client()
        habit = _make_habit()

        with patch("backend.main.Session") as mock_session_class:
            mock_session = MagicMock()
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=False)
            mock_session.get.return_value = habit
            mock_session_class.return_value = mock_session

            r = client.post(
                "/api/habits/logs",
                json={"habit_id": str(habit.id), "logged_date": "2026-06"},
            )
        _teardown()

        assert r.status_code == 400, f"Expected 400 for '2026-06', got {r.status_code}: {r.text}"

    def test_invalid_date_string_wrong_format(self):
        """Date in MM/DD/YYYY format '06/11/2026' should fail (not ISO)."""
        client, _ = _make_client()
        habit = _make_habit()

        with patch("backend.main.Session") as mock_session_class:
            mock_session = MagicMock()
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=False)
            mock_session.get.return_value = habit
            mock_session_class.return_value = mock_session

            r = client.post(
                "/api/habits/logs",
                json={"habit_id": str(habit.id), "logged_date": "06/11/2026"},
            )
        _teardown()

        assert r.status_code == 400, f"Expected 400 for '06/11/2026', got {r.status_code}: {r.text}"

    def test_invalid_date_string_empty(self):
        """Empty string '' should fail parsing."""
        client, _ = _make_client()
        habit = _make_habit()

        with patch("backend.main.Session") as mock_session_class:
            mock_session = MagicMock()
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=False)
            mock_session.get.return_value = habit
            mock_session_class.return_value = mock_session

            r = client.post(
                "/api/habits/logs",
                json={"habit_id": str(habit.id), "logged_date": ""},
            )
        _teardown()

        assert r.status_code == 400, f"Expected 400 for empty string, got {r.status_code}: {r.text}"

    def test_invalid_date_month_out_of_range(self):
        """Month 13 '2026-13-01' should fail parsing."""
        client, _ = _make_client()
        habit = _make_habit()

        with patch("backend.main.Session") as mock_session_class:
            mock_session = MagicMock()
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=False)
            mock_session.get.return_value = habit
            mock_session_class.return_value = mock_session

            r = client.post(
                "/api/habits/logs",
                json={"habit_id": str(habit.id), "logged_date": "2026-13-01"},
            )
        _teardown()

        assert r.status_code == 400, f"Expected 400 for month 13, got {r.status_code}: {r.text}"

    def test_invalid_date_day_out_of_range(self):
        """Day 32 '2026-06-32' should fail parsing."""
        client, _ = _make_client()
        habit = _make_habit()

        with patch("backend.main.Session") as mock_session_class:
            mock_session = MagicMock()
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=False)
            mock_session.get.return_value = habit
            mock_session_class.return_value = mock_session

            r = client.post(
                "/api/habits/logs",
                json={"habit_id": str(habit.id), "logged_date": "2026-06-32"},
            )
        _teardown()

        assert r.status_code == 400, f"Expected 400 for day 32, got {r.status_code}: {r.text}"

    def test_valid_date_iso_format_succeeds(self):
        """Valid ISO date '2026-06-11' should succeed (sanity check)."""
        client, _ = _make_client()
        habit = _make_habit()

        sess = MagicMock()
        sess.__enter__ = MagicMock(return_value=sess)
        sess.__exit__ = MagicMock(return_value=False)
        sess.get.return_value = habit

        ts = MagicMock()
        ts.isoformat.return_value = "2026-06-11T00:00:00+00:00"

        def _refresh(obj):
            obj.id = uuid.uuid4()
            obj.created_at = ts
            obj.updated_at = None

        sess.refresh = _refresh

        with patch("backend.main.Session", return_value=sess):
            r = client.post(
                "/api/habits/logs",
                json={"habit_id": str(habit.id), "logged_date": _TODAY.isoformat()},
            )
        _teardown()

        assert r.status_code == 201, f"Expected 201 for valid date, got {r.status_code}: {r.text}"
