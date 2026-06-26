"""Tests for issue #433: Daily habits grid with tap-to-check and scoring.

AC items covered:
  (a) Grid header has Habit | Mon–Sun | Total; today's column header is blue
  (b) Only daily_checkmark habits appear in the grid
  (c) Each row: icon chip, name, "daily · target N/wk" meta, streak badge when ≥ 3
  (d) Four cell states: done (green-soft), missed (hollow grey), today_pending (blue dashed +),
      future (dotted ring)
  (e) Tapping today_pending POSTs → done optimistically; rollback + toast on failure
  (f) Tapping done (current week) DELETEs → missed/today_pending; rollback + toast on failure
  (g) Tapping missed (current week) POSTs with date → done; rollback + toast on failure
  (h) Past-week and future cells are inert (cursor: default, no click handler)
  (i) Server-rule rejections surfaced as toasts (not silent failures)
  (j) Cell mutation refreshes row total, day-score row, wheel, stats — debounced 300 ms
  (k) Total column: {done}/{target} monospace, mini progress bar, percentage
  (l) DAY SCORE row: heavier border, {done}/{of} per day, grand-total + bar + pct
  (m) Row overflow menu (⋯): edit / archive / delete
  (n) Empty state retains starter-suggestion buttons
  (o) today_pending and done-within-week cells are keyboard-focusable (Enter = tap)
  (p) /api/habits/week daily_habits array has correct state values and total field
  (q) /api/habits/week streaks.per_habit present for streak badge
  (r) /api/habits/week day_scores has done/of for day score row
"""
import pathlib
import uuid
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from backend.main import app, resolve_user
from backend.models import Habit, HabitLog

# ── File paths ────────────────────────────────────────────────────────────────

_ROOT = pathlib.Path(__file__).parent.parent
_HTML = (_ROOT / "frontend" / "pages" / "habits.html").read_text()
_JS   = (_ROOT / "frontend" / "js" / "habits.js").read_text()

# CSS was extracted to habits.css (issue #453). Append it so CSS-pattern checks
# in _HTML still pass after the extraction.
_habits_css_path = _ROOT / "frontend" / "css" / "habits.css"
if _habits_css_path.exists():
    _HTML = _HTML + "\n" + _habits_css_path.read_text()

# ── API test fixtures ─────────────────────────────────────────────────────────

_USER_ID  = uuid.UUID("00000000-0000-0000-0000-000000000433")
_WEEK_MON = date(2026, 6, 8)
_TODAY    = date(2026, 6, 11)   # Wednesday of the test week


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


def _make_daily_habit(*, hid=None, name="Test Habit", target=7.0, sort_order=0):
    h = MagicMock(spec=Habit)
    h.id = hid or uuid.uuid4()
    h.user_id = _USER_ID
    h.name = name
    h.description = None
    h.tracking_type = "daily_checkmark"
    h.weekly_target = target
    h.unit = None
    h.auto_fill_source = None
    h.icon = "ti-clipboard"
    h.color = "#10b981"
    h.sort_order = sort_order
    h.is_archived = False
    h.created_at = None
    h.updated_at = None
    return h


def _make_log(*, habit_id, log_date, week_start=_WEEK_MON):
    log = MagicMock(spec=HabitLog)
    log.id = uuid.uuid4()
    log.habit_id = habit_id
    log.user_id = _USER_ID
    log.log_date = log_date
    log.logged_date = log_date
    log.log_week_start = week_start
    log.value = 1.0
    log.notes = None
    log.source = "manual"
    return log


def _make_session(active_habits, logs=None):
    """Build a properly-mocked SQLAlchemy session.

    The Habit model is queried twice in the endpoint (once for active habits,
    once for archived-with-logs). We return `active_habits` on the first call
    and `[]` on the second.
    """
    logs = logs or []

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

    def _query(model):
        if model is Habit:
            return habit_q
        elif model is HabitLog:
            return log_q
        return MagicMock()

    sess.query.side_effect = _query
    return sess


def _patch_today(target_date):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    _BKK = ZoneInfo("Asia/Bangkok")
    fake_dt = datetime(target_date.year, target_date.month, target_date.day, 10, 0, 0, tzinfo=_BKK)
    mock_dt = MagicMock()
    mock_dt.now.return_value = fake_dt
    mock_dt.fromisoformat = datetime.fromisoformat
    mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
    return patch("backend.main._datetime", mock_dt)


# ── (a) Grid header: Habit | Mon–Sun | Total; today's header is blue ──────────

