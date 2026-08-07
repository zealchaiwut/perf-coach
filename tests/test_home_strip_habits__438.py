"""Home habits + metrics log surface after home revamp v2.

Issue #438 originally shipped a log-today strip + habits wheel widget.
Revamp v2 moved habits into #home-morning (home-morning.js) and Log metrics
into the Readiness card (data-rd-log-metrics → #row-log). Backend summary
contract tests below are unchanged.
"""
import pathlib
import uuid
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.main import app, resolve_user
from backend.models import Habit, HabitLog, DailyMetric

_ROOT = pathlib.Path(__file__).parent.parent
_HTML = (_ROOT / "frontend" / "pages" / "home.html").read_text()
_MORNING_JS = (_ROOT / "frontend" / "js" / "home-morning.js").read_text()
_RTS_JS = (_ROOT / "frontend" / "js" / "home-readiness-training-sleep.js").read_text()
_WH_JS = (_ROOT / "frontend" / "js" / "wheel-helpers.js").read_text()

_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000438")
_TODAY = date(2026, 6, 11)
_WEEK_MON = date(2026, 6, 8)

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
    return lg


def _make_metrics():
    m = MagicMock(spec=DailyMetric)
    m.id = uuid.uuid4()
    m.user_id = _USER_ID
    m.metric_date = _TODAY
    m.resting_hr = 52
    m.hrv = 60
    m.sleep_hours = 7.5
    m.sleep_quality = 4
    m.energy = 4
    m.mood = 4
    m.notes = None
    return m


def _patch_today():
    return patch("backend.main._today_bangkok", return_value=_TODAY)


def _mock_summary_session(*, habits=None, logs=None, metrics=None, baseline_rows=None):
    habits = habits or []
    logs = logs or []
    baseline_rows = baseline_rows if baseline_rows is not None else []

    mock_s = MagicMock()
    habit_q = MagicMock()
    habit_q.filter.return_value = habit_q
    habit_q.order_by.return_value = habit_q
    habit_q.all.return_value = habits

    log_q = MagicMock()
    log_q.filter.return_value = log_q
    log_q.all.return_value = logs

    metrics_q = MagicMock()
    metrics_q.filter.return_value = metrics_q
    metrics_q.first.return_value = metrics
    metrics_q.order_by.return_value = metrics_q
    metrics_q.all.return_value = baseline_rows

    def _query(model, *a, **kw):
        if model is Habit:
            return habit_q
        if model is HabitLog:
            return log_q
        if model is DailyMetric:
            return metrics_q
        q = MagicMock()
        q.filter.return_value = q
        q.order_by.return_value = q
        q.all.return_value = []
        q.first.return_value = None
        return q

    mock_s.query.side_effect = _query
    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_s
    mock_cm.__exit__.return_value = False
    return mock_cm


# ── UI: Log metrics via Readiness (replaces log-today strip) ──────────────────

def test_html_has_fast_log_row():
    """#row-log fast-log form remains for Log metrics."""
    assert 'id="row-log"' in _HTML
    assert 'id="fast-log-section"' in _HTML


def test_html_readiness_log_metrics_path():
    """Readiness card reveals #row-log via data-rd-log-metrics."""
    assert "data-rd-log-metrics" in _RTS_JS
    assert "row-log" in _RTS_JS


def test_html_retired_log_today_strip_gone():
    assert "home-log-today-strip" not in _HTML


# ── UI: Habits live in This morning ───────────────────────────────────────────

def test_html_has_morning_habits_host():
    assert 'id="home-morning"' in _HTML
    assert "home-morning.js" in _HTML
    assert "home-habits-widget" not in _HTML


def test_morning_js_habit_chips_and_log_endpoints():
    assert "daily_habits" in _MORNING_JS
    assert "/api/habits/logs" in _MORNING_JS
    assert "DELETE" in _MORNING_JS
    assert "today_checked" in _MORNING_JS


def test_morning_js_optimistic_habit_toggle():
    assert "hm-hab--on" in _MORNING_JS
    assert "catch" in _MORNING_JS


def test_morning_js_habits_link():
    assert "/habits" in _MORNING_JS


def test_morning_js_empty_habits_copy():
    assert "no habits" in _MORNING_JS.lower()


def test_wheel_helpers_file_still_exists():
    """wheel-helpers.js remains for /habits; Home no longer loads it for a wheel."""
    assert "polarToCartesian" in _WH_JS
    assert "arcPath" in _WH_JS


def test_html_no_longer_loads_habits_strip_module():
    assert 'src="js/home-strip-habits.js' not in _HTML
    assert "src='js/home-strip-habits.js" not in _HTML


def test_html_mobile_responsive():
    assert "@media" in _HTML and "max-width" in _HTML


# ── Backend: habits + readiness summary contract ──────────────────────────────

def test_habits_block_includes_streak():
    h1 = _make_habit(hid=uuid.UUID("11111111-1111-1111-1111-111111111111"))
    logs = [
        _make_log(habit_id=h1.id, log_date=_TODAY),
        _make_log(habit_id=h1.id, log_date=_TODAY - timedelta(days=1)),
        _make_log(habit_id=h1.id, log_date=_TODAY - timedelta(days=2)),
    ]
    c = _override_user()
    try:
        mock_cm = _mock_summary_session(habits=[h1], logs=logs)
        with _patch_today(), patch("backend.main.Session", return_value=mock_cm):
            r = c.get("/api/home/summary")
        assert r.status_code == 200
        daily = r.json()["habits"]["daily_habits"]
        assert len(daily) == 1
        assert "streak" in daily[0], "each daily habit must include 'streak'"
        assert isinstance(daily[0]["streak"], int)
    finally:
        _teardown()


def test_habits_block_includes_auto_fill_source():
    h1 = _make_habit(
        hid=uuid.UUID("22222222-2222-2222-2222-222222222222"),
        auto_fill_source="workout.run_count",
    )
    c = _override_user()
    try:
        mock_cm = _mock_summary_session(habits=[h1])
        with _patch_today(), patch("backend.main.Session", return_value=mock_cm):
            r = c.get("/api/home/summary")
        assert r.status_code == 200
        assert r.json()["habits"]["daily_habits"][0]["auto_fill_source"] == "workout.run_count"
    finally:
        _teardown()


def test_habits_block_streak_zero_when_no_logs():
    h1 = _make_habit(hid=uuid.UUID("33333333-3333-3333-3333-333333333333"))
    c = _override_user()
    try:
        mock_cm = _mock_summary_session(habits=[h1], logs=[])
        with _patch_today(), patch("backend.main.Session", return_value=mock_cm):
            r = c.get("/api/home/summary")
        assert r.status_code == 200
        assert r.json()["habits"]["daily_habits"][0]["streak"] == 0
    finally:
        _teardown()


def test_readiness_block_logged_true_when_metrics_exist():
    c = _override_user()
    try:
        mock_cm = _mock_summary_session(metrics=_make_metrics())
        with _patch_today(), patch("backend.main.Session", return_value=mock_cm):
            r = c.get("/api/home/summary")
        assert r.status_code == 200
        assert r.json()["readiness"] is not None
        assert r.json()["readiness"].get("logged") is True
    finally:
        _teardown()


def test_readiness_block_logged_false_when_no_metrics():
    c = _override_user()
    try:
        mock_cm = _mock_summary_session(metrics=None)
        with _patch_today(), patch("backend.main.Session", return_value=mock_cm):
            r = c.get("/api/home/summary")
        assert r.status_code == 200
        rd = r.json().get("readiness")
        if rd is not None:
            assert rd.get("logged") is False
    finally:
        _teardown()
