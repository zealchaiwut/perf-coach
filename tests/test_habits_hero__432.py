"""Tests for issue #432: Habits page hero — week wheel + stats cards.

Backend-side data-contract tests for the shapes that the new Card A (week
wheel) and Card B (3-up stats) depend on when rendering from GET /api/habits/week.

AC items covered:
  (a) wheel always has exactly 7 entries
  (b) streaks.best is null when no daily_checkmark habits exist
  (c) streaks.best carries habit_name and length for the best-streak tile
  (d) last_week is null when the prior week has no log data
  (e) week_totals carries all fields Card A/B need: elapsed_days, pct_elapsed,
      pct_full_week, daily_habits_count, daily_done
  (f) day_scores entry for today has done/of for the Today tile in Card B
  (g) past-week response: is_current_week=false and no wheel entry has state "today"
  (h) past-week: week_totals.pct_full_week reflects full-week completion
"""
import uuid
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from backend.main import app, resolve_user
from backend.models import Habit, HabitLog, Workout

_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000432")
_WEEK_MON = date(2026, 6, 8)
_WEEK_SUN = date(2026, 6, 14)
_TODAY = date(2026, 6, 11)   # Thursday
_PAST_MON = date(2026, 5, 25)  # a Monday two weeks prior


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_user():
    u = MagicMock()
    u.id = _USER_ID
    return u


def _make_client():
    async def _fake():
        return _make_user()
    app.dependency_overrides[resolve_user] = _fake
    return TestClient(app)


def _teardown():
    app.dependency_overrides.pop(resolve_user, None)


def _make_habit(*, hid=None, tracking_type="daily_checkmark", name="Habit A", sort_order=0):
    h = MagicMock(spec=Habit)
    h.id = hid or uuid.uuid4()
    h.user_id = _USER_ID
    h.name = name
    h.description = None
    h.tracking_type = tracking_type
    h.weekly_target = None
    h.unit = None
    h.auto_fill_source = None
    h.icon = None
    h.color = None
    h.sort_order = sort_order
    h.is_archived = False
    h.created_at = None
    h.updated_at = None
    return h


def _make_log(*, habit_id, log_date, log_week_start=_WEEK_MON, value=1.0):
    log = MagicMock(spec=HabitLog)
    log.id = uuid.uuid4()
    log.habit_id = habit_id
    log.user_id = _USER_ID
    log.log_date = log_date
    log.log_week_start = log_week_start
    log.value = value
    log.notes = None
    log.source = "manual"
    return log


def _make_session(active_habits, archived_habits=None, logs=None, workouts=None):
    """Session mock mirroring test_habits_week.py's _make_session."""
    archived_habits = archived_habits or []
    logs = logs or []
    workouts = workouts or []

    sess = MagicMock()
    sess.__enter__ = MagicMock(return_value=sess)
    sess.__exit__ = MagicMock(return_value=False)

    habit_q = MagicMock()
    habit_q.filter.return_value = habit_q
    habit_q.order_by.return_value = habit_q
    habit_q.join.return_value = habit_q
    habit_q.distinct.return_value = habit_q

    _habit_calls = [0]

    def _habit_all():
        _habit_calls[0] += 1
        return active_habits if _habit_calls[0] == 1 else archived_habits

    habit_q.all.side_effect = _habit_all

    log_q = MagicMock()
    log_q.filter.return_value = log_q
    log_q.all.return_value = logs

    workout_q = MagicMock()
    workout_q.filter.return_value = workout_q
    workout_q.all.return_value = workouts

    def _side(model):
        if model is Habit:
            return habit_q
        if model is HabitLog:
            return log_q
        if model is Workout:
            return workout_q
        return MagicMock()

    sess.query.side_effect = _side
    return sess


def _patch_today(target_date):
    from zoneinfo import ZoneInfo
    _BKK = ZoneInfo("Asia/Bangkok")
    fake_dt = datetime(target_date.year, target_date.month, target_date.day, 10, 0, 0, tzinfo=_BKK)
    mock_dt = MagicMock()
    mock_dt.now.return_value = fake_dt
    mock_dt.fromisoformat = datetime.fromisoformat
    mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
    return patch("backend.main._datetime", mock_dt)


# ── AC (a): wheel always has exactly 7 entries ────────────────────────────────

class TestACa_WheelAlways7Entries:
    """Card A depends on exactly 7 wheel entries (one per day Mon–Sun)."""

    def test_wheel_has_7_entries_with_habits(self):
        client = _make_client()
        hid = uuid.uuid4()
        habit = _make_habit(hid=hid)
        log = _make_log(habit_id=hid, log_date=_WEEK_MON)
        sess = _make_session([habit], logs=[log])

        try:
            with _patch_today(_TODAY), patch("backend.main.Session", return_value=sess):
                res = client.get("/api/habits/week?week_start=2026-06-08")
            assert res.status_code == 200, res.text
            wheel = res.json()["wheel"]
            assert len(wheel) == 7, f"Expected 7 wheel entries, got {len(wheel)}"
        finally:
            _teardown()

    def test_wheel_has_7_entries_with_no_habits(self):
        client = _make_client()
        sess = _make_session([])

        try:
            with _patch_today(_TODAY), patch("backend.main.Session", return_value=sess):
                res = client.get("/api/habits/week?week_start=2026-06-08")
            assert res.status_code == 200, res.text
            wheel = res.json()["wheel"]
            assert len(wheel) == 7, f"Wheel must have 7 entries even with no habits, got {len(wheel)}"
        finally:
            _teardown()


