"""Tests for issue #924: Add three-focus-habit model to Habits.

Anchored to each AC item:

AC1  — Schema: idempotent migration adds is_focus and focus_since columns.
AC2  — Focus cap: max 3 per user; API returns 422 with voice-module copy on 4th.
AC3  — Focus vs. also-tracking: non-focus habits receive no streak/coaching/prominence.
AC4  — Focus habits surface correctly (is_focus=True returned in API response).
AC5  — Swap cooldown: cannot remove focus < FOCUS_COOLDOWN_DAYS; 422 with days remaining.
AC6  — Swap requires confirmation: without confirm=true returns prompt; with it commits.
AC7  — Subtraction suggestion trigger: fires when consistently missing focus habits.
AC8  — Subtraction suggestion guard: suppressed when all focus habits are being hit.
AC9  — No hardcoded literals: all thresholds are named constants in habit_focus.
AC10 — Copy through voice module: cap/cooldown/confirmation/suggestion from habit_voice.
AC11 — Thin caller pattern: service functions are pure (no DB).
AC12 — Migration is additive and idempotent.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from backend.main import app, resolve_user
from backend.models import Habit, HabitLog
from backend.services import habit_focus
from backend.services import habit_voice

# ── Constants ─────────────────────────────────────────────────────────────────

_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000924")
_TODAY = date(2026, 6, 25)


def _make_user():
    u = MagicMock()
    u.id = _USER_ID
    return u


def _make_client():
    mock_user = _make_user()

    async def _fake_resolve():
        return mock_user

    app.dependency_overrides[resolve_user] = _fake_resolve
    return TestClient(app, raise_server_exceptions=False), mock_user


def _make_habit_ns(**kwargs):
    h = MagicMock(spec=Habit)
    h.id = kwargs.get("id", uuid.uuid4())
    h.user_id = _USER_ID
    h.name = kwargs.get("name", "Test Habit")
    h.is_focus = kwargs.get("is_focus", False)
    h.focus_since = kwargs.get("focus_since", None)
    h.active = kwargs.get("active", True)
    h.tracking_type = kwargs.get("tracking_type", "daily_checkmark")
    h.habit_type = kwargs.get("habit_type", "binary")
    h.schedule_type = kwargs.get("schedule_type", "daily")
    h.target_value = None
    h.unit = None
    h.weekly_target = None
    h.sort_order = 0
    h.display_order = 0
    h.is_archived = False
    h.description = None
    h.icon = None
    h.color = None
    h.auto_fill_source = None
    h.schedule_target = None
    h.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    h.updated_at = None
    h.minimum_version = None
    h.anchor_event = None
    return h


# ── AC9 — Named constants ─────────────────────────────────────────────────────

class TestNamedConstants:
    def test_max_focus_count_constant_exists(self):
        """MAX_FOCUS_COUNT is exported from habit_focus."""
        assert hasattr(habit_focus, "MAX_FOCUS_COUNT")
        assert habit_focus.MAX_FOCUS_COUNT == 3

    def test_focus_cooldown_days_constant_exists(self):
        """FOCUS_COOLDOWN_DAYS is exported from habit_focus."""
        assert hasattr(habit_focus, "FOCUS_COOLDOWN_DAYS")
        assert habit_focus.FOCUS_COOLDOWN_DAYS > 0

    def test_subtraction_miss_threshold_constant_exists(self):
        """SUBTRACTION_MISS_THRESHOLD_DAYS is exported from habit_focus."""
        assert hasattr(habit_focus, "SUBTRACTION_MISS_THRESHOLD_DAYS")
        assert habit_focus.SUBTRACTION_MISS_THRESHOLD_DAYS > 0

    def test_subtraction_repeat_cooldown_constant_exists(self):
        """SUBTRACTION_REPEAT_COOLDOWN_DAYS is exported from habit_focus."""
        assert hasattr(habit_focus, "SUBTRACTION_REPEAT_COOLDOWN_DAYS")
        assert habit_focus.SUBTRACTION_REPEAT_COOLDOWN_DAYS > 0


# ── AC10 — Voice copy ─────────────────────────────────────────────────────────

class TestVoiceCopy:
    def test_focus_cap_error_message_exists(self):
        """focus_cap_error_message is exported from habit_voice."""
        assert callable(getattr(habit_voice, "focus_cap_error_message", None))

    def test_focus_cap_error_message_no_exclamation(self):
        """Cap error message contains no exclamation marks."""
        msg = habit_voice.focus_cap_error_message()
        assert "!" not in msg

    def test_focus_cap_error_message_mentions_count(self):
        """Cap error message references the limit (3)."""
        msg = habit_voice.focus_cap_error_message()
        assert "3" in msg

    def test_focus_cooldown_message_exists(self):
        """focus_cooldown_message is exported from habit_voice."""
        assert callable(getattr(habit_voice, "focus_cooldown_message", None))

    def test_focus_cooldown_message_includes_days_remaining(self):
        """Cooldown message includes the number of days remaining."""
        msg = habit_voice.focus_cooldown_message(3)
        assert "3" in msg

    def test_focus_confirmation_prompt_exists(self):
        """focus_confirmation_prompt is exported from habit_voice."""
        assert callable(getattr(habit_voice, "focus_confirmation_prompt", None))

    def test_focus_confirmation_prompt_mentions_habit_name(self):
        """Confirmation prompt includes the habit name."""
        msg = habit_voice.focus_confirmation_prompt("Morning run")
        assert "Morning run" in msg

    def test_focus_subtraction_suggestion_exists(self):
        """focus_subtraction_suggestion is exported from habit_voice."""
        assert callable(getattr(habit_voice, "focus_subtraction_suggestion", None))

    def test_focus_subtraction_suggestion_supportive(self):
        """Subtraction suggestion is supportive (no penalty/shame language)."""
        msg = habit_voice.focus_subtraction_suggestion()
        assert msg
        assert "!" not in msg
        for bad in ("failed", "failure", "penalty", "shame", "punish"):
            assert bad not in msg.lower()


# ── AC11 — Thin caller / service purity ──────────────────────────────────────

class TestFocusCapService:
    def test_check_focus_cap_at_limit(self):
        """check_focus_cap returns True when count equals MAX_FOCUS_COUNT."""
        assert habit_focus.check_focus_cap(habit_focus.MAX_FOCUS_COUNT) is True

    def test_check_focus_cap_below_limit(self):
        """check_focus_cap returns False when count is below MAX_FOCUS_COUNT."""
        assert habit_focus.check_focus_cap(0) is False
        assert habit_focus.check_focus_cap(habit_focus.MAX_FOCUS_COUNT - 1) is False

    def test_check_focus_cap_above_limit(self):
        """check_focus_cap returns True when count exceeds MAX_FOCUS_COUNT."""
        assert habit_focus.check_focus_cap(habit_focus.MAX_FOCUS_COUNT + 1) is True


# ── AC2 — Focus cap via API ───────────────────────────────────────────────────

class TestFocusCapAPI:
    def test_set_focus_returns_422_when_cap_reached(self):
        """POST /api/habits/{id}/focus returns 422 when 3 habits already focus."""
        client, _ = _make_client()
        hid = uuid.uuid4()

        focus_habit = _make_habit_ns(id=hid, is_focus=False)

        with (
            patch("backend.main._habits_repo.get_habit", return_value=focus_habit),
            patch("backend.main.Session") as mock_session_cls,
        ):
            mock_session = MagicMock()
            mock_session_cls.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)
            mock_query = MagicMock()
            mock_session.query.return_value = mock_query
            mock_query.filter.return_value = mock_query
            mock_query.count.return_value = 3

            resp = client.post(f"/api/habits/{hid}/focus")

        assert resp.status_code == 422
        detail = resp.json().get("detail", "")
        assert "3" in detail

    def test_set_focus_uses_voice_copy_for_cap_error(self):
        """Cap error message matches habit_voice.focus_cap_error_message()."""
        client, _ = _make_client()
        hid = uuid.uuid4()
        focus_habit = _make_habit_ns(id=hid, is_focus=False)

        with (
            patch("backend.main._habits_repo.get_habit", return_value=focus_habit),
            patch("backend.main.Session") as mock_session_cls,
        ):
            mock_session = MagicMock()
            mock_session_cls.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)
            mock_query = MagicMock()
            mock_session.query.return_value = mock_query
            mock_query.filter.return_value = mock_query
            mock_query.count.return_value = 3

            resp = client.post(f"/api/habits/{hid}/focus")

        detail = resp.json().get("detail", "")
        assert detail == habit_voice.focus_cap_error_message()

    def test_set_focus_returns_200_below_cap(self):
        """POST /api/habits/{id}/focus returns 200 when under the cap."""
        client, _ = _make_client()
        hid = uuid.uuid4()
        focus_habit = _make_habit_ns(id=hid, is_focus=False)
        focus_habit.focus_since = None

        with (
            patch("backend.main._habits_repo.get_habit", return_value=focus_habit),
            patch("backend.main.Session") as mock_session_cls,
        ):
            mock_session = MagicMock()
            mock_session_cls.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)
            mock_query = MagicMock()
            mock_session.query.return_value = mock_query
            mock_query.filter.return_value = mock_query
            mock_query.count.return_value = 1

            resp = client.post(f"/api/habits/{hid}/focus")

        assert resp.status_code == 200


# ── AC5 — Swap cooldown (service layer) ──────────────────────────────────────

class TestSwapCooldownService:
    def test_is_cooldown_active_when_just_set(self):
        """Cooldown is active on the same day as focus_since."""
        fs = _TODAY
        assert habit_focus.is_cooldown_active(fs, _TODAY) is True

    def test_is_cooldown_active_one_day_before_expiry(self):
        """Cooldown is active one day before FOCUS_COOLDOWN_DAYS elapses."""
        fs = _TODAY - timedelta(days=habit_focus.FOCUS_COOLDOWN_DAYS - 1)
        assert habit_focus.is_cooldown_active(fs, _TODAY) is True

    def test_is_cooldown_inactive_at_expiry(self):
        """Cooldown is inactive exactly at FOCUS_COOLDOWN_DAYS elapsed."""
        fs = _TODAY - timedelta(days=habit_focus.FOCUS_COOLDOWN_DAYS)
        assert habit_focus.is_cooldown_active(fs, _TODAY) is False

    def test_days_until_swap_allowed_correct(self):
        """days_until_swap_allowed returns correct count."""
        fs = _TODAY - timedelta(days=3)
        expected = habit_focus.FOCUS_COOLDOWN_DAYS - 3
        assert habit_focus.days_until_swap_allowed(fs, _TODAY) == expected

    def test_days_until_swap_allowed_zero_after_expiry(self):
        """days_until_swap_allowed returns 0 when cooldown has passed."""
        fs = _TODAY - timedelta(days=habit_focus.FOCUS_COOLDOWN_DAYS + 5)
        assert habit_focus.days_until_swap_allowed(fs, _TODAY) == 0


# ── AC5 — Swap cooldown via API ───────────────────────────────────────────────

class TestSwapCooldownAPI:
    def test_delete_focus_returns_422_in_cooldown(self):
        """DELETE /api/habits/{id}/focus returns 422 when cooldown is active."""
        client, _ = _make_client()
        hid = uuid.uuid4()
        focus_habit = _make_habit_ns(
            id=hid,
            is_focus=True,
            focus_since=datetime(_TODAY.year, _TODAY.month, _TODAY.day, tzinfo=timezone.utc),
        )

        with patch("backend.main._habits_repo.get_habit", return_value=focus_habit), \
             patch("backend.main.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session_cls.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)

            resp = client.delete(f"/api/habits/{hid}/focus?confirm=true")

        assert resp.status_code == 422

    def test_delete_focus_cooldown_message_from_voice(self):
        """422 detail matches habit_voice.focus_cooldown_message(days)."""
        client, _ = _make_client()
        hid = uuid.uuid4()
        focus_habit = _make_habit_ns(
            id=hid,
            is_focus=True,
            focus_since=datetime(_TODAY.year, _TODAY.month, _TODAY.day, tzinfo=timezone.utc),
        )

        with patch("backend.main._habits_repo.get_habit", return_value=focus_habit), \
             patch("backend.main.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session_cls.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)

            resp = client.delete(f"/api/habits/{hid}/focus?confirm=true")

        detail = resp.json().get("detail", "")
        days_left = habit_focus.days_until_swap_allowed(
            focus_habit.focus_since, _TODAY
        )
        expected = habit_voice.focus_cooldown_message(days_left)
        assert detail == expected

    def test_delete_focus_succeeds_after_cooldown(self):
        """DELETE /api/habits/{id}/focus?confirm=true succeeds when cooldown passed."""
        client, _ = _make_client()
        hid = uuid.uuid4()
        old_date = _TODAY - timedelta(days=habit_focus.FOCUS_COOLDOWN_DAYS)
        focus_habit = _make_habit_ns(
            id=hid,
            is_focus=True,
            focus_since=datetime(old_date.year, old_date.month, old_date.day, tzinfo=timezone.utc),
        )

        with patch("backend.main._habits_repo.get_habit", return_value=focus_habit), \
             patch("backend.main.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session_cls.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)
            mock_session.commit = MagicMock()
            mock_session.refresh = MagicMock()

            resp = client.delete(f"/api/habits/{hid}/focus?confirm=true")

        assert resp.status_code == 200


# ── AC6 — Swap confirmation ───────────────────────────────────────────────────

class TestSwapConfirmation:
    def test_delete_without_confirm_returns_prompt(self):
        """DELETE /api/habits/{id}/focus without confirm=true returns confirmation prompt."""
        client, _ = _make_client()
        hid = uuid.uuid4()
        old_date = _TODAY - timedelta(days=habit_focus.FOCUS_COOLDOWN_DAYS)
        focus_habit = _make_habit_ns(
            id=hid,
            name="Evening walk",
            is_focus=True,
            focus_since=datetime(old_date.year, old_date.month, old_date.day, tzinfo=timezone.utc),
        )

        with patch("backend.main._habits_repo.get_habit", return_value=focus_habit), \
             patch("backend.main.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session_cls.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)

            resp = client.delete(f"/api/habits/{hid}/focus")

        assert resp.status_code == 200
        body = resp.json()
        assert body.get("requires_confirmation") is True
        assert "Evening walk" in body.get("message", "")

    def test_confirmation_prompt_from_voice_module(self):
        """Confirmation prompt message matches habit_voice.focus_confirmation_prompt."""
        client, _ = _make_client()
        hid = uuid.uuid4()
        old_date = _TODAY - timedelta(days=habit_focus.FOCUS_COOLDOWN_DAYS)
        focus_habit = _make_habit_ns(
            id=hid,
            name="Evening walk",
            is_focus=True,
            focus_since=datetime(old_date.year, old_date.month, old_date.day, tzinfo=timezone.utc),
        )

        with patch("backend.main._habits_repo.get_habit", return_value=focus_habit), \
             patch("backend.main.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session_cls.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)

            resp = client.delete(f"/api/habits/{hid}/focus")

        message = resp.json().get("message", "")
        expected = habit_voice.focus_confirmation_prompt("Evening walk")
        assert message == expected


# ── AC3 — filter_focus_habits (non-focus excluded) ───────────────────────────

class TestFocusFilter:
    def test_filter_focus_habits_returns_only_focus(self):
        """filter_focus_habits excludes habits where is_focus is not True."""
        h1 = _make_habit_ns(is_focus=True)
        h2 = _make_habit_ns(is_focus=False)
        h3 = _make_habit_ns(is_focus=None)
        result = habit_focus.filter_focus_habits([h1, h2, h3])
        assert result == [h1]

    def test_filter_focus_habits_empty_list(self):
        """filter_focus_habits returns empty list when no habits are focus."""
        h1 = _make_habit_ns(is_focus=False)
        result = habit_focus.filter_focus_habits([h1])
        assert result == []

    def test_filter_focus_habits_all_focus(self):
        """filter_focus_habits returns all habits when all are focus."""
        habits = [_make_habit_ns(is_focus=True) for _ in range(3)]
        result = habit_focus.filter_focus_habits(habits)
        assert len(result) == 3


# ── AC4 — Focus fields in API response ───────────────────────────────────────

class TestFocusFieldsInAPIResponse:
    def _mock_session_for_habits(self, habits):
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_q = MagicMock()
        mock_session.query.return_value = mock_q
        mock_q.filter.return_value = mock_q
        mock_q.order_by.return_value = mock_q
        mock_q.all.return_value = habits
        return mock_session

    def test_get_habits_includes_is_focus_field(self):
        """GET /api/habits includes is_focus in each habit."""
        client, _ = _make_client()
        habits = [_make_habit_ns(is_focus=True), _make_habit_ns(is_focus=False)]
        mock_session = self._mock_session_for_habits(habits)

        with patch("backend.main.Session", return_value=mock_session):
            resp = client.get("/api/habits")

        assert resp.status_code == 200, resp.text
        for h in resp.json():
            assert "is_focus" in h

    def test_get_habits_includes_focus_since_field(self):
        """GET /api/habits includes focus_since in each habit."""
        client, _ = _make_client()
        habits = [_make_habit_ns(is_focus=True, focus_since=datetime(2026, 6, 1, tzinfo=timezone.utc))]
        mock_session = self._mock_session_for_habits(habits)

        with patch("backend.main.Session", return_value=mock_session):
            resp = client.get("/api/habits")

        assert resp.status_code == 200, resp.text
        for h in resp.json():
            assert "focus_since" in h


# ── AC7/AC8 — Subtraction suggestion ─────────────────────────────────────────

class TestSubtractionSuggestion:
    def test_should_suggest_when_missing_all_focus_habits(self):
        """should_suggest_subtraction returns True when a focus habit has no logs in window."""
        h1 = _make_habit_ns(is_focus=True)
        logs_by_habit_id: dict = {h1.id: []}
        result = habit_focus.should_suggest_subtraction([h1], logs_by_habit_id, _TODAY)
        assert result is True

    def test_no_suggestion_when_all_focus_habits_logged(self):
        """should_suggest_subtraction returns False when all focus habits have logs in window."""
        h1 = _make_habit_ns(is_focus=True)
        window = [
            _TODAY - timedelta(days=i)
            for i in range(habit_focus.SUBTRACTION_MISS_THRESHOLD_DAYS)
        ]
        logs_by_habit_id = {h1.id: window}
        result = habit_focus.should_suggest_subtraction([h1], logs_by_habit_id, _TODAY)
        assert result is False

    def test_no_suggestion_when_no_focus_habits(self):
        """should_suggest_subtraction returns False when focus habit list is empty."""
        result = habit_focus.should_suggest_subtraction([], {}, _TODAY)
        assert result is False

    def test_suggestion_api_returns_suggest_false_when_all_hit(self):
        """GET /api/habits/focus-suggestion returns suggest=False when all focus habits logged."""
        client, _ = _make_client()
        hid = uuid.uuid4()
        h1 = _make_habit_ns(id=hid, is_focus=True)
        window = [
            _TODAY - timedelta(days=i)
            for i in range(habit_focus.SUBTRACTION_MISS_THRESHOLD_DAYS)
        ]

        with patch("backend.main.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session_cls.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)
            mock_q = MagicMock()
            mock_session.query.return_value = mock_q
            mock_q.filter.return_value = mock_q

            mock_log = MagicMock(spec=HabitLog)
            mock_log.habit_id = hid
            mock_log.log_date = _TODAY

            mock_q.all.side_effect = [[h1], [mock_log] * len(window)]

            with patch("backend.main._habit_focus.should_suggest_subtraction", return_value=False):
                resp = client.get("/api/habits/focus-suggestion")

        assert resp.status_code == 200
        assert resp.json()["suggest"] is False

    def test_suggestion_message_from_voice_module(self):
        """When suggestion fires, message matches habit_voice.focus_subtraction_suggestion()."""
        client, _ = _make_client()
        hid = uuid.uuid4()
        h1 = _make_habit_ns(id=hid, is_focus=True)

        with patch("backend.main.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session_cls.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)
            mock_q = MagicMock()
            mock_session.query.return_value = mock_q
            mock_q.filter.return_value = mock_q
            mock_q.all.side_effect = [[h1], []]

            with patch("backend.main._habit_focus.should_suggest_subtraction", return_value=True):
                resp = client.get("/api/habits/focus-suggestion")

        assert resp.status_code == 200
        body = resp.json()
        assert body["suggest"] is True
        assert body["message"] == habit_voice.focus_subtraction_suggestion()


# ── AC1/AC12 — Migration idempotency ─────────────────────────────────────────

class TestMigrationIdempotency:
    def test_migration_file_exists(self):
        """Migration file exists in alembic/versions."""
        import os
        versions_dir = "alembic/versions"
        migration_files = os.listdir(versions_dir)
        focus_migrations = [f for f in migration_files if "focus" in f]
        assert focus_migrations, "No migration file containing 'focus' found"

    def test_migration_uses_column_exists_guard(self):
        """Migration file imports column_exists for idempotency."""
        import os
        versions_dir = "alembic/versions"
        # Look for the migration that adds focus columns (not the merge node)
        migration_files = [
            f for f in os.listdir(versions_dir)
            if "focus_columns" in f and f.endswith(".py")
        ]
        assert migration_files, "No focus_columns migration file found"
        content = open(os.path.join(versions_dir, migration_files[0])).read()
        assert "column_exists" in content
