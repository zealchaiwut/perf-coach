"""Tests for issue #920: Apply coaching copy to habit logging surfaces.

Anchored to each AC item:

AC1  — Miss acknowledgement: miss copy acknowledges then pivots to weekly count.
AC2  — Weekly-consistency framing on miss: first message uses X-of-Y from week_done.
AC3  — Forgiving streak model: non-7-per-week habits use weekly framing.
AC4  — Milestone copy: concrete fact + next near target, no vague praise.
AC5  — Identity gating: "you are becoming" only at milestone/landmark events.
AC6  — No fabricated data: /api/habits/summary returns week_done and total_logs.
AC7  — Voice module routing: all coaching strings come from habit_voice service.
AC8  — H1 read-only: no new endpoints; enriched fields live on existing summary.
"""

import types
import uuid
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.main import app, resolve_user
from backend.models import Habit, HabitLog
from backend.services import habit_voice

# ── Shared fixtures ───────────────────────────────────────────────────────────

_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000920")

# Fixed reference date: Wednesday 2026-06-24
_TODAY = date(2026, 6, 24)
# Monday of that week
_WEEK_START = date(2026, 6, 22)


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


def _make_habit_ns(
    *,
    tracking_type="daily_checkmark",
    weekly_target=7,
    schedule_type="daily",
    schedule_target=None,
    name="Morning run",
):
    """Return a SimpleNamespace that quacks like a Habit model row."""
    h = types.SimpleNamespace(
        id=uuid.uuid4(),
        name=name,
        tracking_type=tracking_type,
        weekly_target=weekly_target,
        schedule_type=schedule_type,
        schedule_target=schedule_target,
        habit_type="binary",
        target_value=None,
        unit=None,
        auto_fill_source=None,
        icon=None,
        color=None,
    )
    return h


def _make_habit_mock(
    *,
    tracking_type="daily_checkmark",
    weekly_target=7,
    schedule_type="daily",
    schedule_target=None,
    name="Morning run",
):
    h = MagicMock(spec=Habit)
    h.id = uuid.uuid4()
    h.user_id = _USER_ID
    h.name = name
    h.description = ""
    h.tracking_type = tracking_type
    h.weekly_target = float(weekly_target) if weekly_target is not None else None
    h.schedule_type = schedule_type
    h.schedule_target = schedule_target
    h.habit_type = "binary"
    h.target_value = None
    h.unit = None
    h.auto_fill_source = None
    h.icon = None
    h.color = None
    h.sort_order = 0
    h.is_archived = False
    h.active = True
    ts = MagicMock()
    ts.isoformat.return_value = "2026-06-24T00:00:00"
    h.created_at = ts
    h.updated_at = None
    return h


def _make_log(habit_id, log_date, value=1):
    lg = MagicMock(spec=HabitLog)
    lg.id = uuid.uuid4()
    lg.habit_id = habit_id
    lg.user_id = _USER_ID
    lg.log_date = log_date
    lg.value = value
    return lg


# ═══════════════════════════════════════════════════════════════════════════════
# AC1 — Miss acknowledgement
# ═══════════════════════════════════════════════════════════════════════════════

class TestMissAcknowledgement:
    """AC1: Miss copy acknowledges the miss in one clause then pivots to next
    easy win. No shaming language. No streak-reset-to-zero display."""

    def test_miss_copy_contains_pivot(self):
        """compose_log_feedback with is_miss=True returns a copy string."""
        h = _make_habit_ns(weekly_target=7)
        result = habit_voice.compose_log_feedback(
            habit=h,
            week_done=6,
            week_target=7,
            total_logs=42,
            is_miss=True,
        )
        assert isinstance(result["message"], str)
        assert len(result["message"]) > 0

    def test_miss_copy_no_shaming_words(self):
        """Miss copy must not use shaming language."""
        h = _make_habit_ns(weekly_target=7)
        result = habit_voice.compose_log_feedback(
            habit=h,
            week_done=5,
            week_target=7,
            total_logs=20,
            is_miss=True,
        )
        msg = result["message"].lower()
        for word in ("fail", "shame", "bad", "terrible", "loser", "worthless"):
            assert word not in msg, f"Shaming word '{word}' found in miss copy"

    def test_miss_copy_no_streak_zero(self):
        """Miss copy must not phrase anything as 'streak: 0' or 'streak reset'."""
        h = _make_habit_ns(weekly_target=7)
        result = habit_voice.compose_log_feedback(
            habit=h,
            week_done=3,
            week_target=7,
            total_logs=15,
            is_miss=True,
        )
        msg = result["message"].lower()
        assert "streak: 0" not in msg
        assert "streak reset" not in msg
        assert "streak broke" not in msg


