"""Tests for issue #429: GET /api/habits/week batch endpoint.

9 test classes (a–i), each anchored to one Acceptance Criterion item.
Uses FastAPI TestClient with mocked resolve_user and Session.
"""
import uuid
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from backend.main import app, resolve_user
from backend.models import Habit, HabitLog, Workout

_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000429")
_WEEK_MON = date(2026, 6, 8)   # Monday of the test week
_WEEK_SUN = date(2026, 6, 14)  # Sunday of the test week
_TODAY_THU = date(2026, 6, 11)  # Thursday — within the test week


# ── Shared helpers ────────────────────────────────────────────────────────────

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


def _make_habit(
    *,
    hid=None,
    tracking_type="daily_checkmark",
    weekly_target=None,
    auto_fill_source=None,
    is_archived=False,
    sort_order=0,
    name="Habit",
    unit=None,
):
    h = MagicMock(spec=Habit)
    h.id = hid or uuid.uuid4()
    h.user_id = _USER_ID
    h.name = name
    h.description = None
    h.tracking_type = tracking_type
    h.weekly_target = weekly_target
    h.unit = unit
    h.auto_fill_source = auto_fill_source
    h.icon = None
    h.color = None
    h.sort_order = sort_order
    h.is_archived = is_archived
    h.created_at = None
    h.updated_at = None
    return h


def _make_log(
    *,
    habit_id,
    log_date,
    log_week_start=_WEEK_MON,
    value=1.0,
    source="manual",
):
    log = MagicMock(spec=HabitLog)
    log.id = uuid.uuid4()
    log.habit_id = habit_id
    log.user_id = _USER_ID
    log.log_date = log_date
    log.log_week_start = log_week_start
    log.value = value
    log.notes = None
    log.source = source
    return log


def _make_workout(
    *,
    workout_date,
    workout_type="run",
    zone2_minutes=None,
    duration_seconds=None,
    distance_km=None,
):
    w = MagicMock(spec=Workout)
    w.id = uuid.uuid4()
    w.user_id = _USER_ID
    w.workout_date = workout_date
    w.workout_type = workout_type
    w.zone2_minutes = zone2_minutes
    w.duration_seconds = duration_seconds
    w.distance_km = distance_km
    return w


def _make_session(active_habits, archived_habits=None, logs=None, workouts=None):
    """Build a session mock for GET /api/habits/week.

    Query dispatch:
    - Habit 1st call → active_habits (filter + order_by)
    - Habit 2nd call → archived_habits (join + distinct)
    - HabitLog → bulk logs list
    - Workout → workouts list
    """
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
    """Return a context manager that patches _bangkok_today() to return target_date."""
    from zoneinfo import ZoneInfo
    _BANGKOK = ZoneInfo("Asia/Bangkok")
    fake_dt = datetime(
        target_date.year, target_date.month, target_date.day, 10, 0, 0, tzinfo=_BANGKOK
    )
    mock_dt = MagicMock()
    mock_dt.now.return_value = fake_dt
    mock_dt.fromisoformat = datetime.fromisoformat
    mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
    return patch("backend.main._datetime", mock_dt)


# ── AC (a): Response shape valid with mixed daily + weekly habits ─────────────

class TestACa_ResponseShape:
    """(a) Response contains all required top-level keys; daily and weekly habits placed correctly."""

    def test_response_shape_with_mixed_habits(self):
        client = _make_client()
        hid_d = uuid.uuid4()
        hid_w = uuid.uuid4()
        daily = _make_habit(hid=hid_d, tracking_type="daily_checkmark")
        weekly = _make_habit(hid=hid_w, tracking_type="weekly_minutes", weekly_target=120.0)
        log = _make_log(habit_id=hid_d, log_date=_WEEK_MON)
        sess = _make_session([daily, weekly], logs=[log])

        try:
            with _patch_today(_TODAY_THU), patch("backend.main.Session", return_value=sess):
                res = client.get("/api/habits/week?week_start=2026-06-08")
            assert res.status_code == 200, res.text
            body = res.json()
            for key in (
                "week_start", "week_end", "is_current_week",
                "daily_habits", "weekly_habits", "day_scores", "week_totals", "wheel",
            ):
                assert key in body, f"missing top-level key '{key}'"
            # daily_checkmark goes in daily_habits
            assert len(body["daily_habits"]) == 1
            assert body["daily_habits"][0]["id"] == str(hid_d)
            assert len(body["daily_habits"][0]["days"]) == 7
            # weekly_minutes goes in weekly_habits
            assert len(body["weekly_habits"]) == 1
            assert body["weekly_habits"][0]["id"] == str(hid_w)
            for wkey in ("target", "current_value", "pct", "remaining", "daily_breakdown"):
                assert wkey in body["weekly_habits"][0], f"missing weekly_habits key '{wkey}'"
            assert body["week_start"] == "2026-06-08"
            assert body["week_end"] == "2026-06-14"
        finally:
            _teardown()


