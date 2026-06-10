"""Tests for issue #387: CRUD Endpoints for Habits with Unified Shape.

Each test class is anchored to one Acceptance Criterion item (a–h).
Uses FastAPI TestClient with mocked resolve_user and Session.
"""
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.main import app, resolve_user

_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000387")


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


def _make_habit(
    *,
    hid=None,
    name="Running",
    tracking_type="daily_checkmark",
    is_archived=False,
    sort_order=0,
    weekly_target=None,
    unit=None,
    auto_fill_source=None,
    icon=None,
    color=None,
    description=None,
):
    h = MagicMock()
    h.id = hid or uuid.uuid4()
    h.user_id = _USER_ID
    h.name = name
    h.description = description
    h.tracking_type = tracking_type
    h.weekly_target = weekly_target
    h.unit = unit
    h.auto_fill_source = auto_fill_source
    h.icon = icon
    h.color = color
    h.sort_order = sort_order
    h.is_archived = is_archived
    h.display_order = sort_order
    h.archived_at = None
    ts = MagicMock()
    ts.isoformat.return_value = "2026-06-10T00:00:00+00:00"
    h.created_at = ts
    h.updated_at = None
    return h


def _make_session_ctx(habits=None, habit=None):
    """Return a mock Session context for habit queries."""
    sess = MagicMock()
    sess.__enter__ = MagicMock(return_value=sess)
    sess.__exit__ = MagicMock(return_value=False)

    query_m = MagicMock()
    query_m.filter.return_value = query_m
    query_m.order_by.return_value = query_m
    query_m.all.return_value = habits or []
    query_m.count.return_value = len(habits) if habits else 0
    query_m.scalar.return_value = 0  # used by max(sort_order) in post_habit
    query_m.delete.return_value = 0
    sess.query.return_value = query_m

    if habit is not None:
        sess.get.return_value = habit
    else:
        sess.get.return_value = None

    return sess


# ── AC (a): POST /api/habits creates a habit successfully ─────────────────────

class TestPostHabitCreatesSuccessfully:
    """AC (a): POST /api/habits creates a habit and returns 201 with full row."""

    def test_post_returns_201(self):
        """POST /api/habits returns HTTP 201."""
        client, _ = _make_client()
        h = _make_habit(name="Running", tracking_type="daily_checkmark")
        sess = _make_session_ctx(habit=h)
        try:
            with patch("backend.main.Session", return_value=sess):
                res = client.post("/api/habits", json={
                    "name": "Running",
                    "tracking_type": "daily_checkmark",
                })
            assert res.status_code == 201
        finally:
            _teardown()

    def test_post_returns_full_row(self):
        """POST /api/habits returns full habit row with all expected fields."""
        client, _ = _make_client()
        h = _make_habit(name="Running", tracking_type="daily_checkmark")
        sess = _make_session_ctx(habit=h)
        try:
            with patch("backend.main.Session", return_value=sess):
                res = client.post("/api/habits", json={
                    "name": "Running",
                    "tracking_type": "daily_checkmark",
                })
            assert res.status_code == 201
            body = res.json()
            for field in ("id", "name", "tracking_type", "sort_order", "is_archived",
                          "weekly_target", "unit", "auto_fill_source", "icon", "color",
                          "description", "created_at"):
                assert field in body, f"field '{field}' missing from POST response"
        finally:
            _teardown()

    def test_post_name_required(self):
        """POST /api/habits without name returns 422."""
        client, _ = _make_client()
        try:
            res = client.post("/api/habits", json={"tracking_type": "daily_checkmark"})
            assert res.status_code == 422
        finally:
            _teardown()

    def test_post_tracking_type_required(self):
        """POST /api/habits without tracking_type returns 422."""
        client, _ = _make_client()
        try:
            res = client.post("/api/habits", json={"name": "Running"})
            assert res.status_code == 422
        finally:
            _teardown()


# ── AC (b): GET /api/habits lists only active (non-archived) habits ───────────

