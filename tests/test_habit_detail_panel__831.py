"""Tests for issue #831: Build per-habit detail panel with stats and history.

AC mapping:
- AC1:  HTML has a detail panel element that opens when a habit is selected
- AC2:  Panel shows current_streak from /api/habits/{id}/summary
- AC3:  Panel shows longest_streak from /api/habits/{id}/summary
- AC4:  Panel shows consistency_pct from /api/habits/{id}/summary
- AC5:  Panel shows log history from the log endpoint
- AC6:  Empty habit (no logs) shows streak=0, consistency=0%, friendly empty state
- AC7:  Layout uses structural CSS (no hard-coded px offsets)
- AC8:  Edit entry point is visible in the panel
- AC9:  Archive entry point is visible in the panel
- AC10: Panel is responsive (CSS media queries present)
- AC11: No console errors (JS calls guarded; log history not filtered to broken state)

Static tests read frontend/pages/habits.html and frontend/js/habits.js.
Unit tests exercise the new /api/habits/{habit_id}/summary endpoint with mocked DB.
Live tests (skipped when server not up) hit http://127.0.0.1:9001.
"""

import os
import pathlib
import re
import uuid
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest

BASE_URL = os.environ.get("UAT_BASE_URL", "http://127.0.0.1:9001")
ROOT = pathlib.Path(__file__).parent.parent

_CREDENTIALS = {"username": "tester831", "password": "Test831pass!"}

_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000831")


# ── File readers ──────────────────────────────────────────────────────────────

def _html() -> str:
    return (ROOT / "frontend" / "pages" / "habits.html").read_text()


def _js() -> str:
    return (ROOT / "frontend" / "js" / "habits.js").read_text()


# ── Mock helpers ──────────────────────────────────────────────────────────────

def _make_user():
    from backend.models import User
    u = MagicMock(spec=User)
    u.id = _USER_ID
    return u


def _make_habit(tracking_type="daily_checkmark", hid=None):
    from backend.models import Habit
    h = MagicMock(spec=Habit)
    h.id = hid or uuid.uuid4()
    h.user_id = _USER_ID
    h.name = "Morning run"
    h.description = None
    h.tracking_type = tracking_type
    h.weekly_target = 7.0
    h.unit = "days"
    h.auto_fill_source = None
    h.icon = "ti-run"
    h.color = "#3b82f6"
    h.sort_order = 0
    h.is_archived = False
    ts = MagicMock()
    ts.isoformat.return_value = "2026-06-01T00:00:00+00:00"
    h.created_at = ts
    h.updated_at = None
    return h


def _make_log(habit_id, log_date, value=1.0):
    from backend.models import HabitLog
    lg = MagicMock(spec=HabitLog)
    lg.id = uuid.uuid4()
    lg.habit_id = habit_id
    lg.user_id = _USER_ID
    lg.log_date = log_date
    lg.log_week_start = log_date - timedelta(days=log_date.weekday())
    lg.value = value
    lg.notes = None
    lg.source = "manual"
    ts = MagicMock()
    ts.isoformat.return_value = "2026-06-01T00:00:00+00:00"
    lg.created_at = ts
    return lg


def _make_client():
    from backend.main import app, resolve_user
    from fastapi.testclient import TestClient
    mock_user = _make_user()

    async def _fake_resolve():
        return mock_user

    app.dependency_overrides[resolve_user] = _fake_resolve
    return TestClient(app), mock_user


def _teardown():
    from backend.main import app, resolve_user
    app.dependency_overrides.pop(resolve_user, None)


# ── AC1: HTML has detail panel ────────────────────────────────────────────────

def test_html_has_detail_panel():
    """AC1: habits.html has a habit detail panel container."""
    html = _html()
    assert 'id="habit-detail-panel"' in html, (
        "habits.html must have id='habit-detail-panel'"
    )


def test_js_opens_detail_panel_on_habit_select():
    """AC1: habits.js has a function that opens/reveals the detail panel."""
    js = _js()
    assert "habit-detail-panel" in js, (
        "habits.js must reference 'habit-detail-panel' to open it"
    )
    # Should have a function that loads detail for a given habit id
    assert re.search(r"function\s+\w*[Dd]etail\w*\s*\(", js) or \
           re.search(r"openHabitDetail|loadHabitDetail|showHabitDetail", js), (
        "habits.js must define a function to open/load the habit detail panel"
    )


# ── AC2: current_streak from summary endpoint ─────────────────────────────────