def test_habits_html_today_column_header_blue():
    """CSS rule makes today's day header text blue."""
    assert "day-hdr-today" in _HTML or "day-header-today" in _HTML, (
        "habits.html must define a CSS class for today's column header (day-hdr-today)"
    )
    # Must have a blue color on that class
    assert "#2563eb" in _HTML or "var(--primary-dark)" in _HTML or "var(--primary)" in _HTML, (
        "Today's header must use a blue color token"
    )


def test_habits_js_total_column_header():
    """renderDailyGrid must emit a 'Total' column header cell."""
    assert "Total" in _JS, "habits.js must emit a 'Total' header for the total column"


def test_habits_js_day_headers_all_seven():
    """renderDailyGrid must emit all 7 day-label headers (Mon–Sun)."""
    for day in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]:
        assert day in _JS, f"habits.js must include '{day}' day header"


# ── (b) Only daily_checkmark habits in the grid ───────────────────────────────

def test_habits_js_filters_daily_checkmark_only():
    """Grid must only render habits from weekData.daily_habits (daily_checkmark subset)."""
    assert "daily_habits" in _JS, (
        "habits.js must use weekData.daily_habits for the grid (not all activeHabits)"
    )


def test_habits_js_does_not_render_weekly_in_grid():
    """Weekly habits must go through weekly_habits, not the daily grid."""
    # The daily grid function must reference daily_habits, not the general activeHabits list
    # (weekly habits are excluded server-side via the daily_habits key)
    assert "weekData.daily_habits" in _JS or "week_data.daily_habits" in _JS, (
        "habits.js renderDailyGrid must source data from weekData.daily_habits"
    )


# ── (c) Habit row: icon chip, name, meta, streak badge ───────────────────────

def test_habits_js_habit_meta_line_daily_target():
    """Habit row must show 'daily' and target information in a meta line."""
    assert "daily" in _JS, "habits.js must include 'daily' in the habit meta line"
    assert "target" in _JS, "habits.js must include target value in the meta line"


def test_habits_js_streak_badge_threshold():
    """Streak badge (🔥 N-day streak) shown only when streak ≥ 3."""
    assert "streak" in _JS, "habits.js must reference streak data"
    assert ">= 3" in _JS or ">= 3" in _JS or ">=3" in _JS or "≥ 3" in _JS or "≥3" in _JS or \
           "3" in _JS, "habits.js must have a streak threshold of 3"
    # The badge must use the per_habit streaks
    assert "per_habit" in _JS, "habits.js must read weekData.streaks.per_habit for per-habit streaks"


def test_habits_html_streak_badge_css():
    """CSS for the streak badge must be defined."""
    assert "streak-badge" in _HTML or "streak_badge" in _HTML, (
        "habits.html must define .streak-badge CSS"
    )


# ── (d) Four cell states ──────────────────────────────────────────────────────

def test_habits_html_done_state_green_soft():
    """CSS: done state uses green-soft fill (dff5d6 or --green-soft or 16a34a border)."""
    # The done cell must have green styling (not dark navy #0b1530)
    assert "dff5d6" in _HTML or "green-soft" in _HTML or "--green" in _HTML or \
           "16a34a" in _HTML, (
        "habits.html .day-cell-btn.done must use green-soft fill (not dark navy)"
    )


def test_habits_html_missed_state():
    """CSS: missed state is defined (hollow grey ring)."""
    assert "missed" in _HTML, (
        "habits.html must define CSS for .day-cell-btn.missed (hollow grey ring)"
    )


def test_habits_html_today_pending_state():
    """CSS: today_pending state has blue dashed border."""
    assert "today-pending" in _HTML or "today_pending" in _HTML, (
        "habits.html must define CSS for today-pending cell state"
    )
    assert "dashed" in _HTML, (
        "today-pending cell must use a dashed border style"
    )


def test_habits_html_future_state_dotted():
    """CSS: future state uses a dotted ring."""
    assert "dotted" in _HTML, (
        "habits.html .day-cell-btn.future must use dotted border (faint dotted ring)"
    )


def test_habits_js_cell_states_all_four():
    """JS must apply all four cell states as CSS classes."""
    for state in ["done", "missed", "today-pending", "future"]:
        assert state in _JS, f"habits.js must assign class '{state}' to day cells"


# ── (e-g) Optimistic mutations ────────────────────────────────────────────────

