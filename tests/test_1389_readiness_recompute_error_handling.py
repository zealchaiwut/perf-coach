"""
Tests for issue #1389: Readiness auto-recompute failure must not 500 a committed metric write.

AC coverage:
- AC1: POST /api/daily-metrics returns 201 with metric data even if
       _readiness_compute_and_store raises an exception.
- AC2: PATCH /api/daily-metrics/{uid}/{date} returns 200 with metric data even
       if _readiness_compute_and_store raises an exception.
- AC3: PUT /api/daily-metrics/{uid}/{date} returns 200 with metric data even if
       _readiness_compute_and_store raises an exception.
- AC4: The recompute failure is logged at warning level (not silently swallowed).
"""
import datetime
import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.main import app, resolve_user
from backend.models import User as _UserModel

_TEST_DATE = "2025-06-01"
_TOMORROW = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()

_FAKE_USER_ID = uuid.uuid4()
_FAKE_USER = _UserModel(
    id=_FAKE_USER_ID,
    name="testuser_1389",
    is_admin=False,
    is_active=True,
    password_hash="x",
)


def _user_override():
    return _FAKE_USER


def _make_metric_row():
    """Return a MagicMock that looks like a committed DailyMetric ORM row."""
    row = MagicMock()
    row.id = uuid.uuid4()
    row.user_id = _FAKE_USER_ID
    row.metric_date = datetime.date(2025, 6, 1)
    row.resting_hr = 55
    row.hrv = 65
    row.sleep_hours = 7.5
    row.sleep_quality = 4
    row.energy = 4
    row.mood = 4
    row.notes = "test"
    row.kcal_intake = None
    row.created_at = None
    row.updated_at = None
    return row


def _make_session_mock(row):
    """Return a context-manager-compatible session mock that succeeds on commit."""
    sess = MagicMock()
    sess.__enter__ = MagicMock(return_value=sess)
    sess.__exit__ = MagicMock(return_value=False)
    # query().filter().first() → return the row for PATCH/PUT
    sess.query.return_value.filter.return_value.first.return_value = row
    # refresh() sets up row attributes (already set above)
    sess.refresh = MagicMock()
    return sess


# ── AC1: POST returns 201 even when recompute raises ────────────────────────

def test_ac1_post_returns_201_when_recompute_raises():
    """AC1: Committed metric write returns 201 even if recompute throws."""
    row = _make_metric_row()
    sess_mock = _make_session_mock(row)

    app.dependency_overrides[resolve_user] = _user_override
    try:
        with (
            patch("backend.main.Session", return_value=sess_mock),
            patch(
                "backend.main._readiness_compute_and_store",
                side_effect=RuntimeError("recompute boom"),
            ),
            patch("backend.main._log") as mock_log,
        ):
            client = TestClient(app, raise_server_exceptions=False)
            payload = {
                "metric_date": _TEST_DATE,
                "resting_hr": 55,
                "hrv": 65,
                "sleep_hours": 7.5,
                "sleep_quality": 4,
                "energy": 4,
                "mood": 4,
            }
            res = client.post("/api/daily-metrics", json=payload)

        assert res.status_code == 201, (
            f"Expected 201 after recompute failure, got {res.status_code}: {res.text}"
        )
    finally:
        app.dependency_overrides.pop(resolve_user, None)