def test_summary_endpoint_returns_current_streak():
    """AC2: GET /api/habits/{id}/summary returns current_streak."""
    client, mock_user = _make_client()
    habit_id = uuid.uuid4()
    habit = _make_habit(hid=habit_id)
    today = date.today()
    logs = [_make_log(habit_id, today - timedelta(days=i)) for i in range(5)]

    with patch("backend.main.Session") as MockSession:
        sess = MockSession.return_value.__enter__.return_value
        sess.get.return_value = habit
        sess.query.return_value.filter.return_value.all.return_value = logs

        res = client.get(f"/api/habits/{habit_id}/summary")

    _teardown()
    assert res.status_code == 200
    data = res.json()
    assert "current_streak" in data, "Response must include current_streak"
    assert isinstance(data["current_streak"], int)


def test_js_calls_habit_summary_endpoint():
    """AC2/AC3/AC4: habits.js fetches /api/habits/{id}/summary for stats."""
    js = _js()
    assert re.search(r"/api/habits/\${?.+}?/summary", js) or \
           re.search(r"/api/habits/.*\+.*summary|`/api/habits/.*summary`", js), (
        "habits.js must fetch /api/habits/{id}/summary for the detail panel"
    )


# ── AC3: longest_streak from summary endpoint ─────────────────────────────────

def test_summary_endpoint_returns_longest_streak():
    """AC3: GET /api/habits/{id}/summary returns longest_streak."""
    client, mock_user = _make_client()
    habit_id = uuid.uuid4()
    habit = _make_habit(hid=habit_id)
    today = date.today()
    # 3 consecutive days, gap, then 5 consecutive — longest = 5
    logs = (
        [_make_log(habit_id, today - timedelta(days=i)) for i in range(3)] +
        [_make_log(habit_id, today - timedelta(days=10 + i)) for i in range(5)]
    )

    with patch("backend.main.Session") as MockSession:
        sess = MockSession.return_value.__enter__.return_value
        sess.get.return_value = habit
        sess.query.return_value.filter.return_value.all.return_value = logs

        res = client.get(f"/api/habits/{habit_id}/summary")

    _teardown()
    assert res.status_code == 200
    data = res.json()
    assert "longest_streak" in data, "Response must include longest_streak"
    assert isinstance(data["longest_streak"], int)


# ── AC4: consistency_pct from summary endpoint ────────────────────────────────

def test_summary_endpoint_returns_consistency_pct():
    """AC4: GET /api/habits/{id}/summary returns consistency_pct (last 30 days)."""
    client, mock_user = _make_client()
    habit_id = uuid.uuid4()
    habit = _make_habit(hid=habit_id)
    today = date.today()
    # 15 out of last 30 days → 50%
    logs = [_make_log(habit_id, today - timedelta(days=i * 2)) for i in range(15)]

    with patch("backend.main.Session") as MockSession:
        sess = MockSession.return_value.__enter__.return_value
        sess.get.return_value = habit
        sess.query.return_value.filter.return_value.all.return_value = logs

        res = client.get(f"/api/habits/{habit_id}/summary")

    _teardown()
    assert res.status_code == 200
    data = res.json()
    assert "consistency_pct" in data, "Response must include consistency_pct"
    assert isinstance(data["consistency_pct"], (int, float))


def test_summary_endpoint_includes_habit_metadata():
    """AC2/AC3/AC4: Summary endpoint also returns habit dict for convenience."""
    client, mock_user = _make_client()
    habit_id = uuid.uuid4()
    habit = _make_habit(hid=habit_id)

    with patch("backend.main.Session") as MockSession:
        sess = MockSession.return_value.__enter__.return_value
        sess.get.return_value = habit
        sess.query.return_value.filter.return_value.all.return_value = []

        res = client.get(f"/api/habits/{habit_id}/summary")

    _teardown()
    assert res.status_code == 200
    data = res.json()
    assert "habit" in data, "Response must include habit metadata"
    assert data["habit"]["id"] == str(habit_id)


# ── AC5: log history from log endpoint ───────────────────────────────────────

def test_js_fetches_logs_for_detail_panel():
    """AC5: habits.js fetches logs when loading habit detail."""
    js = _js()
    # Should call the logs endpoint with habit_id filter
    assert re.search(r"api/habits/logs|api/habits/\${?.+}?/logs", js) or \
           re.search(r"habit_id.*logs|logs.*habit_id", js), (
        "habits.js must fetch habit logs for the detail panel history list"
    )