# ── AC (b): Day states correct around today's boundary in Bangkok TZ ──────────

class TestACb_DayStatesBangkok:
    """(b) day.state reflects done/missed/today_pending/future relative to Bangkok today."""

    def test_day_states_around_today(self):
        client = _make_client()
        hid = uuid.uuid4()
        habit = _make_habit(hid=hid, tracking_type="daily_checkmark")
        # Log only on Monday; today is Thursday 2026-06-11
        logs = [_make_log(habit_id=hid, log_date=date(2026, 6, 8))]
        sess = _make_session([habit], logs=logs)

        try:
            with _patch_today(_TODAY_THU), patch("backend.main.Session", return_value=sess):
                res = client.get("/api/habits/week?week_start=2026-06-08")
            assert res.status_code == 200, res.text
            body = res.json()
            days = {d["date"]: d["state"] for d in body["daily_habits"][0]["days"]}

            assert days["2026-06-08"] == "done",          "Mon with log → done"
            assert days["2026-06-09"] == "missed",        "Tue, no log, past → missed"
            assert days["2026-06-10"] == "missed",        "Wed, no log, past → missed"
            assert days["2026-06-11"] == "today_pending", "Thu (today), no log → today_pending"
            assert days["2026-06-12"] == "future",        "Fri → future"
            assert days["2026-06-13"] == "future",        "Sat → future"
            assert days["2026-06-14"] == "future",        "Sun → future"
        finally:
            _teardown()


# ── AC (c): weekly_target < 7 reflected in total.target ──────────────────────

class TestACc_WeeklyTargetInTotal:
    """(c) daily_habits[].total.target reflects weekly_target (default 7 when unset)."""

    def test_weekly_target_less_than_7(self):
        client = _make_client()
        hid = uuid.uuid4()
        habit = _make_habit(hid=hid, tracking_type="daily_checkmark", weekly_target=5.0)
        sess = _make_session([habit])

        try:
            with _patch_today(_TODAY_THU), patch("backend.main.Session", return_value=sess):
                res = client.get("/api/habits/week?week_start=2026-06-08")
            assert res.status_code == 200, res.text
            body = res.json()
            assert body["daily_habits"][0]["total"]["target"] == 5, (
                f"weekly_target=5 should set total.target=5, got {body['daily_habits'][0]['total']['target']}"
            )
        finally:
            _teardown()

    def test_weekly_target_defaults_to_7_when_unset(self):
        client = _make_client()
        hid = uuid.uuid4()
        habit = _make_habit(hid=hid, tracking_type="daily_checkmark", weekly_target=None)
        sess = _make_session([habit])

        try:
            with _patch_today(_TODAY_THU), patch("backend.main.Session", return_value=sess):
                res = client.get("/api/habits/week?week_start=2026-06-08")
            body = res.json()
            assert body["daily_habits"][0]["total"]["target"] == 7
        finally:
            _teardown()


# ── AC (d): day_scores[].of excludes weekly-type habits ──────────────────────

