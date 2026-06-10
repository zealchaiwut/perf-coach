"""Tests for issue #391: Weekly habits-and-targets progress widget on home page.

TDD: each test class anchored to one Acceptance Criterion.
Static checks verify JS/HTML structure; API checks verify backend contract.
"""
import pathlib
import re
import uuid
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = pathlib.Path(__file__).parent.parent
HOME_HTML = REPO_ROOT / "frontend" / "pages" / "home.html"
HOME_HABITS_JS = REPO_ROOT / "frontend" / "js" / "home-habits.js"


# ── Helpers ────────────────────────────────────────────────────────────────────

def _html():
    return HOME_HTML.read_text(encoding="utf-8")


def _js():
    return HOME_HABITS_JS.read_text(encoding="utf-8")


# ── AC: home-habits.js exists ──────────────────────────────────────────────────

def test_home_habits_js_exists():
    """AC: Implemented in frontend/js/home-habits.js."""
    assert HOME_HABITS_JS.exists(), "frontend/js/home-habits.js not found"


# ── AC: home.html loads home-habits.js ────────────────────────────────────────

def test_home_html_loads_home_habits_js():
    """AC: home.html has <script src="js/home-habits.js">."""
    assert 'home-habits.js' in _html(), "home.html must load home-habits.js"


# ── AC: Widget container exists in home.html (top half) ───────────────────────

def test_widget_container_in_home_html():
    """AC: Widget container element exists in home.html."""
    html = _html()
    assert 'id="habits-progress-widget"' in html or 'id="habits-progress"' in html, (
        "home.html must have a habits-progress widget container"
    )


def test_widget_appears_before_row1():
    """AC: Widget is in top half — container appears before row-1 in HTML."""
    html = _html()
    widget_pos = html.find('habits-progress')
    row1_pos = html.find('id="row-1"')
    assert widget_pos != -1, "habits-progress container not found"
    assert row1_pos != -1, "row-1 not found"
    assert widget_pos < row1_pos, "habits-progress widget must appear before row-1"


# ── AC: Widget title ──────────────────────────────────────────────────────────

def test_widget_title_this_weeks_progress():
    """AC: Widget titled 'This week's progress'."""
    js = _js()
    assert "This week" in js and "progress" in js.lower(), (
        "JS must render 'This week's progress' title"
    )


# ── AC: Calls GET /api/habits ─────────────────────────────────────────────────

def test_js_calls_get_api_habits():
    """AC: Calls GET /api/habits to fetch habits on load."""
    js = _js()
    assert "/api/habits" in js, "JS must call /api/habits"
    # Should NOT pass user_id (session-based)
    assert "fetch('/api/habits')" in js or 'fetch("/api/habits")' in js or (
        re.search(r"fetch\(['\"]\/api\/habits['\"]", js)
    ), "JS must fetch /api/habits without query params for session auth"


# ── AC: Calls /api/habits/{id}/progress?week_start= in parallel ───────────────

def test_js_calls_habit_progress_endpoint():
    """AC: Calls GET /api/habits/{id}/progress?week_start={current_monday}."""
    js = _js()
    assert "/progress" in js and "week_start" in js, (
        "JS must call /api/habits/{id}/progress?week_start=..."
    )


def test_js_uses_promise_all():
    """AC: Progress fetches executed in parallel via Promise.all."""
    js = _js()
    assert "Promise.all" in js, "JS must use Promise.all for parallel progress fetches"


# ── AC: Days remaining computed correctly ─────────────────────────────────────

def test_js_computes_days_remaining():
    """AC: Days remaining = 7 - (today.weekday, Monday=0)."""
    js = _js()
    # Must compute days remaining in week; getDay() with Monday=0 adjustment or similar
    assert "days" in js.lower() and ("remaining" in js.lower() or "7 -" in js or "7-" in js), (
        "JS must compute days remaining in week"
    )