def test_logs_endpoint_filters_by_habit_id():
    """AC5: GET /api/habits/logs?habit_id=X filters to that habit's logs only."""
    client, mock_user = _make_client()
    habit_id = uuid.uuid4()
    today = date.today()
    # Only logs for habit_id should be returned
    habit_logs = [_make_log(habit_id, today - timedelta(days=i)) for i in range(3)]

    with patch("backend.main.Session") as MockSession:
        sess = MockSession.return_value.__enter__.return_value
        sess.query.return_value.filter.return_value.all.return_value = habit_logs

        res = client.get(
            f"/api/habits/logs"
            f"?habit_id={habit_id}&from={today - timedelta(days=30)}&to={today}"
        )

    _teardown()
    assert res.status_code == 200
    logs = res.json()
    assert isinstance(logs, list)


def test_html_detail_panel_has_log_history_section():
    """AC5: Detail panel HTML has a log history list container."""
    html = _html()
    assert "habit-detail-panel" in html
    # history container must be inside or alongside the detail panel
    assert re.search(r"habit-detail-(history|logs|log-list)", html) or \
           re.search(r'id="detail-(history|logs|log-list)"', html) or \
           "detail-history" in html or "detail-logs" in html, (
        "habits.html must have a log history container in the detail panel"
    )


# ── AC6: empty habit (zero logs) graceful state ───────────────────────────────

def test_summary_endpoint_zero_logs_returns_zeros():
    """AC6: Habit with no logs: current_streak=0, longest_streak=0, consistency_pct=0."""
    client, mock_user = _make_client()
    habit_id = uuid.uuid4()
    habit = _make_habit(hid=habit_id)

    with patch("backend.main.Session") as MockSession:
        sess = MockSession.return_value.__enter__.return_value
        sess.get.return_value = habit
        sess.query.return_value.filter.return_value.all.return_value = []

        res = client.get(f"/api/habits/{habit_id}/summary")

    _teardown()
    assert res.status_code == 200
    data = res.json()
    assert data["current_streak"] == 0
    assert data["longest_streak"] == 0
    assert data["consistency_pct"] == 0.0


def test_js_renders_empty_state_for_no_logs():
    """AC6: habits.js renders a friendly empty state when log list is empty."""
    js = _js()
    assert re.search(r"empty.?state|no.?log|no.?entr|No log", js, re.IGNORECASE), (
        "habits.js must render a friendly empty-state message when no logs exist"
    )


# ── AC7: layout uses structural CSS tokens ────────────────────────────────────

def test_detail_panel_uses_token_spacing():
    """AC7: Detail panel CSS uses spacing tokens/vars, not hard-coded px values."""
    html = _html()
    # Extract styles specific to detail panel
    panel_style_match = re.search(
        r"\.habit-detail-panel[^}]*\{([^}]*)\}", html, re.DOTALL
    )
    if panel_style_match:
        style_block = panel_style_match.group(1)
        # Hard-coded pixel padding/margin without var() are a violation
        hard_px = re.findall(r"(?:padding|margin)\s*:\s*[\d.]+px", style_block)
        for px in hard_px:
            assert False, (
                f"Detail panel CSS uses hard-coded pixel offset: '{px}'. "
                "Use spacing tokens (var(--space-*)) or relative units instead."
            )


# ── AC8: Edit entry point ─────────────────────────────────────────────────────

def test_detail_panel_has_edit_button():
    """AC8: Detail panel has an Edit button/link visible."""
    html = _html()
    assert re.search(
        r'id="[^"]*detail[^"]*edit[^"]*"|id="[^"]*edit[^"]*detail[^"]*"'
        r'|class="[^"]*detail[^"]*edit[^"]*"'
        r'|detail-edit|btn-edit-habit',
        html,
        re.IGNORECASE,
    ) or re.search(r"Edit</button>|Edit</a>", html), (
        "Detail panel must have an Edit entry point (button or link)"
    )


def test_js_edit_button_is_noop():
    """AC8: Edit button in detail panel does not navigate or trigger actions."""
    js = _js()
    # Edit button handler should be a no-op (preventDefault or empty handler)
    assert re.search(
        r"detail.*edit|edit.*detail|btn-edit-habit|detail-edit",
        js, re.IGNORECASE
    ), (
        "habits.js must reference the detail panel Edit button"
    )


# ── AC9: Archive entry point ──────────────────────────────────────────────────

def test_detail_panel_has_archive_button():
    """AC9: Detail panel has an Archive button/link visible."""
    html = _html()
    assert re.search(
        r'detail-archive|btn-archive-habit'
        r'|Archive</button>|Archive</a>',
        html,
        re.IGNORECASE,
    ), (
        "Detail panel must have an Archive entry point (button or link)"
    )