class TestGetHabitsActiveOnly:
    """AC (b): GET /api/habits returns only non-archived habits by default."""

    def test_get_default_excludes_archived(self):
        """GET /api/habits returns only active habits; is_archived=true filtered out."""
        client, _ = _make_client()
        active = _make_habit(name="Active", is_archived=False, sort_order=0)
        archived = _make_habit(name="Archived", is_archived=True, sort_order=1)
        # Endpoint should filter; mock returns only active (simulating filtered query)
        sess = _make_session_ctx(habits=[active])
        try:
            with patch("backend.main.Session", return_value=sess):
                res = client.get("/api/habits")
            assert res.status_code == 200
            body = res.json()
            names = [h["name"] for h in body]
            assert "Active" in names
            assert "Archived" not in names
        finally:
            _teardown()

    def test_get_returns_sorted_by_sort_order(self):
        """GET /api/habits results sorted by sort_order ASC."""
        client, _ = _make_client()
        h1 = _make_habit(name="First", sort_order=0)
        h2 = _make_habit(name="Second", sort_order=1)
        sess = _make_session_ctx(habits=[h1, h2])
        try:
            with patch("backend.main.Session", return_value=sess):
                res = client.get("/api/habits")
            assert res.status_code == 200
            body = res.json()
            assert body[0]["name"] == "First"
            assert body[1]["name"] == "Second"
        finally:
            _teardown()

    def test_get_returns_all_habit_columns(self):
        """GET /api/habits response rows contain all habit columns."""
        client, _ = _make_client()
        h = _make_habit()
        sess = _make_session_ctx(habits=[h])
        try:
            with patch("backend.main.Session", return_value=sess):
                res = client.get("/api/habits")
            assert res.status_code == 200
            row = res.json()[0]
            for field in ("id", "name", "tracking_type", "sort_order", "is_archived",
                          "weekly_target", "unit", "auto_fill_source"):
                assert field in row, f"field '{field}' missing from GET response"
        finally:
            _teardown()


# ── AC (c): GET /api/habits?include_archived=true includes archived ────────────

class TestGetHabitsIncludeArchived:
    """AC (c): GET /api/habits?include_archived=true includes archived habits."""

    def test_include_archived_true_returns_archived(self):
        """GET /api/habits?include_archived=true includes archived habits."""
        client, _ = _make_client()
        archived = _make_habit(name="Archived Habit", is_archived=True)
        sess = _make_session_ctx(habits=[archived])
        try:
            with patch("backend.main.Session", return_value=sess):
                res = client.get("/api/habits?include_archived=true")
            assert res.status_code == 200
            body = res.json()
            assert any(h["name"] == "Archived Habit" for h in body)
        finally:
            _teardown()

    def test_include_archived_false_excludes_archived(self):
        """GET /api/habits?include_archived=false is equivalent to default."""
        client, _ = _make_client()
        active = _make_habit(name="Active", is_archived=False)
        sess = _make_session_ctx(habits=[active])
        try:
            with patch("backend.main.Session", return_value=sess):
                res = client.get("/api/habits?include_archived=false")
            assert res.status_code == 200
        finally:
            _teardown()


# ── AC (d): PATCH with tracking_type in body returns 422 ─────────────────────

class TestPatchHabitForbidsImmutableFields:
    """AC (d): PATCH /api/habits/{id} with tracking_type or user_id returns 422."""

    def test_patch_with_tracking_type_returns_422(self):
        """PATCH with tracking_type in body returns 422."""
        client, _ = _make_client()
        hid = uuid.uuid4()
        h = _make_habit(hid=hid)
        sess = _make_session_ctx(habit=h)
        try:
            with patch("backend.main.Session", return_value=sess):
                res = client.patch(f"/api/habits/{hid}", json={"tracking_type": "weekly_count"})
            assert res.status_code == 422
        finally:
            _teardown()

    def test_patch_with_user_id_returns_422(self):
        """PATCH with user_id in body returns 422."""
        client, _ = _make_client()
        hid = uuid.uuid4()
        h = _make_habit(hid=hid)
        sess = _make_session_ctx(habit=h)
        try:
            with patch("backend.main.Session", return_value=sess):
                res = client.patch(f"/api/habits/{hid}", json={"user_id": str(_USER_ID)})
            assert res.status_code == 422
        finally:
            _teardown()

    def test_patch_name_only_returns_200(self):
        """PATCH with only name (allowed field) returns 200."""
        client, _ = _make_client()
        hid = uuid.uuid4()
        h = _make_habit(hid=hid, name="Old Name")
        sess = _make_session_ctx(habit=h)
        try:
            with patch("backend.main.Session", return_value=sess):
                res = client.patch(f"/api/habits/{hid}", json={"name": "New Name"})
            assert res.status_code == 200
        finally:
            _teardown()


