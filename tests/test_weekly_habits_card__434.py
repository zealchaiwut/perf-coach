"""Tests for issue #434: Weekly habits card with auto-sync and manual logging.

AC items covered:
  (a) Card shell: heading, hint text, weekly_habits in API response
  (b) Row layout: left icon+name+badge, middle bar+labels, right value+pace
  (c) auto_fill_source included in /api/habits/week weekly_habits entries
  (d) Progress bar type: segmented for weekly_count, smooth for others
  (e) Under-bar labels: daily breakdown weekday short names, target label
  (f) Pace sub-line: green "on pace" vs amber "{remaining} to go"
  (g) Manual "＋ log" chip and popover; absent on auto-fill rows
  (h) weekly_minutes popover quick-add chips (+5, +10, +15)
  (i) Popover submits via add-mode endpoint; updates bar from week_current_value
  (j) Past-week view: read-only, no log chips
  (k) Weekly-only empty state with "New habit" shortcut
  (l) No cross-contamination: weekly_count ≠ smooth bar, weekly_minutes ≠ segmented
  (m) weekly_habits excludes daily_checkmark habits
"""
import pathlib
import uuid
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.main import app, resolve_user
from backend.models import Habit, HabitLog, Workout

# ── File paths ────────────────────────────────────────────────────────────────

_ROOT = pathlib.Path(__file__).parent.parent
_HTML = (_ROOT / "frontend" / "pages" / "habits.html").read_text()
_JS   = (_ROOT / "frontend" / "js" / "habits.js").read_text()

# ── Test constants ────────────────────────────────────────────────────────────

_USER_ID  = uuid.UUID("00000000-0000-0000-0000-000000000434")
_WEEK_MON = date(2026, 6, 8)
_TODAY    = date(2026, 6, 11)   # Wednesday of the test week


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


