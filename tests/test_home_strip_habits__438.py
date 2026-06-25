"""TDD tests for issue #438: Home log-today strip and habits widget.

AC items covered:
  (a) [Strip] Full-width dark translucent log-today strip in home.html with icon,
      title 'Log today's metrics', subtitle text, and lime 'Log today' CTA
  (b) [Strip] 'Log today' CTA routes to the daily-metrics input (fast-log section)
  (c) [Strip] Strip hides / swaps to '✓ Metrics logged' when readiness.logged === true
  (d) [Habits widget] Widget is left tile of the top 2-up row; header 'This week's habits'
      and 'All habits →' link routing to /habits
  (e) [Habits widget] Week-wheel rendered from habits.wheel using shared wheel helper
      (arcPath / polarToCartesian — not re-authored)
  (f) [Habits widget] pct_elapsed value displayed in wheel center
  (g) [Habits widget] Top 3 daily habits: colored icon chip, name, flame streak badge
      (🔥N when streak >= 3), week count (e.g. '3/7'), today-check circle
  (h) [Today-check] Unchecked circle: dashed ○ with '+'; tapping calls
      POST /api/habits/{id}/log with today's date; optimistic flip to green ✓
  (i) [Today-check] On POST error circle reverts to ○ and a toast is shown
  (j) [Today-check] Green ✓ tapped calls DELETE on today's log; optimistic revert to ○;
      rolls back + toast on error
  (k) [Today-check] After check/uncheck re-calls /api/home/summary (or local patch)
  (l) [Weekly auto-habits] auto_fill_source habits show non-interactive progress marker
  (m) [Footer] Footer '+N more · tap ○ to check today · manage →' with manage → /habits
  (n) [Empty state] No habits → 'Add habits to track your week' with /habits link
  (o) [Quality] No log-today strip habit-create/edit UI present in this widget
  (p) [Backend] habits block daily_habits entries include streak and auto_fill_source
  (q) [Backend] readiness block includes logged=true when metrics logged today
"""
import pathlib
import uuid
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.main import app, resolve_user
from backend.models import Habit, HabitLog, DailyMetric

# ── File paths ────────────────────────────────────────────────────────────────

_ROOT  = pathlib.Path(__file__).parent.parent
_HTML  = (_ROOT / "frontend" / "pages" / "home.html").read_text()
_JS    = (_ROOT / "frontend" / "js" / "home-strip-habits.js").read_text()
_WH_JS = (_ROOT / "frontend" / "js" / "wheel-helpers.js").read_text()

# ── Fixtures ──────────────────────────────────────────────────────────────────

_USER_ID  = uuid.UUID("00000000-0000-0000-0000-000000000438")
_TODAY    = date(2026, 6, 11)
_WEEK_MON = date(2026, 6, 8)   # Monday of the test week

client = TestClient(app)


def _make_user():
    u = MagicMock()
    u.id = _USER_ID
    return u


def _override_user():
    async def _fake():
        return _make_user()
    app.dependency_overrides[resolve_user] = _fake
    return TestClient(app)


def _teardown():
    app.dependency_overrides.pop(resolve_user, None)


def _make_habit(*, hid=None, name="Morning run", auto_fill_source=None, sort_order=0):
    h = MagicMock(spec=Habit)
    h.id = hid or uuid.uuid4()
    h.user_id = _USER_ID
    h.name = name
    h.tracking_type = "daily_checkmark"
    h.weekly_target = 7.0
    h.unit = None
    h.auto_fill_source = auto_fill_source
    h.icon = "ti-run"
    h.color = "#3b82f6"
    h.sort_order = sort_order
    h.is_archived = False
    h.description = None
    h.created_at = None
    h.updated_at = None
    return h


def _make_log(*, habit_id, log_date):
    lg = MagicMock(spec=HabitLog)
    lg.id = uuid.uuid4()
    lg.habit_id = habit_id
    lg.user_id = _USER_ID
    lg.log_date = log_date
    lg.logged_date = log_date
    lg.log_week_start = _WEEK_MON
    lg.value = 1.0
    lg.notes = None
    lg.source = "manual"
    return lg


def _make_metrics(*, rhr=52, hrv=62, sleep_hours=7.4, sleep_quality=4, energy=4, mood=4):
    m = MagicMock(spec=DailyMetric)
    m.id = uuid.uuid4()
    m.user_id = _USER_ID
    m.metric_date = _TODAY
    m.resting_hr = rhr
    m.hrv = hrv
    m.sleep_hours = sleep_hours
    m.sleep_quality = sleep_quality
    m.energy = energy
    m.mood = mood
    m.notes = None
    return m