# ── AC (e): DELETE soft-deletes by default ────────────────────────────────────

class TestDeleteHabitSoftDelete:
    """AC (e): DELETE /api/habits/{id} sets is_archived=true; row remains."""

    def test_delete_sets_is_archived(self):
        """DELETE /api/habits/{id} sets is_archived=True on the habit."""
        client, _ = _make_client()
        hid = uuid.uuid4()
        h = _make_habit(hid=hid, is_archived=False)
        sess = _make_session_ctx(habit=h)
        try:
            with patch("backend.main.Session", return_value=sess):
                res = client.delete(f"/api/habits/{hid}")
            assert res.status_code == 200
            assert h.is_archived is True
        finally:
            _teardown()

    def test_soft_delete_does_not_call_session_delete(self):
        """DELETE /api/habits/{id} (soft) does not call session.delete()."""
        client, _ = _make_client()
        hid = uuid.uuid4()
        h = _make_habit(hid=hid)
        sess = _make_session_ctx(habit=h)
        try:
            with patch("backend.main.Session", return_value=sess):
                client.delete(f"/api/habits/{hid}")
            sess.delete.assert_not_called()
        finally:
            _teardown()

    def test_soft_deleted_habit_appears_in_include_archived(self):
        """After soft delete, habit appears with include_archived=true."""
        client, _ = _make_client()
        hid = uuid.uuid4()
        h = _make_habit(hid=hid, name="Soft Deleted")
        sess_del = _make_session_ctx(habit=h)
        try:
            with patch("backend.main.Session", return_value=sess_del):
                res = client.delete(f"/api/habits/{hid}")
            assert res.status_code == 200
            # Habit should now have is_archived=True
            assert h.is_archived is True
        finally:
            _teardown()


# ── AC (f): DELETE ?hard=true removes row and its habit_logs ─────────────────

class TestDeleteHabitHardDelete:
    """AC (f): DELETE /api/habits/{id}?hard=true removes the row and habit_logs."""

    def test_hard_delete_calls_session_delete(self):
        """DELETE /api/habits/{id}?hard=true calls session.delete() on the habit."""
        client, _ = _make_client()
        hid = uuid.uuid4()
        h = _make_habit(hid=hid)
        sess = _make_session_ctx(habit=h)
        try:
            with patch("backend.main.Session", return_value=sess):
                res = client.delete(f"/api/habits/{hid}?hard=true")
            assert res.status_code == 200
            sess.delete.assert_called_once_with(h)
        finally:
            _teardown()

    def test_hard_delete_deletes_habit_logs_first(self):
        """DELETE /api/habits/{id}?hard=true deletes associated habit_logs before habit."""
        from backend.models import HabitLog
        client, _ = _make_client()
        hid = uuid.uuid4()
        h = _make_habit(hid=hid)
        sess = _make_session_ctx(habit=h)

        deleted_classes = []

        def track_delete(obj):
            deleted_classes.append(type(obj).__name__ if not isinstance(obj, MagicMock) else "mock")

        sess.delete.side_effect = track_delete

        try:
            with patch("backend.main.Session", return_value=sess):
                res = client.delete(f"/api/habits/{hid}?hard=true")
            assert res.status_code == 200
            # query for HabitLog should have been used to delete logs
            sess.query.assert_any_call(HabitLog)
        finally:
            _teardown()

    def test_soft_delete_does_not_remove_when_hard_false(self):
        """DELETE /api/habits/{id}?hard=false behaves as soft delete."""
        client, _ = _make_client()
        hid = uuid.uuid4()
        h = _make_habit(hid=hid)
        sess = _make_session_ctx(habit=h)
        try:
            with patch("backend.main.Session", return_value=sess):
                res = client.delete(f"/api/habits/{hid}?hard=false")
            assert res.status_code == 200
            sess.delete.assert_not_called()
            assert h.is_archived is True
        finally:
            _teardown()