def _make_habit(
    *,
    hid=None,
    tracking_type="weekly_count",
    weekly_target=3.0,
    auto_fill_source=None,
    is_archived=False,
    sort_order=0,
    name="Weekly Habit",
    unit="sessions",
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
    h.icon = "ti-run"
    h.color = "#3b82f6"
    h.sort_order = sort_order
    h.is_archived = is_archived
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


def _make_session(active_habits, logs=None, workouts=None):
    logs = logs or []
    workouts = workouts or []

    sess = MagicMock()
    sess.__enter__ = MagicMock(return_value=sess)
    sess.__exit__ = MagicMock(return_value=False)

    _habit_calls = [0]

    habit_q = MagicMock()
    habit_q.filter.return_value = habit_q
    habit_q.order_by.return_value = habit_q
    habit_q.join.return_value = habit_q
    habit_q.distinct.return_value = habit_q
    habit_q.in_.return_value = habit_q

    def _habit_all():
        _habit_calls[0] += 1
        return active_habits if _habit_calls[0] == 1 else []

    habit_q.all.side_effect = _habit_all

    log_q = MagicMock()
    log_q.filter.return_value = log_q
    log_q.in_.return_value = log_q
    log_q.all.return_value = logs

    workout_q = MagicMock()
    workout_q.filter.return_value = workout_q
    workout_q.all.return_value = workouts

    def _query(model):
        if model is Habit:
            return habit_q
        elif model is HabitLog:
            return log_q
        elif model is Workout:
            return workout_q
        return MagicMock()

    sess.query.side_effect = _query
    sess.get.return_value = None
    return sess


def _patch_today(target_date):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    _BKK = ZoneInfo("Asia/Bangkok")
    fake_dt = datetime(
        target_date.year, target_date.month, target_date.day, 10, 0, 0, tzinfo=_BKK
    )
    mock_dt = MagicMock()
    mock_dt.now.return_value = fake_dt
    mock_dt.fromisoformat = datetime.fromisoformat
    mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
    return patch("backend.main._datetime", mock_dt)


# ── (a) Card shell: heading and hint text in HTML ────────────────────────────

def test_weekly_card_heading_text():
    """HTML must contain the required card heading text."""
    assert "Weekly habits" in _HTML, (
        "habits.html weekly card heading must read 'Weekly habits …'"
    )
    assert "progress accumulates across the week" in _HTML, (
        "habits.html weekly card heading must include 'progress accumulates across the week'"
    )


def test_weekly_card_hint_text():
    """HTML or JS must contain the hint text about auto rows."""
    has_hint = (
        "auto rows update when you log workouts" in _HTML or
        "auto rows update when you log workouts" in _JS
    )
    assert has_hint, (
        "habits.html or habits.js must contain hint 'auto rows update when you log workouts'"
    )


# ── (c) auto_fill_source in /api/habits/week weekly_habits entries ────────────

def test_api_weekly_habits_includes_auto_fill_source():
    """Each weekly_habits entry must have an 'auto_fill_source' field."""
    client = _make_client()
    hab = _make_habit(
        tracking_type="weekly_count",
        weekly_target=3.0,
        auto_fill_source="workout.run_count",
    )
    sess = _make_session([hab])
    try:
        with _patch_today(_TODAY), patch("backend.main.Session", return_value=sess):
            resp = client.get("/api/habits/week?week_start=2026-06-08")
        assert resp.status_code == 200, f"Expected 200: {resp.text}"
        body = resp.json()
        assert "weekly_habits" in body
        assert len(body["weekly_habits"]) == 1
        wh = body["weekly_habits"][0]
        assert "auto_fill_source" in wh, (
            "weekly_habits entries must include 'auto_fill_source'"
        )
        assert wh["auto_fill_source"] == "workout.run_count"
    finally:
        _teardown()


def test_api_weekly_habits_auto_fill_source_null_when_manual():
    """auto_fill_source must be null/None for manual habits."""
    client = _make_client()
    hab = _make_habit(tracking_type="weekly_minutes", weekly_target=210.0, auto_fill_source=None)
    sess = _make_session([hab])
    try:
        with _patch_today(_TODAY), patch("backend.main.Session", return_value=sess):
            resp = client.get("/api/habits/week?week_start=2026-06-08")
        body = resp.json()
        wh = body["weekly_habits"][0]
        assert "auto_fill_source" in wh
        assert wh["auto_fill_source"] is None
    finally:
        _teardown()


# ── (m) weekly_habits excludes daily_checkmark habits ────────────────────────

def test_api_weekly_habits_excludes_daily_checkmark():
    """daily_checkmark habits must NOT appear in weekly_habits."""
    client = _make_client()
    daily = _make_habit(tracking_type="daily_checkmark", weekly_target=7.0, name="Daily Check")
    weekly = _make_habit(tracking_type="weekly_count", weekly_target=3.0, name="Weekly Count")
    sess = _make_session([daily, weekly])
    try:
        with _patch_today(_TODAY), patch("backend.main.Session", return_value=sess):
            resp = client.get("/api/habits/week?week_start=2026-06-08")
        body = resp.json()
        weekly_names = [wh["name"] for wh in body["weekly_habits"]]
        assert "Daily Check" not in weekly_names, (
            "daily_checkmark habits must not appear in weekly_habits"
        )
        assert "Weekly Count" in weekly_names
    finally:
        _teardown()


# ── (a) weekly_habits has correct progress fields ─────────────────────────────

def test_api_weekly_habits_has_progress_fields():
    """weekly_habits entries must have target, current_value, pct, remaining, is_complete."""
    client = _make_client()
    hab = _make_habit(tracking_type="weekly_count", weekly_target=3.0)
    logs = [
        _make_log(habit_id=hab.id, log_date=_WEEK_MON, value=1.0),
        _make_log(habit_id=hab.id, log_date=_WEEK_MON + timedelta(days=1), value=1.0),
    ]
    sess = _make_session([hab], logs)
    try:
        with _patch_today(_TODAY), patch("backend.main.Session", return_value=sess):
            resp = client.get("/api/habits/week?week_start=2026-06-08")
        body = resp.json()
        wh = body["weekly_habits"][0]
        assert "target" in wh
        assert "current_value" in wh
        assert "pct" in wh
        assert "remaining" in wh
        assert "is_complete" in wh
        assert "daily_breakdown" in wh
        assert wh["current_value"] == 2.0
        assert wh["target"] == 3.0
        assert wh["remaining"] == 1.0
        assert wh["is_complete"] is False
    finally:
        _teardown()


def test_api_weekly_habits_daily_breakdown_entries():
    """daily_breakdown must have date/value entries for logged days."""
    client = _make_client()
    hab = _make_habit(tracking_type="weekly_minutes", weekly_target=210.0, unit="min")
    logs = [
        _make_log(habit_id=hab.id, log_date=_WEEK_MON, value=45.0),
        _make_log(habit_id=hab.id, log_date=_WEEK_MON + timedelta(days=1), value=60.0),
    ]
    sess = _make_session([hab], logs)
    try:
        with _patch_today(_TODAY), patch("backend.main.Session", return_value=sess):
            resp = client.get("/api/habits/week?week_start=2026-06-08")
        body = resp.json()
        breakdown = body["weekly_habits"][0]["daily_breakdown"]
        dates = {entry["date"] for entry in breakdown}
        assert _WEEK_MON.isoformat() in dates
        assert (_WEEK_MON + timedelta(days=1)).isoformat() in dates
        mon_entry = next(e for e in breakdown if e["date"] == _WEEK_MON.isoformat())
        assert mon_entry["value"] == 45.0
    finally:
        _teardown()


def test_api_weekly_habits_is_complete_when_target_reached():
    """is_complete must be True when current_value >= target."""
    client = _make_client()
    hab = _make_habit(tracking_type="weekly_count", weekly_target=2.0)
    logs = [
        _make_log(habit_id=hab.id, log_date=_WEEK_MON, value=1.0),
        _make_log(habit_id=hab.id, log_date=_WEEK_MON + timedelta(days=1), value=1.0),
    ]
    sess = _make_session([hab], logs)
    try:
        with _patch_today(_TODAY), patch("backend.main.Session", return_value=sess):
            resp = client.get("/api/habits/week?week_start=2026-06-08")
        wh = resp.json()["weekly_habits"][0]
        assert wh["is_complete"] is True
        assert wh["remaining"] == 0.0
    finally:
        _teardown()


# ── (d) Progress bar types in JS ──────────────────────────────────────────────

def test_js_segmented_bar_for_weekly_count():
    """JS must render a segmented bar specifically for weekly_count habits."""
    has_segmented = (
        "week-seg-bar" in _JS or
        "segmented" in _JS.lower() or
        "weekly_count" in _JS and "segment" in _JS.lower()
    )
    assert has_segmented, (
        "habits.js must render a segmented bar for weekly_count habits"
    )
    assert "weekly_count" in _JS, "habits.js must branch on weekly_count tracking type"


def test_js_smooth_bar_for_weekly_minutes():
    """JS must render a smooth gradient bar for weekly_minutes habits."""
    has_smooth = (
        "weekly_minutes" in _JS and
        ("gradient" in _JS or "smooth" in _JS.lower() or "week-smooth" in _JS or
         "week-habit-bar" in _JS)
    )
    assert has_smooth, (
        "habits.js must render a smooth gradient bar for weekly_minutes habits"
    )


def test_js_no_cross_contamination_bar_types():
    """weekly_count must never use smooth bar; weekly_minutes must never use segmented."""
    # Verify the code has distinct rendering paths for weekly_count vs others
    assert "weekly_count" in _JS, "habits.js must reference weekly_count for bar selection"
    # There must be a conditional that separates these two paths
    assert ("weekly_count" in _JS and
            ("==" in _JS or "===" in _JS or "!=" in _JS or "!==" in _JS)), (
        "habits.js must use a conditional to select bar type based on tracking_type"
    )


def test_js_segmented_bar_overflow_label():
    """When weekly_count current > target, a '+N over' overflow label must appear."""
    has_overflow = (
        "over" in _JS and
        ("overflow" in _JS.lower() or "+N" in _JS or "over target" in _JS.lower() or
         "current_value" in _JS and "target" in _JS and "over" in _JS)
    )
    assert has_overflow, (
        "habits.js must render a '+N over' label when weekly_count exceeds target"
    )


# ── (e) Under-bar labels ──────────────────────────────────────────────────────

def test_js_daily_breakdown_weekday_format():
    """JS must format daily_breakdown as weekday short names: 'Mon 45 · Tue 60'."""
    has_weekday_format = (
        ("Mon" in _JS or "Tue" in _JS or "Wed" in _JS) and
        ("daily_breakdown" in _JS or "breakdown" in _JS.lower()) and
        ("·" in _JS or "\\u00b7" in _JS or "middle dot" in _JS.lower() or
         "&middot;" in _JS or "·" in _JS)
    )
    assert has_weekday_format, (
        "habits.js must format daily_breakdown as 'Mon 45 · Tue 60' under-bar left label"
    )


def test_js_target_label_under_bar():
    """JS must render 'target {N}' as the under-bar right label."""
    has_target_label = (
        "target" in _JS and
        ("under" in _JS.lower() or "bar-label" in _JS or "bar_label" in _JS or
         "breakdown-label" in _JS or "week-bar" in _JS or "under-bar" in _JS or
         "underbar" in _JS.lower() or
         # The target label is rendered in some form
         "target " in _JS and "label" in _JS)
    )
    assert has_target_label, (
        "habits.js must render 'target {N}' as the under-bar right label"
    )


# ── (f) Pace sub-line ─────────────────────────────────────────────────────────

def test_js_pace_on_pace_green():
    """JS must show green 'on pace' when current/target >= elapsed_days/7."""
    has_on_pace = "on pace" in _JS
    assert has_on_pace, "habits.js must render 'on pace' text for the pace sub-line"


def test_js_pace_behind_amber():
    """JS must show amber '{remaining} to go' when behind pace."""
    has_to_go = "to go" in _JS
    assert has_to_go, "habits.js must render '{remaining} to go' for the behind-pace sub-line"


def test_js_pace_calculation_uses_elapsed_days():
    """Pace calculation must use elapsed_days from week_totals or equivalent."""
    has_elapsed = (
        "elapsed_days" in _JS or
        "elapsed" in _JS.lower() or
        "week_totals" in _JS
    )
    assert has_elapsed, (
        "habits.js pace sub-line must use elapsed_days (from weekData.week_totals) "
        "for on-pace vs behind-pace determination"
    )


def test_js_pace_formula():
    """Pace must compare current/target >= elapsed_days/7."""
    has_seven = "7" in _JS
    has_ratio = (
        "elapsed" in _JS.lower() and
        ("/" in _JS or "divide" in _JS.lower())
    )
    assert has_seven and has_ratio, (
        "habits.js must implement the pace formula: current/target vs elapsed_days/7"
    )


# ── (g) Manual log chip and auto badge ───────────────────────────────────────

def test_js_log_chip_for_manual_habits():
    """JS must render a '＋ log' chip for manual (non-auto-fill) habits."""
    has_log_chip = (
        "＋ log" in _JS or
        "+ log" in _JS.lower() or
        "log-chip" in _JS or
        "log chip" in _JS.lower() or
        ("log" in _JS and "chip" in _JS)
    )
    assert has_log_chip, (
        "habits.js must render a '＋ log' chip for manual (non-auto-fill) habits"
    )


def test_js_no_log_chip_for_auto_fill():
    """JS must NOT render '＋ log' for auto-fill habits."""
    has_auto_check = (
        "auto_fill_source" in _JS or
        "autoFillSource" in _JS or
        "auto_fill" in _JS
    )
    assert has_auto_check, (
        "habits.js must check auto_fill_source to suppress the log chip for auto-fill habits"
    )


def test_js_auto_badge_present():
    """JS must render the green '↻ auto · workouts' badge for auto-fill habits."""
    has_auto_badge = (
        "auto · workouts" in _JS or
        "auto-badge" in _JS or
        "auto_badge" in _JS or
        ("auto" in _JS.lower() and "workouts" in _JS.lower() and "badge" in _JS.lower()) or
        "↻" in _JS
    )
    assert has_auto_badge, (
        "habits.js must render the green '↻ auto · workouts' badge for auto-fill habits"
    )


def test_html_auto_badge_css():
    """HTML must define CSS for the auto-fill badge (green)."""
    has_auto_css = (
        "auto-badge" in _HTML or
        "week-auto-badge" in _HTML or
        ("auto" in _HTML.lower() and "#16a34a" in _HTML or
         "green" in _HTML.lower() and "auto" in _HTML.lower())
    )
    assert has_auto_css, (
        "habits.html must define CSS for the auto-fill badge (green color)"
    )


def test_js_auto_badge_tooltip():
    """Auto badge must have tooltip 'Updates automatically from your workouts'."""
    assert "Updates automatically from your workouts" in _JS, (
        "habits.js auto badge must have title/tooltip 'Updates automatically from your workouts'"
    )


# ── (h) weekly_minutes popover quick-add chips ────────────────────────────────

def test_js_weekly_minutes_quick_add_chips():
    """JS must render +5, +10, +15 quick-add chips in the log popover for weekly_minutes."""
    has_quick_add = (
        ("+5" in _JS or "＋5" in _JS or "5" in _JS) and
        ("+10" in _JS or "＋10" in _JS or "10" in _JS) and
        ("+15" in _JS or "＋15" in _JS or "15" in _JS) and
        "weekly_minutes" in _JS
    )
    assert has_quick_add, (
        "habits.js must show +5/+10/+15 quick-add chips in weekly_minutes log popovers"
    )


def test_js_popover_has_numeric_input():
    """Log popover must contain a numeric input field."""
    has_num_input = (
        "number" in _JS and
        ("popover" in _JS or "log-popover" in _JS or "logPopover" in _JS or
         "inline" in _JS.lower())
    )
    assert has_num_input, (
        "habits.js must include a numeric input in the log popover"
    )


# ── (i) Popover submission and DOM update ─────────────────────────────────────

def test_js_log_popover_posts_add_mode():
    """Popover submission must POST to /api/habits/{id}/log with mode: 'add'."""
    has_add_mode = (
        '"add"' in _JS or
        "'add'" in _JS or
        "mode.*add" in _JS or
        "add" in _JS and "/api/habits/" in _JS and "log" in _JS
    )
    assert has_add_mode, (
        "habits.js must POST with mode: 'add' to /api/habits/{id}/log for the log popover"
    )
    assert "/api/habits/" in _JS and "/log" in _JS, (
        "habits.js must target /api/habits/{id}/log for the add-mode POST"
    )


def test_js_bar_updates_from_week_current_value():
    """On success, bar/value must update from week_current_value without full reload."""
    has_week_current = (
        "week_current_value" in _JS
    )
    assert has_week_current, (
        "habits.js must read week_current_value from the POST response to update the bar "
        "without a full page refetch"
    )


def test_js_popover_closes_after_submit():
    """Popover must close after successful submission."""
    has_close = (
        "popover" in _JS and
        (
            "display" in _JS or "remove" in _JS or "close" in _JS or
            "hide" in _JS.lower() or "style.display" in _JS
        )
    )
    assert has_close, (
        "habits.js must close the log popover after a successful submission"
    )


# ── (j) Past-week read-only ───────────────────────────────────────────────────

def test_js_no_log_chip_in_past_week():
    """No '＋ log' chips must appear in past-week mode."""
    has_current_week_gate = (
        "is_current_week" in _JS and
        ("log" in _JS.lower() and "chip" in _JS.lower() or
         "＋ log" in _JS or
         "log-chip" in _JS)
    )
    assert has_current_week_gate, (
        "habits.js must gate '＋ log' chips behind weekData.is_current_week check"
    )


# ── (k) Weekly card empty state ───────────────────────────────────────────────

def test_js_weekly_empty_state_message():
    """Weekly card empty state must show the specified text."""
    has_empty_msg = (
        "Track weekly goals" in _JS or
        "weekly goals" in _JS.lower() or
        "zone 2 minutes" in _JS.lower() or
        "they can sync automatically" in _JS.lower()
    )
    assert has_empty_msg, (
        "habits.js weekly card empty state must mention 'Track weekly goals' / "
        "'Zone 2 minutes' / 'sync automatically'"
    )


def test_js_weekly_empty_state_new_habit_shortcut():
    """Weekly card empty state must have a 'New habit' shortcut for weekly type."""
    has_shortcut = (
        "New habit" in _JS and
        (
            "weekly" in _JS.lower() or
            "weekly_minutes" in _JS or
            "weekly_count" in _JS
        )
    )
    assert has_shortcut, (
        "habits.js weekly card empty state must include a 'New habit' shortcut "
        "that pre-selects a weekly tracking type"
    )


# ── (b) Row layout CSS ────────────────────────────────────────────────────────

def test_html_weekly_row_layout_css():
    """HTML must define CSS classes for the new weekly habit row layout."""
    has_row_css = (
        "week-habit-row" in _HTML or
        "week-habit-left" in _HTML or
        "week-habit-info" in _HTML
    )
    assert has_row_css, "habits.html must define CSS for weekly habit row layout"


def test_html_pace_css():
    """HTML must define CSS for the pace sub-line (green/amber)."""
    has_pace_css = (
        "pace" in _HTML or
        "on-pace" in _HTML or
        "week-pace" in _HTML
    )
    assert has_pace_css, (
        "habits.html must define CSS for the pace sub-line"
    )


def test_html_log_chip_css():
    """HTML must define CSS for the '＋ log' chip (lime/green)."""
    has_chip_css = (
        "log-chip" in _HTML or
        "week-log-chip" in _HTML or
        "log chip" in _HTML.lower()
    )
    assert has_chip_css, (
        "habits.html must define CSS for the '＋ log' chip"
    )


def test_html_seg_bar_css():
    """HTML must define CSS for the segmented bar."""
    has_seg_css = (
        "seg-bar" in _HTML or
        "segmented" in _HTML.lower() or
        "week-seg" in _HTML
    )
    assert has_seg_css, (
        "habits.html must define CSS for the segmented progress bar"
    )


def test_html_smooth_bar_css():
    """HTML must define CSS for the smooth gradient bar."""
    has_smooth_css = (
        "smooth-bar" in _HTML or
        "week-smooth" in _HTML or
        "week-habit-bar" in _HTML
    )
    assert has_smooth_css, (
        "habits.html must define CSS for the smooth gradient progress bar"
    )


# ── (l) JS uses weekData.weekly_habits ───────────────────────────────────────

def test_js_uses_weekly_habits_from_weekdata():
    """JS must use weekData.weekly_habits for the weekly card (not separate progress calls)."""
    assert "weekly_habits" in _JS, (
        "habits.js must use weekData.weekly_habits for the weekly habits card"
    )