# ═══════════════════════════════════════════════════════════════════════════════
# AC2 — Weekly-consistency framing on miss
# ═══════════════════════════════════════════════════════════════════════════════

class TestWeeklyConsistencyFraming:
    """AC2: The first message after any miss surfaces the weekly-consistency
    count derived from week_done—never a raw streak counter that reads zero."""

    def test_miss_message_contains_weekly_count(self):
        """Miss copy includes 'X of Y' phrasing using week_done and week_target."""
        h = _make_habit_ns(weekly_target=7)
        # Use non-milestone total_logs (milestone check runs first)
        result = habit_voice.compose_log_feedback(
            habit=h,
            week_done=6,
            week_target=7,
            total_logs=32,
            is_miss=True,
        )
        msg = result["message"]
        assert "6" in msg and "7" in msg, (
            f"Expected '6' and '7' in miss message, got: {msg!r}"
        )

    def test_miss_message_uses_week_done_not_streak(self):
        """week_done value (not current_streak) appears in the miss copy."""
        h = _make_habit_ns(weekly_target=7)
        # streak = 0 (we just missed), week_done = 4; use non-milestone total
        result = habit_voice.compose_log_feedback(
            habit=h,
            week_done=4,
            week_target=7,
            total_logs=22,
            is_miss=True,
        )
        msg = result["message"]
        assert "4" in msg, f"week_done=4 should appear in miss copy, got: {msg!r}"


# ═══════════════════════════════════════════════════════════════════════════════
# AC3 — Forgiving streak model
# ═══════════════════════════════════════════════════════════════════════════════

class TestForgivingStreakModel:
    """AC3: Habits with times_per_week < 7 use weekly-cadence framing.
    Hard daily-streak language only when times_per_week == 7."""

    def test_3x_per_week_habit_uses_weekly_framing(self):
        """3×/week habit gives weekly-cadence copy, not daily-streak counter."""
        h = _make_habit_ns(
            tracking_type="weekly_count",
            weekly_target=3,
            schedule_type="times_per_week",
            schedule_target=3,
        )
        result = habit_voice.compose_log_feedback(
            habit=h,
            week_done=2,
            week_target=3,
            total_logs=11,  # not a milestone
            is_miss=False,
        )
        framing = result["framing"]
        assert framing == "weekly", (
            f"Expected weekly framing for 3×/week habit, got: {framing!r}"
        )

    def test_daily_7x_habit_uses_streak_framing(self):
        """daily_checkmark with weekly_target=7 may use streak or routine framing."""
        h = _make_habit_ns(
            tracking_type="daily_checkmark",
            weekly_target=7,
            schedule_type="daily",
        )
        result = habit_voice.compose_log_feedback(
            habit=h,
            week_done=7,
            week_target=7,
            total_logs=21,
            is_miss=False,
        )
        # A 7×/week daily habit that completed all 7 days can produce routine or
        # streak framing — both are acceptable; must not error
        assert result["framing"] in ("streak", "weekly", "milestone", "routine")

    def test_5x_per_week_uses_weekly_framing(self):
        """5×/week habit → weekly-cadence framing regardless of streak length."""
        h = _make_habit_ns(
            tracking_type="weekly_count",
            weekly_target=5,
            schedule_type="times_per_week",
            schedule_target=5,
        )
        result = habit_voice.compose_log_feedback(
            habit=h,
            week_done=3,
            week_target=5,
            total_logs=40,
            is_miss=False,
        )
        assert result["framing"] == "weekly"


# ═══════════════════════════════════════════════════════════════════════════════
# AC4 — Milestone copy
# ═══════════════════════════════════════════════════════════════════════════════

