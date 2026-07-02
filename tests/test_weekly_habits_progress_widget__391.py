"""Tests for issue #391: Weekly habits-and-targets progress widget on home page.

TDD: each test class anchored to one Acceptance Criterion.
Static checks verify JS/HTML structure; API checks verify backend contract.
"""
import pathlib
import uuid
from unittest.mock import MagicMock, patch

REPO_ROOT = pathlib.Path(__file__).parent.parent


# ── AC: API contract — GET /api/habits returns list ───────────────────────────

def test_api_get_habits_requires_auth():
    """GET /api/habits returns 401 when unauthenticated."""
    from fastapi.testclient import TestClient
    from backend.main import app
    client = TestClient(app, raise_server_exceptions=False)
    res = client.get("/api/habits")
    assert res.status_code == 401, f"Expected 401, got {res.status_code}"


def test_api_get_habits_returns_list_with_auth():
    """GET /api/habits returns 200 list when authenticated."""
    from fastapi.testclient import TestClient
    from backend.main import app, resolve_user

    mock_user = MagicMock()
    mock_user.id = uuid.UUID("00000000-0000-0000-0000-000000000391")

    async def fake_resolve():
        return mock_user

    app.dependency_overrides[resolve_user] = fake_resolve
    try:
        with patch("backend.main.Session") as MockSession:
            mock_session = MagicMock()
            MockSession.return_value.__enter__ = MagicMock(return_value=mock_session)
            MockSession.return_value.__exit__ = MagicMock(return_value=False)
            mock_q = MagicMock()
            mock_session.query.return_value = mock_q
            mock_q.filter.return_value = mock_q
            mock_q.order_by.return_value = mock_q
            mock_q.all.return_value = []

            client = TestClient(app)
            res = client.get("/api/habits")
            assert res.status_code == 200
            assert res.json() == []
    finally:
        app.dependency_overrides.pop(resolve_user, None)


# ── AC: API contract — GET /api/habits/{id}/progress returns expected shape ───

def test_api_habit_progress_requires_auth():
    """GET /api/habits/{id}/progress returns 401 when unauthenticated."""
    from fastapi.testclient import TestClient
    from backend.main import app
    client = TestClient(app, raise_server_exceptions=False)
    hid = str(uuid.uuid4())
    res = client.get(f"/api/habits/{hid}/progress")
    assert res.status_code == 401, f"Expected 401, got {res.status_code}"


def test_api_habit_progress_shape():
    """GET /api/habits/{id}/progress returns required shape fields."""
    from fastapi.testclient import TestClient
    from backend.main import app, resolve_user
    from backend.models import Habit

    hid = uuid.uuid4()
    mock_user = MagicMock()
    mock_user.id = uuid.UUID("00000000-0000-0000-0000-000000000391")

    async def fake_resolve():
        return mock_user

    app.dependency_overrides[resolve_user] = fake_resolve
    try:
        with patch("backend.main.Session") as MockSession:
            mock_session = MagicMock()
            MockSession.return_value.__enter__ = MagicMock(return_value=mock_session)
            MockSession.return_value.__exit__ = MagicMock(return_value=False)

            mock_habit = MagicMock(spec=Habit)
            mock_habit.id = hid
            mock_habit.user_id = mock_user.id
            mock_habit.name = "Run"
            mock_habit.description = None
            mock_habit.tracking_type = "quantity"
            mock_habit.weekly_target = 210.0
            mock_habit.unit = "min"
            mock_habit.auto_fill_source = None
            mock_habit.icon = None
            mock_habit.color = None
            mock_habit.sort_order = 1
            mock_habit.is_archived = False
            ts = MagicMock()
            ts.isoformat.return_value = "2026-06-09T00:00:00+00:00"
            mock_habit.created_at = ts
            mock_habit.updated_at = None

            mock_session.get.return_value = mock_habit
            mock_q = MagicMock()
            mock_session.query.return_value = mock_q
            mock_q.filter.return_value = mock_q
            mock_q.all.return_value = []

            client = TestClient(app)
            week_start = "2026-06-09"
            res = client.get(f"/api/habits/{hid}/progress?week_start={week_start}")
            assert res.status_code == 200
            data = res.json()
            required_keys = {
                "habit", "week_start", "week_end", "target",
                "current_value", "percentage", "is_complete",
            }
            missing = required_keys - set(data.keys())
            assert not missing, f"Progress response missing keys: {missing}"
            assert data["is_complete"] is False
            assert data["current_value"] == 0.0
    finally:
        app.dependency_overrides.pop(resolve_user, None)