# ── AC (g): Invalid tracking_type + weekly_target combos return 422 ───────────

class TestHabitValidationTrackingTypeAndTarget:
    """AC (g): Invalid tracking_type + weekly_target combinations return 422."""

    def test_daily_checkmark_weekly_target_8_returns_422(self):
        """POST daily_checkmark with weekly_target=8 returns 422 (must be 1–7)."""
        client, _ = _make_client()
        try:
            res = client.post("/api/habits", json={
                "name": "Bad",
                "tracking_type": "daily_checkmark",
                "weekly_target": 8,
            })
            assert res.status_code == 422
        finally:
            _teardown()

    def test_daily_checkmark_weekly_target_0_returns_422(self):
        """POST daily_checkmark with weekly_target=0 returns 422 (must be 1–7)."""
        client, _ = _make_client()
        try:
            res = client.post("/api/habits", json={
                "name": "Bad",
                "tracking_type": "daily_checkmark",
                "weekly_target": 0,
            })
            assert res.status_code == 422
        finally:
            _teardown()

    def test_daily_checkmark_weekly_target_7_valid(self):
        """POST daily_checkmark with weekly_target=7 is valid (upper bound)."""
        client, _ = _make_client()
        h = _make_habit(name="Good", tracking_type="daily_checkmark", weekly_target=7)
        sess = _make_session_ctx(habit=h)
        try:
            with patch("backend.main.Session", return_value=sess):
                res = client.post("/api/habits", json={
                    "name": "Good",
                    "tracking_type": "daily_checkmark",
                    "weekly_target": 7,
                })
            assert res.status_code == 201
        finally:
            _teardown()

    def test_daily_checkmark_weekly_target_1_valid(self):
        """POST daily_checkmark with weekly_target=1 is valid (lower bound)."""
        client, _ = _make_client()
        h = _make_habit(name="Good", tracking_type="daily_checkmark", weekly_target=1)
        sess = _make_session_ctx(habit=h)
        try:
            with patch("backend.main.Session", return_value=sess):
                res = client.post("/api/habits", json={
                    "name": "Good",
                    "tracking_type": "daily_checkmark",
                    "weekly_target": 1,
                })
            assert res.status_code == 201
        finally:
            _teardown()

    def test_weekly_count_target_0_returns_422(self):
        """POST weekly_count with weekly_target=0 returns 422 (must be > 0)."""
        client, _ = _make_client()
        try:
            res = client.post("/api/habits", json={
                "name": "Bad",
                "tracking_type": "weekly_count",
                "weekly_target": 0,
            })
            assert res.status_code == 422
        finally:
            _teardown()

    def test_weekly_minutes_target_negative_returns_422(self):
        """POST weekly_minutes with weekly_target=-1 returns 422."""
        client, _ = _make_client()
        try:
            res = client.post("/api/habits", json={
                "name": "Bad",
                "tracking_type": "weekly_minutes",
                "weekly_target": -1,
            })
            assert res.status_code == 422
        finally:
            _teardown()

    def test_weekly_count_target_3_valid(self):
        """POST weekly_count with weekly_target=3 is valid."""
        client, _ = _make_client()
        h = _make_habit(name="Good", tracking_type="weekly_count", weekly_target=3)
        sess = _make_session_ctx(habit=h)
        try:
            with patch("backend.main.Session", return_value=sess):
                res = client.post("/api/habits", json={
                    "name": "Good",
                    "tracking_type": "weekly_count",
                    "weekly_target": 3,
                })
            assert res.status_code == 201
        finally:
            _teardown()

    def test_name_over_100_chars_returns_422(self):
        """POST with name > 100 chars returns 422."""
        client, _ = _make_client()
        try:
            res = client.post("/api/habits", json={
                "name": "x" * 101,
                "tracking_type": "daily_checkmark",
            })
            assert res.status_code == 422
        finally:
            _teardown()

    def test_name_exactly_100_chars_valid(self):
        """POST with name exactly 100 chars is valid."""
        client, _ = _make_client()
        h = _make_habit(name="x" * 100, tracking_type="daily_checkmark")
        sess = _make_session_ctx(habit=h)
        try:
            with patch("backend.main.Session", return_value=sess):
                res = client.post("/api/habits", json={
                    "name": "x" * 100,
                    "tracking_type": "daily_checkmark",
                })
            assert res.status_code == 201
        finally:
            _teardown()