def test_ac1_post_returns_metric_data_when_recompute_raises():
    """AC1: Response body contains the metric data even if recompute fails."""
    row = _make_metric_row()
    sess_mock = _make_session_mock(row)

    app.dependency_overrides[resolve_user] = _user_override
    try:
        with (
            patch("backend.main.Session", return_value=sess_mock),
            patch(
                "backend.main._readiness_compute_and_store",
                side_effect=ValueError("signal missing"),
            ),
            patch("backend.main._log"),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            payload = {
                "metric_date": _TEST_DATE,
                "resting_hr": 55,
            }
            res = client.post("/api/daily-metrics", json=payload)

        assert res.status_code == 201
        # Response must be JSON (not an error page)
        data = res.json()
        assert isinstance(data, dict), "Response body must be a JSON object"
    finally:
        app.dependency_overrides.pop(resolve_user, None)


# ── AC2: PATCH returns 200 even when recompute raises ───────────────────────

def test_ac2_patch_returns_200_when_recompute_raises():
    """AC2: PATCH returns 200 with metric data even if recompute throws."""
    row = _make_metric_row()
    sess_mock = _make_session_mock(row)

    app.dependency_overrides[resolve_user] = _user_override
    uid_str = str(_FAKE_USER_ID)
    try:
        with (
            patch("backend.main.Session", return_value=sess_mock),
            patch(
                "backend.main._readiness_compute_and_store",
                side_effect=RuntimeError("recompute boom"),
            ),
            patch("backend.main._log"),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            payload = {"resting_hr": 60}
            res = client.patch(
                f"/api/daily-metrics/{uid_str}/{_TEST_DATE}", json=payload
            )

        assert res.status_code == 200, (
            f"Expected 200 after recompute failure, got {res.status_code}: {res.text}"
        )
    finally:
        app.dependency_overrides.pop(resolve_user, None)


def test_ac2_patch_returns_metric_data_when_recompute_raises():
    """AC2: PATCH response body is a JSON object, not an error, when recompute fails."""
    row = _make_metric_row()
    sess_mock = _make_session_mock(row)

    app.dependency_overrides[resolve_user] = _user_override
    uid_str = str(_FAKE_USER_ID)
    try:
        with (
            patch("backend.main.Session", return_value=sess_mock),
            patch(
                "backend.main._readiness_compute_and_store",
                side_effect=Exception("any failure"),
            ),
            patch("backend.main._log"),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            payload = {"hrv": 70}
            res = client.patch(
                f"/api/daily-metrics/{uid_str}/{_TEST_DATE}", json=payload
            )

        assert res.status_code == 200
        data = res.json()
        assert isinstance(data, dict), "Response body must be a JSON object"
    finally:
        app.dependency_overrides.pop(resolve_user, None)


# ── AC3: PUT returns 200 even when recompute raises ─────────────────────────

def test_ac3_put_returns_200_when_recompute_raises():
    """AC3: PUT returns 200 with metric data even if recompute throws."""
    row = _make_metric_row()
    sess_mock = _make_session_mock(row)

    app.dependency_overrides[resolve_user] = _user_override
    uid_str = str(_FAKE_USER_ID)
    try:
        with (
            patch("backend.main.Session", return_value=sess_mock),
            patch(
                "backend.main._readiness_compute_and_store",
                side_effect=RuntimeError("recompute boom"),
            ),
            patch("backend.main._log"),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            payload = {"resting_hr": 58, "hrv": 62}
            res = client.put(
                f"/api/daily-metrics/{uid_str}/{_TEST_DATE}", json=payload
            )

        assert res.status_code == 200, (
            f"Expected 200 after recompute failure, got {res.status_code}: {res.text}"
        )
    finally:
        app.dependency_overrides.pop(resolve_user, None)


def test_ac3_put_returns_metric_data_when_recompute_raises():
    """AC3: PUT response body is a JSON object, not an error, when recompute fails."""
    row = _make_metric_row()
    sess_mock = _make_session_mock(row)

    app.dependency_overrides[resolve_user] = _user_override
    uid_str = str(_FAKE_USER_ID)
    try:
        with (
            patch("backend.main.Session", return_value=sess_mock),
            patch(
                "backend.main._readiness_compute_and_store",
                side_effect=ValueError("signal missing"),
            ),
            patch("backend.main._log"),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            payload = {"resting_hr": 58}
            res = client.put(
                f"/api/daily-metrics/{uid_str}/{_TEST_DATE}", json=payload
            )

        assert res.status_code == 200
        data = res.json()
        assert isinstance(data, dict), "Response body must be a JSON object"
    finally:
        app.dependency_overrides.pop(resolve_user, None)


# ── AC4: Recompute failure is logged at warning level ───────────────────────

def test_ac4_post_logs_warning_when_recompute_raises():
    """AC4: POST handler logs a warning when recompute raises."""
    row = _make_metric_row()
    sess_mock = _make_session_mock(row)

    app.dependency_overrides[resolve_user] = _user_override
    try:
        with (
            patch("backend.main.Session", return_value=sess_mock),
            patch(
                "backend.main._readiness_compute_and_store",
                side_effect=RuntimeError("recompute boom"),
            ),
            patch("backend.main._log") as mock_log,
        ):
            client = TestClient(app, raise_server_exceptions=False)
            payload = {"metric_date": _TEST_DATE, "resting_hr": 55}
            client.post("/api/daily-metrics", json=payload)

        assert mock_log.warning.called or mock_log.exception.called, (
            "Expected _log.warning or _log.exception to be called when recompute raises"
        )
    finally:
        app.dependency_overrides.pop(resolve_user, None)


def test_ac4_patch_logs_warning_when_recompute_raises():
    """AC4: PATCH handler logs a warning when recompute raises."""
    row = _make_metric_row()
    sess_mock = _make_session_mock(row)

    app.dependency_overrides[resolve_user] = _user_override
    uid_str = str(_FAKE_USER_ID)
    try:
        with (
            patch("backend.main.Session", return_value=sess_mock),
            patch(
                "backend.main._readiness_compute_and_store",
                side_effect=RuntimeError("recompute boom"),
            ),
            patch("backend.main._log") as mock_log,
        ):
            client = TestClient(app, raise_server_exceptions=False)
            payload = {"resting_hr": 60}
            client.patch(f"/api/daily-metrics/{uid_str}/{_TEST_DATE}", json=payload)

        assert mock_log.warning.called or mock_log.exception.called, (
            "Expected _log.warning or _log.exception to be called when recompute raises"
        )
    finally:
        app.dependency_overrides.pop(resolve_user, None)


def test_ac4_put_logs_warning_when_recompute_raises():
    """AC4: PUT handler logs a warning when recompute raises."""
    row = _make_metric_row()
    sess_mock = _make_session_mock(row)

    app.dependency_overrides[resolve_user] = _user_override
    uid_str = str(_FAKE_USER_ID)
    try:
        with (
            patch("backend.main.Session", return_value=sess_mock),
            patch(
                "backend.main._readiness_compute_and_store",
                side_effect=RuntimeError("recompute boom"),
            ),
            patch("backend.main._log") as mock_log,
        ):
            client = TestClient(app, raise_server_exceptions=False)
            payload = {"resting_hr": 58}
            client.put(f"/api/daily-metrics/{uid_str}/{_TEST_DATE}", json=payload)

        assert mock_log.warning.called or mock_log.exception.called, (
            "Expected _log.warning or _log.exception to be called when recompute raises"
        )
    finally:
        app.dependency_overrides.pop(resolve_user, None)