# ── AC: Progress bar capped at 100% ───────────────────────────────────────────

def test_js_caps_progress_bar_at_100():
    """AC: Progress bar capped at 100% even when value exceeds target."""
    js = _js()
    # Must cap at 100 — e.g. Math.min(100, ...) or min(100
    assert "Math.min(100" in js or "min(100," in js or "100%" in js, (
        "JS must cap progress bar at 100%"
    )


# ── AC: Checkmark for completed habits ───────────────────────────────────────

def test_js_shows_checkmark_when_complete():
    """AC: Rows where progress >= 100% show a checkmark (is_complete)."""
    js = _js()
    assert "is_complete" in js or "checkmark" in js.lower() or "ti-check" in js, (
        "JS must show checkmark when habit is complete"
    )


# ── AC: Sorted incomplete first ───────────────────────────────────────────────

def test_js_sorts_incomplete_first():
    """AC: Habits sorted incomplete first, completed last."""
    js = _js()
    assert ".sort(" in js or "sort(" in js, "JS must sort habits"
    assert "is_complete" in js, "JS sort must reference is_complete"


# ── AC: Click navigates to /habits#{habit_id} ─────────────────────────────────

def test_js_click_navigates_to_habits_anchor():
    """AC: Clicking a row navigates to /habits#{habit_id}."""
    js = _js()
    assert "/habits#" in js or "habits#" in js, (
        "JS must navigate to /habits#{habit_id} on row click"
    )


# ── AC: Empty state ───────────────────────────────────────────────────────────

def test_js_has_empty_state():
    """AC: Zero habits shows 'Add habits to track your weekly goals' with link to /habits."""
    js = _js()
    assert "Add habits" in js or "weekly goals" in js, (
        "JS must render empty state with 'Add habits to track your weekly goals'"
    )
    assert '"/habits"' in js or "'/habits'" in js or "href=\"/habits\"" in js or "href='/habits'" in js, (
        "Empty state must link to /habits"
    )


# ── AC: Loading skeleton ──────────────────────────────────────────────────────

def test_js_has_skeleton_loading_state():
    """AC: Skeleton rows render while data is in flight."""
    js = _js()
    assert "skeleton" in js.lower() or "skel" in js.lower(), (
        "JS must render skeleton rows during loading"
    )


# ── AC: Error state with retry ────────────────────────────────────────────────

def test_js_has_error_state_with_retry():
    """AC: Inline error message with retry button; no crash."""
    js = _js()
    assert "retry" in js.lower() or "Retry" in js, "JS must show retry button on error"
    assert "error" in js.lower(), "JS must render error state"


# ── AC: visibilitychange refresh ─────────────────────────────────────────────

def test_js_listens_for_visibility_change():
    """AC: Widget refreshes when page regains visibility."""
    js = _js()
    assert "visibilitychange" in js, "JS must listen for visibilitychange event"
    assert "visibilityState" in js, "JS must check document.visibilityState"


# ── AC: Uses design tokens (no hardcoded colors) ──────────────────────────────

def test_js_uses_design_tokens_not_hardcoded_colors():
    """AC: Uses existing home page design tokens — no hardcoded hex colors in JS."""
    js = _js()
    # Allow hex in comments; find raw hex color assignments in JS strings
    hardcoded = re.findall(r'(?<!var\()["\']#[0-9a-fA-F]{3,6}["\']', js)
    # Filter out any that are in CSS variable definitions or acceptable
    hardcoded = [h for h in hardcoded if "var(--" not in h]
    assert not hardcoded, (
        f"JS must not contain hardcoded hex colors; found: {hardcoded}"
    )


# ── AC: API contract — GET /api/habits returns list ───────────────────────────

def test_api_get_habits_requires_auth():
    """GET /api/habits returns 401 when unauthenticated."""
    from fastapi.testclient import TestClient
    from backend.main import app
    client = TestClient(app, raise_server_exceptions=False)
    res = client.get("/api/habits")
    assert res.status_code == 401, f"Expected 401, got {res.status_code}"