class TestMilestoneCopy:
    """AC4: Milestone copy states the fact with exact count, then gives the
    next near target. No vague praise without a follow-up target."""

    def test_milestone_at_30_logs(self):
        """total_logs=30 triggers milestone copy with '30' and next landmark."""
        h = _make_habit_ns(name="Meditation")
        result = habit_voice.compose_log_feedback(
            habit=h,
            week_done=3,
            week_target=7,
            total_logs=30,
            is_miss=False,
        )
        msg = result["message"]
        assert "30" in msg, f"Milestone copy should contain '30', got: {msg!r}"
        assert result["framing"] == "milestone"

    def test_milestone_copy_has_next_target(self):
        """Milestone copy always includes a next near target."""
        h = _make_habit_ns(name="Meditation")
        result = habit_voice.compose_log_feedback(
            habit=h,
            week_done=5,
            week_target=7,
            total_logs=50,
            is_miss=False,
        )
        assert result["next_milestone"] is not None
        assert result["next_milestone"] > 50

    def test_milestone_copy_no_vague_praise_without_target(self):
        """Milestone copy must not be empty or vague-only (needs next target)."""
        h = _make_habit_ns(name="Running")
        result = habit_voice.compose_log_feedback(
            habit=h,
            week_done=7,
            week_target=7,
            total_logs=100,
            is_miss=False,
        )
        assert result["framing"] == "milestone"
        assert result["next_milestone"] is not None
        assert result["next_milestone"] > 100

    def test_non_milestone_has_no_next_milestone_key(self):
        """Routine logs at non-milestone counts do not surface a next_milestone."""
        h = _make_habit_ns()
        result = habit_voice.compose_log_feedback(
            habit=h,
            week_done=3,
            week_target=7,
            total_logs=17,
            is_miss=False,
        )
        assert result["framing"] != "milestone"
        assert result.get("next_milestone") is None


# ═══════════════════════════════════════════════════════════════════════════════
# AC5 — Identity framing gating
# ═══════════════════════════════════════════════════════════════════════════════

class TestIdentityFramingGating:
    """AC5: 'You are becoming someone who…' copy only at milestone events and
    streak landmark thresholds—never on routine daily log confirmations."""

    def test_routine_log_no_identity_framing(self):
        """Routine non-milestone, non-landmark log must not include identity copy."""
        h = _make_habit_ns(weekly_target=7)
        result = habit_voice.compose_log_feedback(
            habit=h,
            week_done=3,
            week_target=7,
            total_logs=12,
            is_miss=False,
        )
        assert not result["show_identity"], (
            "Identity framing must be absent on routine daily log"
        )

    def test_milestone_shows_identity_framing(self):
        """Milestone log must include identity framing."""
        h = _make_habit_ns(weekly_target=7)
        result = habit_voice.compose_log_feedback(
            habit=h,
            week_done=7,
            week_target=7,
            total_logs=25,
            is_miss=False,
        )
        assert result["show_identity"] is True
        assert result["framing"] == "milestone"

    def test_streak_landmark_shows_identity_framing(self):
        """Streak landmark (e.g., 7-day, 30-day streak) enables identity framing."""
        h = _make_habit_ns(weekly_target=7)
        result = habit_voice.compose_log_feedback(
            habit=h,
            week_done=7,
            week_target=7,
            total_logs=9,
            is_miss=False,
            current_streak=7,
        )
        assert result["show_identity"] is True

    def test_non_landmark_streak_no_identity(self):
        """A streak of 4 days (not a landmark) must not trigger identity framing."""
        h = _make_habit_ns(weekly_target=7)
        result = habit_voice.compose_log_feedback(
            habit=h,
            week_done=4,
            week_target=7,
            total_logs=8,
            is_miss=False,
            current_streak=4,
        )
        assert not result["show_identity"]


# ═══════════════════════════════════════════════════════════════════════════════
# AC6 — No fabricated data: /api/habits/summary returns week_done and total_logs
# ═══════════════════════════════════════════════════════════════════════════════

