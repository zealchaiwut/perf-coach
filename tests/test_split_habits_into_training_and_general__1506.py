"""Tests for issue #1506: Split Habits into Training and General Sections.

Acceptance Criteria covered:
(a) Habit model gains a section field (training|general, default general)
(b) All habit CRUD endpoints accept and return section
(c) get_training_habit_adherence returns correct ratio for fixture data
(d) Zero checkins → 0.0
(e) All completed → 1.0
(f) A habit with no explicit section defaults to 'general' in API responses
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.main import app, resolve_user
from backend.services.coach_plan import get_training_habit_adherence

_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000001506")


# ── Helpers ───────────────────────────────────────────────────────────────────

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
    name="Test Habit",
    tracking_type="daily_checkmark",
    habit_type="binary",
    schedule_type="daily",
    section="general",
    is_archived=False,
    active=True,
    sort_order=0,
    display_order=0,
    weekly_target=None,
    target_value=None,
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
    h.section = section
    h.habit_type = habit_type
    h.schedule_type = schedule_type
    h.target_value = target_value
    h.active = active
    h.display_order = display_order
    h.tracking_type = tracking_type
    h.weekly_target = weekly_target
    h.unit = unit
    h.auto_fill_source = auto_fill_source
    h.icon = icon
    h.color = color
    h.sort_order = sort_order
    h.is_archived = is_archived
    h.description = description
    ts = MagicMock()
    ts.isoformat.return_value = "2026-07-17T00:00:00+00:00"
    h.created_at = ts
    h.updated_at = None
    return h


def _make_habit_ns(hid=None, section="general"):
    """SimpleNamespace habit for pure-function tests."""
    return SimpleNamespace(
        id=hid or uuid.uuid4(),
        section=section,
    )


def _make_log_ns(habit_id, log_date):
    """SimpleNamespace habit log for pure-function tests."""
    return SimpleNamespace(
        habit_id=habit_id,
        log_date=log_date,
    )


# ── (c) get_training_habit_adherence — fixture habits + checkins → ratio ─────

class TestGetTrainingHabitAdherence:
    _today = date(2026, 7, 17)

    def _habits(self):
        self.h1 = _make_habit_ns(hid=uuid.UUID("11111111-1111-1111-1111-111111111111"), section="training")
        self.h2 = _make_habit_ns(hid=uuid.UUID("22222222-2222-2222-2222-222222222222"), section="training")
        return [self.h1, self.h2]

    def test_correct_ratio_partial_completion(self):
        """(c) fixture habits + checkins → correct ratio"""
        habits = self._habits()
        today = self._today
        # 2 habits × 7 days = 14 expected; 7 completed = 0.5
        logs = [
            _make_log_ns(self.h1.id, today - timedelta(days=i)) for i in range(7)
        ]
        result = get_training_habit_adherence(habits, logs, 7, _today=today)
        assert abs(result - 7 / 14) < 1e-9

    def test_zero_checkins_returns_zero(self):
        """(d) zero checkins → 0.0"""
        habits = self._habits()
        result = get_training_habit_adherence(habits, [], 7, _today=self._today)
        assert result == 0.0

    def test_all_completed_returns_one(self):
        """(e) all completed → 1.0"""
        habits = self._habits()
        today = self._today
        # 2 habits × 7 days = 14; fill all 14
        logs = []
        for h in habits:
            for i in range(7):
                logs.append(_make_log_ns(h.id, today - timedelta(days=i)))
        result = get_training_habit_adherence(habits, logs, 7, _today=today)
        assert result == 1.0

    def test_empty_habits_returns_zero(self):
        """No training habits → 0.0"""
        result = get_training_habit_adherence([], [], 7, _today=self._today)
        assert result == 0.0

    def test_logs_outside_window_excluded(self):
        """Logs before the window are not counted."""
        habits = self._habits()
        today = self._today
        # Only 1 day window; add a log from 2 days ago (outside window)
        logs = [_make_log_ns(self.h1.id, today - timedelta(days=2))]
        result = get_training_habit_adherence(habits, logs, 1, _today=today)
        assert result == 0.0

    def test_ratio_capped_at_one(self):
        """Extra logs beyond expected days don't push ratio > 1.0."""
        habits = self._habits()
        today = self._today
        # Duplicate logs for same habit on same day shouldn't exceed 1.0
        logs = []
        for h in habits:
            for i in range(7):
                logs.append(_make_log_ns(h.id, today - timedelta(days=i)))
                logs.append(_make_log_ns(h.id, today - timedelta(days=i)))
        result = get_training_habit_adherence(habits, logs, 7, _today=today)
        assert result <= 1.0


# ── (b) + (f) GET /habits returns section field ───────────────────────────────

class TestGetHabitsReturnsSection:
    def setup_method(self):
        self.client, self.mock_user = _make_client()

    def teardown_method(self):
        _teardown()

    def test_get_habits_includes_section_field(self):
        """(b) GET /habits response includes section on each habit."""
        habit = _make_habit(name="Running", section="general")

        with patch("backend.main.Session") as MockSession:
            sess = MagicMock()
            sess.__enter__ = MagicMock(return_value=sess)
            sess.__exit__ = MagicMock(return_value=False)
            q = MagicMock()
            q.filter.return_value = q
            q.order_by.return_value = q
            q.all.return_value = [habit]
            sess.query.return_value = q
            MockSession.return_value = sess

            resp = self.client.get("/api/habits")

        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert "section" in data[0]
        assert data[0]["section"] == "general"

    def test_get_habits_training_section(self):
        """(b) GET /habits returns training section when set."""
        habit = _make_habit(name="Drills", section="training")

        with patch("backend.main.Session") as MockSession:
            sess = MagicMock()
            sess.__enter__ = MagicMock(return_value=sess)
            sess.__exit__ = MagicMock(return_value=False)
            q = MagicMock()
            q.filter.return_value = q
            q.order_by.return_value = q
            q.all.return_value = [habit]
            sess.query.return_value = q
            MockSession.return_value = sess

            resp = self.client.get("/api/habits")

        assert resp.status_code == 200
        data = resp.json()
        assert data[0]["section"] == "training"