def test_api_get_habits_returns_list_with_auth():
    """GET /api/habits returns 200 list when authenticated."""
    from fastapi.testclient import TestClient
    from backend.main import app, resolve_user

    mock_user = MagicMock()
    mock_user.id = uuid.UUID("00000000-0000-0000-0000-000000000391")

    async def fake_resolve():
        return mock_user

    app.dependency_overrides[resolve_user] = fake_resolve
    try:
        with patch("backend.main.Session") as MockSession:
            mock_session = MagicMock()
            MockSession.return_value.__enter__ = MagicMock(return_value=mock_session)
            MockSession.return_value.__exit__ = MagicMock(return_value=False)
            mock_q = MagicMock()
            mock_session.query.return_value = mock_q
            mock_q.filter.return_value = mock_q
            mock_q.order_by.return_value = mock_q
            mock_q.all.return_value = []

            client = TestClient(app)
            res = client.get("/api/habits")
            assert res.status_code == 200
            assert res.json() == []
    finally:
        app.dependency_overrides.pop(resolve_user, None)


# ── AC: API contract — GET /api/habits/{id}/progress returns expected shape ───

def test_api_habit_progress_requires_auth():
    """GET /api/habits/{id}/progress returns 401 when unauthenticated."""
    from fastapi.testclient import TestClient
    from backend.main import app
    client = TestClient(app, raise_server_exceptions=False)
    hid = str(uuid.uuid4())
    res = client.get(f"/api/habits/{hid}/progress")
    assert res.status_code == 401, f"Expected 401, got {res.status_code}"


def test_api_habit_progress_shape():
    """GET /api/habits/{id}/progress returns required shape fields."""
    from fastapi.testclient import TestClient
    from backend.main import app, resolve_user
    from backend.models import Habit

    hid = uuid.uuid4()
    mock_user = MagicMock()
    mock_user.id = uuid.UUID("00000000-0000-0000-0000-000000000391")

    async def fake_resolve():
        return mock_user

    app.dependency_overrides[resolve_user] = fake_resolve
    try:
        with patch("backend.main.Session") as MockSession:
            mock_session = MagicMock()
            MockSession.return_value.__enter__ = MagicMock(return_value=mock_session)
            MockSession.return_value.__exit__ = MagicMock(return_value=False)

            mock_habit = MagicMock(spec=Habit)
            mock_habit.id = hid
            mock_habit.user_id = mock_user.id
            mock_habit.name = "Run"
            mock_habit.description = None
            mock_habit.tracking_type = "quantity"
            mock_habit.weekly_target = 210.0
            mock_habit.unit = "min"
            mock_habit.auto_fill_source = None
            mock_habit.icon = None
            mock_habit.color = None
            mock_habit.sort_order = 1
            mock_habit.is_archived = False
            ts = MagicMock()
            ts.isoformat.return_value = "2026-06-09T00:00:00+00:00"
            mock_habit.created_at = ts
            mock_habit.updated_at = None

            mock_session.get.return_value = mock_habit
            mock_q = MagicMock()
            mock_session.query.return_value = mock_q
            mock_q.filter.return_value = mock_q
            mock_q.all.return_value = []

            client = TestClient(app)
            week_start = "2026-06-09"
            res = client.get(f"/api/habits/{hid}/progress?week_start={week_start}")
            assert res.status_code == 200
            data = res.json()
            required_keys = {
                "habit", "week_start", "week_end", "target",
                "current_value", "percentage", "is_complete",
            }
            missing = required_keys - set(data.keys())
            assert not missing, f"Progress response missing keys: {missing}"
            assert data["is_complete"] is False
            assert data["current_value"] == 0.0
    finally:
        app.dependency_overrides.pop(resolve_user, None)