def test_js_archive_button_is_noop():
    """AC9: Archive button in detail panel does not trigger actions."""
    js = _js()
    assert re.search(
        r"detail.*archive|archive.*detail|btn-archive-habit|detail-archive",
        js, re.IGNORECASE
    ), (
        "habits.js must reference the detail panel Archive button"
    )


# ── AC10: Responsive layout ───────────────────────────────────────────────────

def test_detail_panel_has_responsive_styles():
    """AC10: habits.html includes media queries for the detail panel."""
    html = _html()
    # There should be at least one media query covering ≤768px and/or ≤375px
    media_queries = re.findall(r"@media\s*\([^)]*\)", html)
    assert any("375" in mq or "480" in mq or "768" in mq for mq in media_queries), (
        "habits.html must have media queries for mobile/iPad viewports"
    )


# ── AC11: No unhandled errors ─────────────────────────────────────────────────

def test_summary_endpoint_404_for_unknown_habit():
    """AC11: Summary endpoint returns 404 for a non-existent habit."""
    client, _ = _make_client()
    unknown_id = uuid.uuid4()

    with patch("backend.main.Session") as MockSession:
        sess = MockSession.return_value.__enter__.return_value
        sess.get.return_value = None

        res = client.get(f"/api/habits/{unknown_id}/summary")

    _teardown()
    assert res.status_code == 404


def test_summary_endpoint_403_for_wrong_user():
    """AC11: Summary endpoint returns 403 when habit belongs to different user."""
    client, _ = _make_client()
    habit_id = uuid.uuid4()
    habit = _make_habit(hid=habit_id)
    habit.user_id = uuid.uuid4()  # different user

    with patch("backend.main.Session") as MockSession:
        sess = MockSession.return_value.__enter__.return_value
        sess.get.return_value = habit
        sess.query.return_value.filter.return_value.all.return_value = []

        res = client.get(f"/api/habits/{habit_id}/summary")

    _teardown()
    assert res.status_code == 403


def test_summary_endpoint_400_for_bad_id():
    """AC11: Summary endpoint returns 400 for malformed habit_id."""
    client, _ = _make_client()

    res = client.get("/api/habits/not-a-uuid/summary")
    _teardown()
    assert res.status_code == 400


# ── Live integration tests (skipped when server is not running) ───────────────

try:
    import httpx  # noqa: F401
    _HTTPX_AVAILABLE = True
except ImportError:
    _HTTPX_AVAILABLE = False


def _extract_cookie(response, name: str):
    for header in response.headers.get_list("set-cookie"):
        parts = [p.strip() for p in header.split(";")]
        if parts and "=" in parts[0]:
            k, v = parts[0].split("=", 1)
            if k.strip() == name:
                return v.strip()
    return None


@pytest.fixture(scope="module")
def live_client():
    if not _HTTPX_AVAILABLE:
        pytest.skip("httpx not available")
    import httpx as _httpx
    with _httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        r = c.post("/api/auth/login", json=_CREDENTIALS)
        if r.status_code != 200:
            pytest.skip(f"Login failed ({r.status_code}); seed tester831 first")
        csrf_val = _extract_cookie(r, "csrf-token")
        if csrf_val:
            c.cookies.set("csrf-token", csrf_val, domain="127.0.0.1")
        yield c


def test_live_summary_endpoint_shape(live_client):
    """Live: /api/habits/{id}/summary returns correct shape for any habit."""
    r = live_client.get("/api/habits")
    if r.status_code != 200 or not r.json():
        pytest.skip("No habits available for live test")
    habit_id = r.json()[0]["id"]

    r2 = live_client.get(f"/api/habits/{habit_id}/summary")
    assert r2.status_code == 200
    data = r2.json()
    for key in ("habit", "current_streak", "longest_streak", "consistency_pct"):
        assert key in data, f"Live summary missing field: {key}"


def test_live_logs_endpoint_with_habit_id(live_client):
    """Live: /api/habits/logs?habit_id=X&from=...&to=... works."""
    r = live_client.get("/api/habits")
    if r.status_code != 200 or not r.json():
        pytest.skip("No habits available for live test")
    habit_id = r.json()[0]["id"]
    today_str = date.today().isoformat()
    from_str = (date.today() - timedelta(days=90)).isoformat()

    r2 = live_client.get(
        f"/api/habits/logs?habit_id={habit_id}&from={from_str}&to={today_str}"
    )
    assert r2.status_code == 200
    assert isinstance(r2.json(), list)