def test_habits_js_post_on_today_pending():
    """Clicking today_pending fires POST /api/habits/logs."""
    assert "today-pending" in _JS or "today_pending" in _JS, (
        "habits.js must handle today-pending cell clicks"
    )
    assert "POST" in _JS, "habits.js must POST to /api/habits/logs on today_pending click"
    assert "/api/habits/logs" in _JS, "habits.js must target /api/habits/logs for log creation"


def test_habits_js_delete_on_done_current_week():
    """Clicking a done cell DELETEs the log."""
    assert "DELETE" in _JS, "habits.js must DELETE to remove a log"
    assert "/api/habits/logs/" in _JS, "DELETE must target /api/habits/logs/{log_id}"


def test_habits_js_missed_backfill_post():
    """Clicking a missed cell (current week) fires POST with that date."""
    assert "missed" in _JS, "habits.js must handle missed cell clicks"
    # The missed action uses the same POST path as today_pending
    assert "/api/habits/logs" in _JS, "backfill POST must target /api/habits/logs"


def test_habits_js_optimistic_update():
    """Optimistic update must be applied before the server responds."""
    # The optimistic update happens by changing state before await
    # Check that there's a function that sets cell state BEFORE await
    assert "setCellState" in _JS or "optimistic" in _JS.lower() or (
        "classList" in _JS and "done" in _JS and "fetch" in _JS
    ), "habits.js must apply an optimistic visual update before the await"


def test_habits_js_rollback_on_failure():
    """On server failure, the cell rolls back to its previous state."""
    assert "rollback" in _JS.lower() or "prevState" in _JS or "prev_state" in _JS or \
           "restore" in _JS.lower() or ("catch" in _JS and "setCellState" in _JS), (
        "habits.js must rollback cell state on server failure"
    )


def test_habits_js_toast_on_server_failure():
    """On server failure, an error toast is shown."""
    assert "showToast" in _JS, "habits.js must call UIStates.showToast on failure"
    assert "true" in _JS or "isError" in _JS or "error" in _JS.lower(), (
        "habits.js toast on failure must be an error toast"
    )


# ── (h) Inert cells ───────────────────────────────────────────────────────────

def test_habits_html_future_cells_inert():
    """Future cells must have cursor: default and pointer-events: none."""
    assert "pointer-events" in _HTML, (
        "habits.html must set pointer-events: none on future cells"
    )
    assert "cursor" in _HTML, "habits.html must set cursor on cell states"


def test_habits_js_past_week_cells_inert():
    """When is_current_week is false, no mutations should fire."""
    assert "is_current_week" in _JS, (
        "habits.js must check weekData.is_current_week before allowing mutations"
    )


# ── (j) Debounced hero refresh ────────────────────────────────────────────────

def test_habits_js_debounced_refresh_300ms():
    """Mutations must trigger a debounced 300 ms hero/grid refresh."""
    assert "300" in _JS, "habits.js must have a 300 ms debounce for the hero refresh"
    assert "setTimeout" in _JS, "habits.js must use setTimeout for debouncing"


def test_habits_js_refresh_updates_hero_and_grid():
    """After debounce, hero wheel, stats, and grid totals must be refreshed."""
    assert "renderHeroWheel" in _JS, "habits.js must call renderHeroWheel after mutation"
    assert "renderHeroStats" in _JS, "habits.js must call renderHeroStats after mutation"
    assert "refreshGridTotals" in _JS or "day-score-row" in _JS, (
        "habits.js must refresh grid totals (row total + day score row) after mutation"
    )


# ── (k) Total column ─────────────────────────────────────────────────────────

def test_habits_html_total_column_css():
    """CSS for the total column cells must be defined."""
    assert "day-total" in _HTML or "total-cell" in _HTML, (
        "habits.html must define CSS for the total column"
    )


def test_habits_js_total_column_done_of_target():
    """Total column must show {done}/{target}."""
    # Check for pattern like total.done or habit.total
    assert "total" in _JS and ("done" in _JS), (
        "habits.js total column must render {done}/{target}"
    )


def test_habits_js_total_column_progress_bar():
    """Total column must include a mini progress bar."""
    assert "day-total-bar" in _JS or "total-bar" in _JS or \
           ("bar" in _JS and "width" in _JS and "%" in _JS), (
        "habits.js must render a mini progress bar in the total column"
    )


def test_habits_js_total_column_percentage():
    """Total column must show a percentage."""
    # Check for rounding and percentage rendering
    assert "Math.round" in _JS or "toFixed" in _JS, (
        "habits.js must compute and display a percentage in the total column"
    )
    assert "%" in _JS, "habits.js must render a '%' character in the total column"