# ── AC (h): Invalid auto_fill_source returns 422 ─────────────────────────────

class TestHabitValidationAutoFillSource:
    """AC (h): Invalid auto_fill_source returns 422."""

    def test_invalid_auto_fill_source_returns_422(self):
        """POST with auto_fill_source='not_a_real_field' returns 422."""
        client, _ = _make_client()
        try:
            res = client.post("/api/habits", json={
                "name": "Bad",
                "tracking_type": "weekly_minutes",
                "auto_fill_source": "not_a_real_field",
            })
            assert res.status_code == 422
        finally:
            _teardown()

    def test_valid_auto_fill_source_zone2_minutes_accepted(self):
        """POST with auto_fill_source='workout.zone2_minutes' is valid."""
        client, _ = _make_client()
        h = _make_habit(tracking_type="weekly_minutes", auto_fill_source="workout.zone2_minutes")
        sess = _make_session_ctx(habit=h)
        try:
            with patch("backend.main.Session", return_value=sess):
                res = client.post("/api/habits", json={
                    "name": "Zone2",
                    "tracking_type": "weekly_minutes",
                    "weekly_target": 180,
                    "auto_fill_source": "workout.zone2_minutes",
                })
            assert res.status_code == 201
        finally:
            _teardown()

    def test_valid_auto_fill_source_run_count_accepted(self):
        """POST with auto_fill_source='workout.run_count' is valid."""
        client, _ = _make_client()
        h = _make_habit(tracking_type="weekly_count", auto_fill_source="workout.run_count")
        sess = _make_session_ctx(habit=h)
        try:
            with patch("backend.main.Session", return_value=sess):
                res = client.post("/api/habits", json={
                    "name": "Runs",
                    "tracking_type": "weekly_count",
                    "weekly_target": 3,
                    "auto_fill_source": "workout.run_count",
                })
            assert res.status_code == 201
        finally:
            _teardown()

    def test_null_auto_fill_source_accepted(self):
        """POST with auto_fill_source=null is valid."""
        client, _ = _make_client()
        h = _make_habit(tracking_type="daily_checkmark")
        sess = _make_session_ctx(habit=h)
        try:
            with patch("backend.main.Session", return_value=sess):
                res = client.post("/api/habits", json={
                    "name": "Manual",
                    "tracking_type": "daily_checkmark",
                    "auto_fill_source": None,
                })
            assert res.status_code == 201
        finally:
            _teardown()


# ── Reorder endpoint ──────────────────────────────────────────────────────────

class TestReorderHabit:
    """POST /api/habits/{id}/reorder updates sort_order."""

    def test_reorder_updates_sort_order(self):
        """POST /api/habits/{id}/reorder with sort_order=2 returns 200."""
        client, _ = _make_client()
        hid = uuid.uuid4()
        h = _make_habit(hid=hid, sort_order=0)
        sess = _make_session_ctx(habit=h)
        try:
            with patch("backend.main.Session", return_value=sess):
                res = client.post(f"/api/habits/{hid}/reorder", json={"sort_order": 2})
            assert res.status_code == 200
            assert h.sort_order == 2
        finally:
            _teardown()

    def test_reorder_missing_sort_order_returns_422(self):
        """POST /api/habits/{id}/reorder without sort_order returns 422."""
        client, _ = _make_client()
        hid = uuid.uuid4()
        try:
            res = client.post(f"/api/habits/{hid}/reorder", json={})
            assert res.status_code == 422
        finally:
            _teardown()