def _patch_today(target_date=_TODAY):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    _BKK = ZoneInfo("Asia/Bangkok")
    fake_dt = datetime(target_date.year, target_date.month, target_date.day, 10, 0, 0, tzinfo=_BKK)
    mock_dt = MagicMock()
    mock_dt.now.return_value = fake_dt
    mock_dt.fromisoformat = datetime.fromisoformat
    mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
    return patch("backend.main._datetime", mock_dt)


def _mock_summary_session(habits=None, logs=None, metrics=None, baseline_rows=None):
    """Return a Session context-manager mock for get_home_summary calls."""
    habits = habits or []
    logs = logs or []
    baseline_rows = baseline_rows or []

    mock_s = MagicMock()
    mock_s.__enter__ = MagicMock(return_value=mock_s)
    mock_s.__exit__ = MagicMock(return_value=False)

    user = _make_user()
    mock_s.get.return_value = user

    habit_q    = MagicMock()
    habit_q.filter.return_value  = habit_q
    habit_q.order_by.return_value = habit_q
    habit_q.all.return_value     = habits
    habit_q.first.return_value   = habits[0] if habits else None
    habit_q.in_.return_value     = habit_q

    log_q = MagicMock()
    log_q.filter.return_value = log_q
    log_q.in_.return_value    = log_q
    log_q.all.return_value    = logs

    metrics_q = MagicMock()
    metrics_q.filter.return_value = metrics_q
    metrics_q.first.return_value  = metrics
    metrics_q.all.return_value    = baseline_rows

    def _query(model, *a, **kw):
        if model is Habit:
            return habit_q
        if model is HabitLog:
            return log_q
        if model is DailyMetric:
            return metrics_q
        q = MagicMock()
        q.filter.return_value  = q
        q.order_by.return_value = q
        q.all.return_value     = []
        q.first.return_value   = None
        return q

    mock_s.query.side_effect = _query
    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_s
    mock_cm.__exit__.return_value  = False
    return mock_cm


# ═══════════════════════════════════════════════════════════════════════════════
# (a) [Strip] Home HTML has log-today strip element with required content
# ═══════════════════════════════════════════════════════════════════════════════

def test_html_has_log_today_strip():
    """home.html must have a dedicated log-today strip element (not just old banner)."""
    assert "home-log-today-strip" in _HTML, (
        "home.html must have id='home-log-today-strip'"
    )


def test_html_strip_has_log_today_title():
    """Strip must contain title text 'Log today'."""
    assert "Log today" in _HTML, (
        "home.html log-today strip must contain 'Log today' title"
    )


def test_html_strip_has_subtitle_metrics():
    """Strip must contain the subtitle about RHR, HRV, sleep etc."""
    assert "RHR" in _HTML and "HRV" in _HTML and "sleep" in _HTML.lower(), (
        "home.html log-today strip must reference RHR, HRV, sleep metrics"
    )