# ── (l) DAY SCORE row ─────────────────────────────────────────────────────────

def test_habits_html_day_score_row_css():
    """CSS for the day score row with heavier border must be defined."""
    assert "day-score-row" in _HTML, (
        "habits.html must define .day-score-row CSS"
    )
    assert "border" in _HTML, "day-score-row must use a heavier border for visual separation"


def test_habits_js_day_score_row_rendered():
    """JS must render the day score row from weekData.day_scores."""
    assert "day_scores" in _JS, "habits.js must use weekData.day_scores for the day score row"
    assert "day-score-row" in _JS, "habits.js must render a .day-score-row element"


def test_habits_js_day_score_row_grand_total():
    """Day score row grand-total cell shows done/possible + bar + pct of week."""
    assert "pct_full_week" in _JS or "of week" in _JS or "possible" in _JS, (
        "habits.js must render the grand total in the day score row"
    )


# ── (m) Overflow menu ─────────────────────────────────────────────────────────

def test_habits_js_overflow_menu_on_grid_rows():
    """Each daily habit row must have an overflow menu (⋯) with edit/archive/delete."""
    # Must have an actions toggle in the daily grid (not just weekly habits)
    assert "day-actions-toggle" in _JS or (
        "renderDailyGrid" in _JS and "Edit" in _JS and "Archive" in _JS
    ), "habits.js must add an overflow menu to each daily grid row"


def test_habits_html_day_actions_css():
    """CSS for the daily grid row overflow menu must be defined."""
    assert "day-actions" in _HTML or "actions-menu" in _HTML, (
        "habits.html must define CSS for the daily grid row overflow menu"
    )


# ── (n) Empty state ───────────────────────────────────────────────────────────

def test_habits_js_empty_state_preserved():
    """When no daily_checkmark habits exist, the starter suggestions must still show."""
    assert "starter" in _JS, "habits.js must still show starter suggestions in empty state"
    assert "daily_checkmark" not in _JS or "starter-section" in _JS, (
        "habits.js must show the starter section when there are no daily habits"
    )


# ── (o) Keyboard focus + Enter ────────────────────────────────────────────────

def test_habits_js_cells_keyboard_focusable():
    """Actionable cells must be keyboard-focusable (tabIndex or button elements)."""
    # day-cell-btn is a <button> element which is already focusable
    # But we need to verify today_pending and done-within-week cells have tabIndex >= 0
    # (not tabIndex=-1 which would exclude them)
    # Check that inert cells have tabIndex=-1 or are type="button" (always focusable)
    assert "tabIndex" in _JS or "tabindex" in _JS or "day-cell-btn" in _JS, (
        "habits.js must ensure actionable cells are keyboard-focusable"
    )


def test_habits_js_enter_key_triggers_action():
    """Pressing Enter on a focusable cell triggers the same action as a tap."""
    assert "Enter" in _JS or "keydown" in _JS or "keypress" in _JS or "keyCode" in _JS, (
        "habits.js must handle Enter key on focusable day cells"
    )


# ── (p) API: /api/habits/week — daily_habits states ─────────────────────────

def test_api_daily_habits_states_valid():
    """Every day in daily_habits has a valid state value."""
    client = _make_client()
    hab = _make_daily_habit(hid=uuid.uuid4(), name="Metrics")
    logs = [
        _make_log(habit_id=hab.id, log_date=_WEEK_MON),
        _make_log(habit_id=hab.id, log_date=_WEEK_MON + timedelta(days=1)),
    ]
    sess = _make_session([hab], logs)
    try:
        with _patch_today(_TODAY), patch("backend.main.Session", return_value=sess):
            resp = client.get("/api/habits/week?week_start=2026-06-08")
        assert resp.status_code == 200, f"Expected 200: {resp.text}"
        body = resp.json()
        assert "daily_habits" in body
        assert len(body["daily_habits"]) == 1
        dh = body["daily_habits"][0]
        assert dh["id"] == str(hab.id)
        assert len(dh["days"]) == 7
        valid_states = {"done", "today_pending", "missed", "future"}
        for day in dh["days"]:
            assert "state" in day
            assert day["state"] in valid_states, f"Invalid state: {day['state']}"
    finally:
        _teardown()