# ── AC (b): streaks.best is null when no daily_checkmark habits ───────────────

class TestACb_StreaksBestNullWithNoDaily:
    """Card B best-streak tile must be hidden when streaks.best is null."""

    def test_streaks_best_null_when_only_weekly_habits(self):
        client = _make_client()
        hid = uuid.uuid4()
        weekly_habit = _make_habit(hid=hid, tracking_type="weekly_count")
        sess = _make_session([weekly_habit])

        try:
            with _patch_today(_TODAY), patch("backend.main.Session", return_value=sess):
                res = client.get("/api/habits/week?week_start=2026-06-08")
            assert res.status_code == 200, res.text
            streaks = res.json()["streaks"]
            assert "best" in streaks, "Response must include streaks.best key"
            assert streaks["best"] is None, (
                f"streaks.best should be null with only weekly habits, got {streaks['best']}"
            )
        finally:
            _teardown()

    def test_streaks_best_null_when_no_habits(self):
        client = _make_client()
        sess = _make_session([])

        try:
            with _patch_today(_TODAY), patch("backend.main.Session", return_value=sess):
                res = client.get("/api/habits/week?week_start=2026-06-08")
            assert res.status_code == 200, res.text
            streaks = res.json()["streaks"]
            assert streaks["best"] is None, "streaks.best must be null when no habits"
        finally:
            _teardown()


# ── AC (c): streaks.best includes habit_name and length ───────────────────────

class TestACc_StreaksBestHasHabitName:
    """Card B uses streaks.best.habit_name and streaks.best.length."""

    def test_streaks_best_shape_with_daily_habit(self):
        client = _make_client()
        hid = uuid.uuid4()
        habit = _make_habit(hid=hid, tracking_type="daily_checkmark", name="Morning run")
        # Log Monday through Thursday (4 consecutive days)
        logs = [
            _make_log(habit_id=hid, log_date=date(2026, 6, 8)),
            _make_log(habit_id=hid, log_date=date(2026, 6, 9)),
            _make_log(habit_id=hid, log_date=date(2026, 6, 10)),
            _make_log(habit_id=hid, log_date=date(2026, 6, 11)),
        ]
        sess = _make_session([habit], logs=logs)

        try:
            with _patch_today(_TODAY), patch("backend.main.Session", return_value=sess):
                res = client.get("/api/habits/week?week_start=2026-06-08")
            assert res.status_code == 200, res.text
            best = res.json()["streaks"]["best"]
            assert best is not None, "streaks.best must not be null when daily habits exist"
            assert "habit_name" in best, "streaks.best must include habit_name"
            assert "length" in best, "streaks.best must include length"
            assert best["habit_name"] == "Morning run"
            assert best["length"] >= 1, "streak length must be at least 1"
        finally:
            _teardown()


# ── AC (d): last_week is null when no log data for prior week ─────────────────

class TestACd_LastWeekNullWhenNoData:
    """Card B last-week tile must show 'no data' when last_week is null."""

    def test_last_week_null_when_no_logs(self):
        client = _make_client()
        hid = uuid.uuid4()
        habit = _make_habit(hid=hid, tracking_type="daily_checkmark")
        sess = _make_session([habit], logs=[])   # no logs at all

        try:
            with _patch_today(_TODAY), patch("backend.main.Session", return_value=sess):
                res = client.get("/api/habits/week?week_start=2026-06-08")
            assert res.status_code == 200, res.text
            assert res.json()["last_week"] is None, (
                "last_week must be null when there are no log records"
            )
        finally:
            _teardown()


# ── AC (e): week_totals carries all fields required by Card A / B ─────────────

class TestACe_WeekTotalsShape:
    """week_totals must include all fields the hero cards read."""

    def test_week_totals_has_required_fields(self):
        client = _make_client()
        hid = uuid.uuid4()
        habit = _make_habit(hid=hid, tracking_type="daily_checkmark")
        logs = [_make_log(habit_id=hid, log_date=_WEEK_MON)]
        sess = _make_session([habit], logs=logs)

        try:
            with _patch_today(_TODAY), patch("backend.main.Session", return_value=sess):
                res = client.get("/api/habits/week?week_start=2026-06-08")
            assert res.status_code == 200, res.text
            totals = res.json()["week_totals"]
            for field in ("elapsed_days", "pct_elapsed", "pct_full_week",
                          "daily_habits_count", "daily_done"):
                assert field in totals, f"week_totals missing required field '{field}'"
        finally:
            _teardown()

    def test_elapsed_days_reflects_today_position(self):
        client = _make_client()
        hid = uuid.uuid4()
        habit = _make_habit(hid=hid, tracking_type="daily_checkmark")
        sess = _make_session([habit])

        try:
            # Today = Thursday (day 4 of Mon–Sun)
            with _patch_today(_TODAY), patch("backend.main.Session", return_value=sess):
                res = client.get("/api/habits/week?week_start=2026-06-08")
            assert res.status_code == 200, res.text
            totals = res.json()["week_totals"]
            assert totals["elapsed_days"] == 4, (
                f"Thursday is day 4 of the week (Mon=1), got elapsed_days={totals['elapsed_days']}"
            )
        finally:
            _teardown()