class TestACd_DayScoresExcludesWeekly:
    """(d) day_scores[].of counts only daily_checkmark habits, not weekly types."""

    def test_day_scores_of_excludes_weekly_habits(self):
        client = _make_client()
        hid_d = uuid.uuid4()
        hid_w = uuid.uuid4()
        daily = _make_habit(hid=hid_d, tracking_type="daily_checkmark")
        weekly = _make_habit(hid=hid_w, tracking_type="weekly_minutes", weekly_target=60.0)
        # Both logged on Monday
        logs = [
            _make_log(habit_id=hid_d, log_date=date(2026, 6, 8)),
            _make_log(habit_id=hid_w, log_date=date(2026, 6, 8), value=30.0),
        ]
        sess = _make_session([daily, weekly], logs=logs)

        try:
            with _patch_today(_TODAY_THU), patch("backend.main.Session", return_value=sess):
                res = client.get("/api/habits/week?week_start=2026-06-08")
            assert res.status_code == 200, res.text
            body = res.json()
            mon_score = next(s for s in body["day_scores"] if s["date"] == "2026-06-08")
            assert mon_score["of"] == 1, (
                f"'of' must count only daily_checkmark habits (1), got {mon_score['of']}"
            )
            assert mon_score["done"] == 1, "daily habit was logged on Mon → done=1"
        finally:
            _teardown()


# ── AC (e): wheel full / partial / zero / today / future rules ───────────────

class TestACe_WheelStates:
    """(e) wheel entries use correct state: full/partial/zero/today/future."""

    def test_wheel_full_partial_zero_today_future(self):
        client = _make_client()
        hid_a = uuid.uuid4()
        hid_b = uuid.uuid4()
        habit_a = _make_habit(hid=hid_a, tracking_type="daily_checkmark", sort_order=0)
        habit_b = _make_habit(hid=hid_b, tracking_type="daily_checkmark", sort_order=1)
        # Mon: both done → full
        # Tue: only habit_a done → partial
        # Wed: neither → zero
        # Thu: today (2026-06-11)
        # Fri-Sun: future
        logs = [
            _make_log(habit_id=hid_a, log_date=date(2026, 6, 8)),
            _make_log(habit_id=hid_b, log_date=date(2026, 6, 8)),
            _make_log(habit_id=hid_a, log_date=date(2026, 6, 9)),
        ]
        sess = _make_session([habit_a, habit_b], logs=logs)

        try:
            with _patch_today(_TODAY_THU), patch("backend.main.Session", return_value=sess):
                res = client.get("/api/habits/week?week_start=2026-06-08")
            assert res.status_code == 200, res.text
            wheel = {w["date"]: w["state"] for w in res.json()["wheel"]}

            assert wheel["2026-06-08"] == "full",   "Mon: both habits done → full"
            assert wheel["2026-06-09"] == "partial", "Tue: 1 of 2 done → partial"
            assert wheel["2026-06-10"] == "zero",   "Wed: none done → zero"
            assert wheel["2026-06-11"] == "today",  "Today always → today"
            assert wheel["2026-06-12"] == "future", "Fri → future"
            assert wheel["2026-06-14"] == "future", "Sun → future"
        finally:
            _teardown()


# ── AC (f): pct_elapsed uses elapsed days; pct_full_week uses 7 ───────────────

class TestACf_PctElapsed:
    """(f) week_totals.pct_elapsed denominates by elapsed days; pct_full_week by 7."""

    def test_pct_elapsed_uses_elapsed_days_not_7(self):
        client = _make_client()
        hid = uuid.uuid4()
        habit = _make_habit(hid=hid, tracking_type="daily_checkmark")
        # Log only on Monday; today = Thursday (4 elapsed days: Mon, Tue, Wed, Thu)
        logs = [_make_log(habit_id=hid, log_date=date(2026, 6, 8))]
        sess = _make_session([habit], logs=logs)

        try:
            with _patch_today(_TODAY_THU), patch("backend.main.Session", return_value=sess):
                res = client.get("/api/habits/week?week_start=2026-06-08")
            assert res.status_code == 200, res.text
            totals = res.json()["week_totals"]
            # 1 habit × 4 elapsed days = 4 possible; 1 done → 25%
            assert totals["pct_elapsed"] == 25.0, (
                f"Expected pct_elapsed=25.0 (1/4 elapsed), got {totals['pct_elapsed']}"
            )
            # 1 done / (1 habit × 7 days) ≈ 14.29%
            assert abs(totals["pct_full_week"] - round(100 / 7, 2)) < 0.01, (
                f"Expected pct_full_week≈{round(100/7,2)}, got {totals['pct_full_week']}"
            )
        finally:
            _teardown()