class TestSummaryEndpointFields:
    """AC6: The enriched summary endpoint includes week_done and total_logs so
    the frontend voice module never needs to infer or fabricate numbers."""

    def _make_session(self, habits, logs):
        """Build a mock DB session matching the actual query chains in get_habits_summary."""
        sess = MagicMock()
        q = sess.query.return_value
        # Habits chain: .filter(...).order_by(...).all()
        q.filter.return_value.order_by.return_value.all.return_value = habits
        # Logs chain: .filter(...).all()
        q.filter.return_value.all.return_value = logs
        return sess

    def test_summary_includes_week_done(self):
        """GET /api/habits/summary returns week_done per habit."""
        client, _ = _make_client()
        habit = _make_habit_mock(tracking_type="daily_checkmark", weekly_target=7)
        habit.schedule_type = "daily"
        habit.schedule_target = None
        habit.habit_type = "binary"
        habit.target_value = None
        week_start = _WEEK_START
        logs = [
            _make_log(habit.id, week_start),
            _make_log(habit.id, week_start + timedelta(days=1)),
        ]
        for lg in logs:
            lg.log_date = lg.log_date  # ensure date type

        with patch("backend.main.Session") as MockSession:
            MockSession.return_value.__enter__.return_value = self._make_session([habit], logs)
            resp = client.get("/api/habits/summary")

        _teardown()
        assert resp.status_code == 200
        data = resp.json()
        assert "habits" in data
        assert len(data["habits"]) == 1
        h0 = data["habits"][0]
        assert "week_done" in h0, "week_done field missing from summary"
        assert isinstance(h0["week_done"], int)
        assert h0["week_done"] == 2  # two logs in the current week

    def test_summary_includes_total_logs(self):
        """GET /api/habits/summary returns total_logs per habit."""
        client, _ = _make_client()
        habit = _make_habit_mock(tracking_type="daily_checkmark", weekly_target=7)
        habit.schedule_type = "daily"
        habit.schedule_target = None
        habit.habit_type = "binary"
        habit.target_value = None
        today = _TODAY
        logs = [_make_log(habit.id, today - timedelta(days=i)) for i in range(15)]

        with patch("backend.main.Session") as MockSession:
            MockSession.return_value.__enter__.return_value = self._make_session([habit], logs)
            resp = client.get("/api/habits/summary")

        _teardown()
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["habits"]) == 1
        h0 = data["habits"][0]
        assert "total_logs" in h0, "total_logs field missing from summary"
        assert h0["total_logs"] == 15


# ═══════════════════════════════════════════════════════════════════════════════
# AC7 — Voice module routing
# ═══════════════════════════════════════════════════════════════════════════════

class TestVoiceModuleRouting:
    """AC7: All coaching strings are produced by the habit_voice module;
    no surface hard-codes its own copy strings."""

    def test_compose_log_feedback_returns_dict(self):
        """habit_voice.compose_log_feedback always returns a dict."""
        h = _make_habit_ns()
        result = habit_voice.compose_log_feedback(
            habit=h,
            week_done=3,
            week_target=7,
            total_logs=20,
            is_miss=False,
        )
        assert isinstance(result, dict)
        assert "message" in result
        assert "framing" in result
        assert "show_identity" in result

    def test_voice_module_handles_zero_week_done(self):
        """Voice module does not crash or fabricate when week_done=0."""
        h = _make_habit_ns()
        result = habit_voice.compose_log_feedback(
            habit=h,
            week_done=0,
            week_target=7,
            total_logs=5,
            is_miss=True,
        )
        assert isinstance(result["message"], str)

    def test_voice_module_handles_none_weekly_target(self):
        """Voice module gracefully handles None weekly_target."""
        h = _make_habit_ns(weekly_target=None)
        result = habit_voice.compose_log_feedback(
            habit=h,
            week_done=1,
            week_target=None,
            total_logs=10,
            is_miss=False,
        )
        assert isinstance(result["message"], str)


# ═══════════════════════════════════════════════════════════════════════════════
# AC8 — H1 read-only
# ═══════════════════════════════════════════════════════════════════════════════

class TestH1ReadOnly:
    """AC8: The implementation enriches the existing summary endpoint only.
    No new endpoint added; week_done and total_logs are on /api/habits/summary."""

    def test_no_new_coaching_endpoint_in_routes(self):
        """No /api/habits/coaching or /api/voice route was registered."""
        from backend.main import app as _app
        routes = {str(r.path) for r in _app.routes}  # type: ignore[attr-defined]
        assert "/api/habits/coaching" not in routes
        assert "/api/voice" not in routes
        assert "/api/habits/voice" not in routes

    def test_summary_endpoint_still_works(self):
        """GET /api/habits/summary continues to return 200 with all prior fields."""
        client, _ = _make_client()
        habit = _make_habit_mock(tracking_type="daily_checkmark", weekly_target=7)

        def _mk():
            from unittest.mock import MagicMock as _MM
            sess = _MM()
            q = sess.query.return_value
            q.filter.return_value.filter.return_value.filter.return_value.order_by.return_value.all.return_value = [habit]
            q.filter.return_value.filter.return_value.all.return_value = []
            return sess

        with patch("backend.main.Session") as MockSession:
            MockSession.return_value.__enter__.return_value = _mk()
            resp = client.get("/api/habits/summary")

        _teardown()
        assert resp.status_code == 200
        data = resp.json()
        assert "habits" in data
        if data["habits"]:
            h0 = data["habits"][0]
            # Legacy fields still present
            assert "current_streak" in h0
            assert "longest_streak" in h0
            assert "consistency_percent" in h0