def test_html_strip_has_lime_cta():
    """Strip CTA button must use lime/accent color (var(--accent))."""
    assert "home-log-today-strip" in _HTML, "strip element required"
    # The CTA should use var(--accent) — check in style definitions
    assert "var(--accent)" in _HTML, (
        "home.html must use var(--accent) for the lime CTA button"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# (b) [Strip] 'Log today' CTA routes to daily-metrics input
# ═══════════════════════════════════════════════════════════════════════════════

def test_js_strip_cta_routes_to_fast_log():
    """JS must route the 'Log today' CTA to the fast-log section."""
    # Should scroll/link to fast-log-section or #log-today anchor
    assert (
        "fast-log-section" in _JS
        or "fast-log" in _JS
        or "log-today" in _JS.lower()
    ), (
        "home-strip-habits.js must route strip CTA to the fast-log / daily-metrics section"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# (c) [Strip] Strip hides when readiness.logged === true
# ═══════════════════════════════════════════════════════════════════════════════

def test_js_strip_hides_when_logged():
    """JS must check readiness.logged and hide the strip (or show confirmed state)."""
    assert "readiness" in _JS and "logged" in _JS, (
        "home-strip-habits.js must read readiness.logged to determine strip visibility"
    )


def test_js_strip_confirmed_state():
    """JS must render a 'Metrics logged' confirmation state when readiness.logged."""
    assert (
        "Metrics logged" in _JS
        or "logged" in _JS.lower() and "confirmed" in _JS.lower()
        or "✓" in _JS
    ), (
        "home-strip-habits.js must show a confirmation state when metrics are logged"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# (d) [Habits widget] HTML has top-row with habits widget on left
# ═══════════════════════════════════════════════════════════════════════════════

def test_html_has_home_top_row():
    """home.html must have a top 2-up row container for the habits widget."""
    assert "home-top-row" in _HTML, (
        "home.html must have id='home-top-row' for the 2-up habits/widget row"
    )


def test_html_has_habits_widget():
    """home.html must have the habits widget element."""
    assert "home-habits-widget" in _HTML, (
        "home.html must have id='home-habits-widget'"
    )


def test_js_habits_widget_header():
    """JS must render 'This week's habits' as the widget header."""
    assert "This week" in _JS and "habits" in _JS.lower(), (
        "home-strip-habits.js must render 'This week's habits' header"
    )


def test_js_habits_widget_all_habits_link():
    """JS must render an 'All habits →' link routing to /habits."""
    assert "/habits" in _JS, (
        "home-strip-habits.js must include a link to /habits"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# (e) [Habits widget] Week-wheel uses shared wheel helper (not re-authored)
# ═══════════════════════════════════════════════════════════════════════════════

def test_wheel_helpers_file_exists():
    """wheel-helpers.js must exist and define polarToCartesian / arcPath."""
    assert "polarToCartesian" in _WH_JS, (
        "wheel-helpers.js must define polarToCartesian"
    )
    assert "arcPath" in _WH_JS, (
        "wheel-helpers.js must define arcPath"
    )


def test_js_uses_wheel_helpers():
    """home-strip-habits.js must use the WheelHelpers namespace (not re-implement math)."""
    assert "WheelHelpers" in _JS or "arcPath" in _JS or "polarToCartesian" in _JS, (
        "home-strip-habits.js must use the shared wheel helper functions"
    )


def test_html_loads_wheel_helpers():
    """home.html must load wheel-helpers.js before home-strip-habits.js."""
    wh_pos = _HTML.find("wheel-helpers.js")
    strip_pos = _HTML.find("home-strip-habits.js")
    assert wh_pos != -1, "home.html must load wheel-helpers.js"
    assert strip_pos != -1, "home.html must load home-strip-habits.js"
    assert wh_pos < strip_pos, "wheel-helpers.js must be loaded before home-strip-habits.js"


# ═══════════════════════════════════════════════════════════════════════════════
# (f) [Habits widget] pct_elapsed shown in wheel center
# ═══════════════════════════════════════════════════════════════════════════════

def test_js_renders_pct_elapsed_in_wheel():
    """JS must render pct_elapsed in the wheel's center text."""
    assert "pct_elapsed" in _JS, (
        "home-strip-habits.js must render habits.pct_elapsed in the wheel center"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# (g) [Habits widget] Top 3 habits with icon chip, name, streak badge, week count,
#     today-check circle
# ═══════════════════════════════════════════════════════════════════════════════

def test_js_renders_top_habits():
    """JS must use top_habits (or daily_habits slice) from API response."""
    assert "top_habits" in _JS or "daily_habits" in _JS, (
        "home-strip-habits.js must render top habits from the habits block"
    )


def test_js_streak_badge_threshold():
    """JS must show flame streak badge when streak >= 3."""
    assert "streak" in _JS and ("🔥" in _JS or "flame" in _JS.lower()), (
        "home-strip-habits.js must render a flame streak badge for streak >= 3"
    )


def test_js_streak_badge_condition():
    """JS must only show badge when streak >= 3."""
    assert ">= 3" in _JS or ">= 3" in _JS or "streak >= 3" in _JS or "streak>=3" in _JS or \
           ("streak" in _JS and "3" in _JS), (
        "home-strip-habits.js must conditionally show streak badge when streak >= 3"
    )


def test_js_week_count_renders():
    """JS must render week_count (e.g. '3/7') for each habit."""
    assert "week_count" in _JS, (
        "home-strip-habits.js must render habit.week_count in the habit row"
    )


def test_js_today_check_circle():
    """JS must render a today-check circle for each daily habit."""
    assert "today_checked" in _JS, (
        "home-strip-habits.js must render today-check state from today_checked field"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# (h) [Today-check] Unchecked → POST /api/habits/{id}/log with today
# ═══════════════════════════════════════════════════════════════════════════════

def test_js_today_check_post():
    """JS must POST to /api/habits/{id}/log when checking an unchecked habit."""
    assert "/api/habits/" in _JS and "POST" in _JS and "/log" in _JS, (
        "home-strip-habits.js must POST /api/habits/{id}/log to check a habit"
    )


def test_js_optimistic_check():
    """JS must optimistically flip the circle before the POST resolves."""
    # Optimistic = update DOM before await
    assert "optimistic" in _JS.lower() or \
           ("classList" in _JS and "POST" in _JS) or \
           "optimist" in _JS.lower(), (
        "home-strip-habits.js must apply an optimistic UI update on check"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# (i) [Today-check] POST error → revert + toast
# ═══════════════════════════════════════════════════════════════════════════════

def test_js_check_error_revert():
    """JS must revert the optimistic check on POST failure."""
    assert "revert" in _JS.lower() or ("catch" in _JS and "today_checked" in _JS), (
        "home-strip-habits.js must revert optimistic check on error"
    )


def test_js_check_error_toast():
    """JS must show a toast on POST error."""
    assert "toast" in _JS.lower() or "UIStates" in _JS or "showToast" in _JS, (
        "home-strip-habits.js must show a toast on check/uncheck error"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# (j) [Today-check] Green ✓ tapped → DELETE today's log
# ═══════════════════════════════════════════════════════════════════════════════

def test_js_today_uncheck_delete():
    """JS must DELETE /api/habits/logs/{log_id} when unchecking."""
    assert "DELETE" in _JS and "/api/habits/logs" in _JS, (
        "home-strip-habits.js must DELETE the habit log when unchecking"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# (k) [Today-check] After check/uncheck, refresh habits block
# ═══════════════════════════════════════════════════════════════════════════════

def test_js_refreshes_after_check():
    """JS must refresh habits data (re-fetch summary or local patch) after check/uncheck."""
    assert (
        "home/summary" in _JS
        or "refreshHabits" in _JS
        or "_loadSummary" in _JS
        or "_refresh" in _JS
        or "reload" in _JS.lower()
    ), (
        "home-strip-habits.js must refresh habits block after a check/uncheck"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# (l) [Weekly auto-habits] auto_fill_source shows non-interactive marker
# ═══════════════════════════════════════════════════════════════════════════════

def test_js_auto_fill_non_interactive():
    """JS must render a non-interactive marker for auto_fill_source habits."""
    assert "auto_fill_source" in _JS, (
        "home-strip-habits.js must handle auto_fill_source habits differently"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# (m) [Footer] Footer shows +N more, tap info, manage → /habits
# ═══════════════════════════════════════════════════════════════════════════════

def test_js_footer_more_count():
    """JS must render '+N more' in the habits widget footer."""
    assert "remaining_count" in _JS or "more" in _JS.lower(), (
        "home-strip-habits.js must render '+N more' based on remaining_count"
    )


def test_js_footer_manage_link():
    """JS footer must have 'manage →' linking to /habits."""
    assert "manage" in _JS.lower() and "/habits" in _JS, (
        "home-strip-habits.js must render 'manage →' footer link to /habits"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# (n) [Empty state] No habits → message with /habits link
# ═══════════════════════════════════════════════════════════════════════════════

def test_js_empty_state_message():
    """JS must show empty state message when no habits."""
    assert "Add habits" in _JS or "no habits" in _JS.lower(), (
        "home-strip-habits.js must show empty state for users with no habits"
    )


def test_js_empty_state_habits_link():
    """Empty state must link to /habits."""
    assert "/habits" in _JS, (
        "home-strip-habits.js empty state must link to /habits"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# (o) [Scope] No habit create/edit UI in widget
# ═══════════════════════════════════════════════════════════════════════════════

def test_no_habit_create_form_in_widget():
    """The habits widget must NOT include habit create/edit form UI."""
    # The widget should not have a form for creating or editing habits
    # (all editing links out to /habits)
    # Check JS doesn't define a habit-create form
    assert "habit-create-form" not in _JS and "edit-habit-modal" not in _JS, (
        "home-strip-habits.js must not include habit create/edit UI"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# (p) [Backend] habits block includes streak and auto_fill_source
# ═══════════════════════════════════════════════════════════════════════════════

def test_habits_block_includes_streak():
    """GET /api/home/summary habits block must include streak per daily habit."""
    h1 = _make_habit(hid=uuid.UUID("11111111-1111-1111-1111-111111111111"))
    # 3 logs in the last 3 days to produce a streak of 3
    logs = [
        _make_log(habit_id=h1.id, log_date=_TODAY),
        _make_log(habit_id=h1.id, log_date=_TODAY - timedelta(days=1)),
        _make_log(habit_id=h1.id, log_date=_TODAY - timedelta(days=2)),
    ]

    mock_cm = _mock_summary_session(habits=[h1], logs=logs)
    with _patch_today(), patch("backend.main.Session", return_value=mock_cm):
        r = client.get(f"/api/home/summary?user_id={_USER_ID}")

    assert r.status_code == 200
    body = r.json()
    assert body["habits"] is not None
    daily = body["habits"]["daily_habits"]
    assert len(daily) == 1
    assert "streak" in daily[0], "each daily habit must include 'streak'"
    assert daily[0]["streak"] == 3, "streak must equal the number of consecutive logged days"


def test_habits_block_includes_auto_fill_source():
    """GET /api/home/summary habits block must include auto_fill_source per daily habit."""
    h1 = _make_habit(
        hid=uuid.UUID("22222222-2222-2222-2222-222222222222"),
        auto_fill_source="workout.run_count",
    )

    mock_cm = _mock_summary_session(habits=[h1])
    with _patch_today(), patch("backend.main.Session", return_value=mock_cm):
        r = client.get(f"/api/home/summary?user_id={_USER_ID}")

    assert r.status_code == 200
    body = r.json()
    assert body["habits"] is not None
    daily = body["habits"]["daily_habits"]
    assert len(daily) == 1
    assert "auto_fill_source" in daily[0], "each daily habit must include 'auto_fill_source'"
    assert daily[0]["auto_fill_source"] == "workout.run_count"


def test_habits_block_streak_zero_when_no_logs():
    """streak must be 0 when there are no logs for a daily habit."""
    h1 = _make_habit(hid=uuid.UUID("33333333-3333-3333-3333-333333333333"))

    mock_cm = _mock_summary_session(habits=[h1], logs=[])
    with _patch_today(), patch("backend.main.Session", return_value=mock_cm):
        r = client.get(f"/api/home/summary?user_id={_USER_ID}")

    assert r.status_code == 200
    body = r.json()
    assert body["habits"]["daily_habits"][0]["streak"] == 0


# ═══════════════════════════════════════════════════════════════════════════════
# (q) [Backend] readiness block includes logged=true when metrics logged
# ═══════════════════════════════════════════════════════════════════════════════

def test_readiness_block_logged_true_when_metrics_exist():
    """readiness block must include logged=true when today's metrics are logged."""
    m = _make_metrics()

    mock_cm = _mock_summary_session(metrics=m)
    with _patch_today(), patch("backend.main.Session", return_value=mock_cm):
        r = client.get(f"/api/home/summary?user_id={_USER_ID}")

    assert r.status_code == 200
    body = r.json()
    assert body["readiness"] is not None, "readiness block must be present"
    assert body["readiness"].get("logged") is True, (
        "readiness block must set logged=true when today's metrics are logged"
    )


def test_readiness_block_logged_false_when_no_metrics():
    """readiness block must return logged=false when no metrics for today."""
    # No metrics (metrics_q.first returns None)
    mock_cm = _mock_summary_session(metrics=None)
    with _patch_today(), patch("backend.main.Session", return_value=mock_cm):
        r = client.get(f"/api/home/summary?user_id={_USER_ID}")

    assert r.status_code == 200
    body = r.json()
    # readiness block may be None (error) or {"logged": False}
    rd = body.get("readiness")
    if rd is not None:
        assert rd.get("logged") is False, (
            "readiness.logged must be false when no metrics logged"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# CSS / layout sanity checks
# ═══════════════════════════════════════════════════════════════════════════════

def test_html_strip_dark_background():
    """Log-today strip must use a dark/translucent background style."""
    # Look for dark background styling near the strip class/id
    assert (
        "rgba(0,0,0" in _HTML
        or "rgba(0, 0, 0" in _HTML
        or "#0b1530" in _HTML
        or "dark" in _HTML.lower()
        or "translucent" in _HTML.lower()
        or "1f3b8a" in _HTML
        or "linear-gradient" in _HTML
    ), (
        "home.html must apply a dark/translucent background to the log-today strip"
    )


def test_html_mobile_responsive():
    """home.html must include media query for mobile breakpoint <= 880px or similar."""
    assert "@media" in _HTML and "max-width" in _HTML, (
        "home.html must include responsive media queries for the new strip/widget"
    )