# ── (b) POST /habits accepts and returns section ──────────────────────────────

class TestPostHabitSection:
    def setup_method(self):
        self.client, self.mock_user = _make_client()

    def teardown_method(self):
        _teardown()

    def test_post_habit_defaults_to_general(self):
        """(f) New habit without explicit section → general in response."""
        created = _make_habit(name="Journaling", section="general")

        with patch("backend.main._habits_repo") as mock_repo, \
             patch("backend.main.Session") as MockSession:
            sess = MagicMock()
            sess.__enter__ = MagicMock(return_value=sess)
            sess.__exit__ = MagicMock(return_value=False)
            q = MagicMock()
            q.filter.return_value = q
            q.first.return_value = None
            sess.query.return_value = q
            MockSession.return_value = sess
            mock_repo.create_habit.return_value = created
            mock_repo.HABIT_TYPE_VALUES = frozenset(("binary", "count", "duration"))
            mock_repo.SCHEDULE_TYPE_VALUES = frozenset(("daily", "weekly", "times_per_week"))

            resp = self.client.post(
                "/api/habits",
                json={"name": "Journaling", "habit_type": "binary"},
            )

        assert resp.status_code == 201
        data = resp.json()
        assert "section" in data
        assert data["section"] == "general"

    def test_post_habit_with_training_section(self):
        """(b) POST /habits with section=training → section stored and returned."""
        created = _make_habit(name="Drills", section="training")

        with patch("backend.main._habits_repo") as mock_repo, \
             patch("backend.main.Session") as MockSession:
            sess = MagicMock()
            sess.__enter__ = MagicMock(return_value=sess)
            sess.__exit__ = MagicMock(return_value=False)
            q = MagicMock()
            q.filter.return_value = q
            q.first.return_value = None
            sess.query.return_value = q
            MockSession.return_value = sess
            mock_repo.create_habit.return_value = created
            mock_repo.HABIT_TYPE_VALUES = frozenset(("binary", "count", "duration"))
            mock_repo.SCHEDULE_TYPE_VALUES = frozenset(("daily", "weekly", "times_per_week"))

            resp = self.client.post(
                "/api/habits",
                json={"name": "Drills", "habit_type": "binary", "section": "training"},
            )

        assert resp.status_code == 201
        data = resp.json()
        assert data["section"] == "training"

    def test_post_habit_invalid_section_rejected(self):
        """(b) section must be 'training' or 'general'; unknown values → 422."""
        with patch("backend.main._habits_repo") as mock_repo, \
             patch("backend.main.Session") as MockSession:
            sess = MagicMock()
            sess.__enter__ = MagicMock(return_value=sess)
            sess.__exit__ = MagicMock(return_value=False)
            MockSession.return_value = sess
            mock_repo.HABIT_TYPE_VALUES = frozenset(("binary", "count", "duration"))
            mock_repo.SCHEDULE_TYPE_VALUES = frozenset(("daily", "weekly", "times_per_week"))

            resp = self.client.post(
                "/api/habits",
                json={"name": "Bad", "habit_type": "binary", "section": "nutrition"},
            )

        assert resp.status_code == 422


# ── (b) PATCH /habits/:id accepts section ────────────────────────────────────

class TestPatchHabitSection:
    def setup_method(self):
        self.client, self.mock_user = _make_client()

    def teardown_method(self):
        _teardown()

    def test_patch_section_to_training(self):
        """(b) PATCH /habits/:id with section=training updates and returns it."""
        hid = uuid.uuid4()
        updated = _make_habit(hid=hid, name="Mobility", section="training")

        with patch("backend.main._habits_repo") as mock_repo, \
             patch("backend.main.Session") as MockSession:
            sess = MagicMock()
            sess.__enter__ = MagicMock(return_value=sess)
            sess.__exit__ = MagicMock(return_value=False)
            MockSession.return_value = sess
            mock_repo.update_habit.return_value = updated
            mock_repo.HABIT_TYPE_VALUES = frozenset(("binary", "count", "duration"))
            mock_repo.SCHEDULE_TYPE_VALUES = frozenset(("daily", "weekly", "times_per_week"))

            resp = self.client.patch(
                f"/api/habits/{hid}",
                json={"section": "training"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["section"] == "training"

    def test_patch_section_invalid_rejected(self):
        """(b) PATCH with invalid section value → 422."""
        hid = uuid.uuid4()

        with patch("backend.main._habits_repo") as mock_repo, \
             patch("backend.main.Session") as MockSession:
            sess = MagicMock()
            sess.__enter__ = MagicMock(return_value=sess)
            sess.__exit__ = MagicMock(return_value=False)
            MockSession.return_value = sess
            mock_repo.HABIT_TYPE_VALUES = frozenset(("binary", "count", "duration"))
            mock_repo.SCHEDULE_TYPE_VALUES = frozenset(("daily", "weekly", "times_per_week"))

            resp = self.client.patch(
                f"/api/habits/{hid}",
                json={"section": "unknown"},
            )

        assert resp.status_code == 422