# ── AC (f): day_scores entry for today has done/of for Today tile ─────────────

class TestACf_DayScoresTodayTile:
    """Card B Today tile reads day_scores entry where date == today."""

    def test_today_day_score_has_done_and_of(self):
        client = _make_client()
        hid_a = uuid.uuid4()
        hid_b = uuid.uuid4()
        habit_a = _make_habit(hid=hid_a, tracking_type="daily_checkmark", sort_order=0)
        habit_b = _make_habit(hid=hid_b, tracking_type="daily_checkmark", sort_order=1)
        # Log only habit_a on today (Thursday 2026-06-11)
        logs = [_make_log(habit_id=hid_a, log_date=_TODAY)]
        sess = _make_session([habit_a, habit_b], logs=logs)

        try:
            with _patch_today(_TODAY), patch("backend.main.Session", return_value=sess):
                res = client.get("/api/habits/week?week_start=2026-06-08")
            assert res.status_code == 200, res.text
            day_scores = res.json()["day_scores"]
            today_score = next((d for d in day_scores if d["date"] == "2026-06-11"), None)
            assert today_score is not None, "day_scores must include an entry for today"
            assert today_score["done"] == 1, (
                f"1 of 2 habits logged → done=1, got {today_score['done']}"
            )
            assert today_score["of"] == 2, (
                f"2 daily habits → of=2, got {today_score['of']}"
            )
        finally:
            _teardown()


# ── AC (g): past-week: is_current_week=false, no "today" in wheel ─────────────

class TestACg_PastWeekNoTodayInWheel:
    """Past-week view must not show a blue (today) segment in the wheel."""

    def test_past_week_has_no_today_state_in_wheel(self):
        client = _make_client()
        hid = uuid.uuid4()
        habit = _make_habit(hid=hid, tracking_type="daily_checkmark")
        past_mon = date(2026, 5, 25)  # Monday two weeks before today
        logs = [
            _make_log(habit_id=hid, log_date=date(2026, 5, 25), log_week_start=past_mon),
            _make_log(habit_id=hid, log_date=date(2026, 5, 26), log_week_start=past_mon),
        ]
        sess = _make_session([habit], logs=logs)

        try:
            with _patch_today(_TODAY), patch("backend.main.Session", return_value=sess):
                res = client.get("/api/habits/week?week_start=2026-05-25")
            assert res.status_code == 200, res.text
            body = res.json()
            assert body["is_current_week"] is False, "Past week must have is_current_week=false"
            wheel_states = [w["state"] for w in body["wheel"]]
            assert "today" not in wheel_states, (
                f"Past-week wheel must not contain 'today' state; got {wheel_states}"
            )
        finally:
            _teardown()


# ── AC (h): past-week: pct_full_week reflects complete-week completion ─────────

class TestACh_PastWeekPctFullWeek:
    """Card B 'Week result' tile uses week_totals.pct_full_week in past-week view."""

    def test_pct_full_week_present_in_past_week_response(self):
        client = _make_client()
        hid = uuid.uuid4()
        habit = _make_habit(hid=hid, tracking_type="daily_checkmark")
        past_mon = date(2026, 5, 25)
        # Log 5 of 7 days
        logs = [
            _make_log(habit_id=hid, log_date=date(2026, 5, 25), log_week_start=past_mon),
            _make_log(habit_id=hid, log_date=date(2026, 5, 26), log_week_start=past_mon),
            _make_log(habit_id=hid, log_date=date(2026, 5, 27), log_week_start=past_mon),
            _make_log(habit_id=hid, log_date=date(2026, 5, 28), log_week_start=past_mon),
            _make_log(habit_id=hid, log_date=date(2026, 5, 29), log_week_start=past_mon),
        ]
        sess = _make_session([habit], logs=logs)

        try:
            with _patch_today(_TODAY), patch("backend.main.Session", return_value=sess):
                res = client.get("/api/habits/week?week_start=2026-05-25")
            assert res.status_code == 200, res.text
            totals = res.json()["week_totals"]
            assert "pct_full_week" in totals, "week_totals must include pct_full_week"
            # 5 done / (1 habit * 7 days) = 71.43%
            assert abs(totals["pct_full_week"] - round(500 / 7, 2)) < 0.1, (
                f"5/7 = ~71.43%, got {totals['pct_full_week']}"
            )
        finally:
            _teardown()