# ── AC (g): Non-Monday week_start → 422 ──────────────────────────────────────

class TestACg_NonMonday422:
    """(g) A week_start that is not Monday returns HTTP 422 with descriptive error."""

    def test_tuesday_week_start_returns_422(self):
        client = _make_client()
        try:
            res = client.get("/api/habits/week?week_start=2026-06-09")  # Tuesday
            assert res.status_code == 422, f"Expected 422, got {res.status_code}"
            detail = res.json().get("detail", "")
            assert "monday" in detail.lower() or "Monday" in detail, (
                f"422 detail should mention Monday, got: {detail}"
            )
        finally:
            _teardown()

    def test_wednesday_week_start_returns_422(self):
        client = _make_client()
        try:
            res = client.get("/api/habits/week?week_start=2026-06-10")  # Wednesday
            assert res.status_code == 422
        finally:
            _teardown()


# ── AC (h): Past week returns complete data with is_current_week: false ───────

class TestACh_PastWeek:
    """(h) A past week_start returns is_current_week=false; all days are done or missed."""

    def test_past_week_returns_complete_data(self):
        client = _make_client()
        hid = uuid.uuid4()
        habit = _make_habit(hid=hid, tracking_type="daily_checkmark")
        past_mon = date(2026, 6, 1)  # Monday two weeks ago
        # Log Mon–Fri of that week; Sat+Sun unlogged
        logs = [
            _make_log(habit_id=hid, log_date=date(2026, 6, 1), log_week_start=past_mon),
            _make_log(habit_id=hid, log_date=date(2026, 6, 2), log_week_start=past_mon),
            _make_log(habit_id=hid, log_date=date(2026, 6, 3), log_week_start=past_mon),
            _make_log(habit_id=hid, log_date=date(2026, 6, 4), log_week_start=past_mon),
            _make_log(habit_id=hid, log_date=date(2026, 6, 5), log_week_start=past_mon),
        ]
        sess = _make_session([habit], logs=logs)

        try:
            with _patch_today(_TODAY_THU), patch("backend.main.Session", return_value=sess):
                res = client.get("/api/habits/week?week_start=2026-06-01")
            assert res.status_code == 200, res.text
            body = res.json()
            assert body["is_current_week"] is False, "Past week must have is_current_week=false"
            days = body["daily_habits"][0]["days"]
            assert len(days) == 7
            for day in days:
                assert day["state"] in ("done", "missed"), (
                    f"Past week day {day['date']} state must be done/missed, got {day['state']}"
                )
        finally:
            _teardown()


# ── AC (i): Autofill contributions appear in weekly_habits[].daily_breakdown ──

class TestACi_AutofillBreakdown:
    """(i) Workout autofill values appear in weekly_habits[].daily_breakdown."""

    def test_autofill_contributions_in_daily_breakdown(self):
        client = _make_client()
        hid = uuid.uuid4()
        habit = _make_habit(
            hid=hid,
            tracking_type="weekly_minutes",
            weekly_target=120.0,
            auto_fill_source="workout.zone2_minutes",
            unit="min",
        )
        workout = _make_workout(
            workout_date=date(2026, 6, 10),  # Wednesday
            workout_type="run",
            zone2_minutes=45,
        )
        sess = _make_session([habit], workouts=[workout])

        try:
            with _patch_today(_TODAY_THU), patch("backend.main.Session", return_value=sess):
                res = client.get("/api/habits/week?week_start=2026-06-08")
            assert res.status_code == 200, res.text
            body = res.json()
            assert len(body["weekly_habits"]) == 1
            wh = body["weekly_habits"][0]
            assert wh["current_value"] == 45.0, "autofill should contribute to current_value"
            breakdown = wh["daily_breakdown"]
            assert len(breakdown) >= 1, "autofill workout should appear in daily_breakdown"
            dates_in_bd = [b["date"] for b in breakdown]
            assert "2026-06-10" in dates_in_bd, "Wed workout must be in daily_breakdown"
            wed = next(b for b in breakdown if b["date"] == "2026-06-10")
            assert wed["value"] == 45.0
        finally:
            _teardown()