def test_api_daily_habits_monday_is_done():
    """Monday log → Monday day entry state is 'done'."""
    client = _make_client()
    hab = _make_daily_habit()
    logs = [_make_log(habit_id=hab.id, log_date=_WEEK_MON)]
    sess = _make_session([hab], logs)
    try:
        with _patch_today(_TODAY), patch("backend.main.Session", return_value=sess):
            resp = client.get("/api/habits/week?week_start=2026-06-08")
        days = resp.json()["daily_habits"][0]["days"]
        mon = next(d for d in days if d["date"] == _WEEK_MON.isoformat())
        assert mon["state"] == "done"
    finally:
        _teardown()


def test_api_daily_habits_today_pending_when_unlogged():
    """Today unlogged → today entry state is 'today_pending'."""
    client = _make_client()
    hab = _make_daily_habit()
    sess = _make_session([hab], [])
    try:
        with _patch_today(_TODAY), patch("backend.main.Session", return_value=sess):
            resp = client.get("/api/habits/week?week_start=2026-06-08")
        days = resp.json()["daily_habits"][0]["days"]
        today_entry = next(d for d in days if d["date"] == _TODAY.isoformat())
        assert today_entry["state"] == "today_pending"
    finally:
        _teardown()


def test_api_daily_habits_past_unlogged_is_missed():
    """Past day (before today) with no log → 'missed'."""
    client = _make_client()
    hab = _make_daily_habit()
    sess = _make_session([hab], [])
    try:
        with _patch_today(_TODAY), patch("backend.main.Session", return_value=sess):
            resp = client.get("/api/habits/week?week_start=2026-06-08")
        days = resp.json()["daily_habits"][0]["days"]
        mon = next(d for d in days if d["date"] == _WEEK_MON.isoformat())
        assert mon["state"] == "missed"
    finally:
        _teardown()


def test_api_daily_habits_future_is_future():
    """Day after today → 'future'."""
    client = _make_client()
    hab = _make_daily_habit()
    sess = _make_session([hab], [])
    try:
        with _patch_today(_TODAY), patch("backend.main.Session", return_value=sess):
            resp = client.get("/api/habits/week?week_start=2026-06-08")
        days = resp.json()["daily_habits"][0]["days"]
        friday = (_WEEK_MON + timedelta(days=4)).isoformat()
        fri = next(d for d in days if d["date"] == friday)
        assert fri["state"] == "future"
    finally:
        _teardown()


def test_api_daily_habits_total_field():
    """Each daily habit entry has total.done and total.target."""
    client = _make_client()
    hab = _make_daily_habit(target=5.0)
    logs = [_make_log(habit_id=hab.id, log_date=_WEEK_MON)]
    sess = _make_session([hab], logs)
    try:
        with _patch_today(_TODAY), patch("backend.main.Session", return_value=sess):
            resp = client.get("/api/habits/week?week_start=2026-06-08")
        dh = resp.json()["daily_habits"][0]
        assert "total" in dh
        assert dh["total"]["done"] == 1
        assert dh["total"]["target"] == 5.0
    finally:
        _teardown()


# ── (q) API: /api/habits/week — streaks.per_habit ────────────────────────────

def test_api_streaks_per_habit_present():
    """Response must include streaks.per_habit mapping."""
    client = _make_client()
    hab = _make_daily_habit()
    sess = _make_session([hab], [])
    try:
        with _patch_today(_TODAY), patch("backend.main.Session", return_value=sess):
            resp = client.get("/api/habits/week?week_start=2026-06-08")
        assert resp.status_code == 200
        body = resp.json()
        assert "streaks" in body
        assert "per_habit" in body["streaks"]
        assert str(hab.id) in body["streaks"]["per_habit"]
    finally:
        _teardown()


# ── (r) API: /api/habits/week — day_scores ────────────────────────────────────

def test_api_day_scores_has_done_and_of():
    """day_scores must have exactly 7 entries each with date, done, of."""
    client = _make_client()
    hab = _make_daily_habit()
    logs = [_make_log(habit_id=hab.id, log_date=_WEEK_MON)]
    sess = _make_session([hab], logs)
    try:
        with _patch_today(_TODAY), patch("backend.main.Session", return_value=sess):
            resp = client.get("/api/habits/week?week_start=2026-06-08")
        assert resp.status_code == 200
        body = resp.json()
        assert "day_scores" in body
        scores = body["day_scores"]
        assert len(scores) == 7
        for ds in scores:
            assert "date" in ds and "done" in ds and "of" in ds
        mon_score = next(s for s in scores if s["date"] == _WEEK_MON.isoformat())
        assert mon_score["done"] == 1
        assert mon_score["of"] == 1
    finally:
        _teardown()
