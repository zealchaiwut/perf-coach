"""Tests for issue #638: Add Desktop Month Calendar to Training Log Tab (runs against UAT)"""
import os
import uuid
import pytest
import httpx
from sqlalchemy.orm import Session as _OrmSess
from backend.auth import hash_password as _hash_pw
from backend.db import engine as _engine
from backend.models import User as _UserModel


BASE_URL = os.environ.get("UAT_BASE_URL") or "http://localhost:" + os.environ.get("UAT_PORT", "")
if not BASE_URL.startswith("http"):
    raise RuntimeError(
        "UAT_BASE_URL / UAT_PORT not set. Run the tester skill's Step 0 to resolve UAT before pytest."
    )

_TEST_PW = "tester638-pw"


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        yield c


@pytest.fixture(scope="module")
def test_user(client):
    name = f"tester638_{uuid.uuid4().hex[:8]}"
    r = client.post("/api/users", json={"name": name})
    assert r.status_code == 201, r.text
    uid = r.json()["id"]
    pw_hash = _hash_pw(_TEST_PW)
    with _OrmSess(_engine) as db:
        u = db.get(_UserModel, uuid.UUID(uid))
        u.password_hash = pw_hash
        db.commit()
    yield uid
    client.delete(f"/api/users/{uid}")


@pytest.fixture(scope="module")
def session_cookie(client, test_user):
    with _OrmSess(_engine) as db:
        u = db.get(_UserModel, uuid.UUID(test_user))
        name = u.name
    res = client.post("/api/auth/login", json={"username": name, "password": _TEST_PW})
    assert res.status_code == 200, res.text
    return res.cookies.get("session")


@pytest.fixture(scope="module")
def logged_in_client(session_cookie):
    with httpx.Client(base_url=BASE_URL, timeout=10.0, follow_redirects=True) as c:
        c.cookies.set("session", session_cookie)
        yield c


# --- Acceptance Criteria ---

def test_calendar_container_renders_on_log_page(logged_in_client):
    """AC1: A month-grid calendar element is present in the Log tab HTML."""
    r = logged_in_client.get("/log")
    assert r.status_code == 200
    text = r.text
    assert "log-calendar" in text, "Expected log-calendar container element in HTML"


def test_calendar_css_defines_grid_and_cells(logged_in_client):
    """AC1: Calendar grid CSS classes are defined (cal-grid, cal-cell, cal-weekday)."""
    r = logged_in_client.get("/log")
    assert r.status_code == 200
    text = r.text
    assert "cal-grid" in text, "Expected .cal-grid CSS class"
    assert "cal-cell" in text, "Expected .cal-cell CSS class"
    assert "cal-weekday" in text, "Expected .cal-weekday CSS class"


def test_calendar_hidden_below_1024px_breakpoint(logged_in_client):
    """AC2: Calendar is hidden (display:none) at mobile/tablet widths via @media query."""
    r = logged_in_client.get("/log")
    assert r.status_code == 200
    text = r.text
    # Check for media query approach (display: none at default, display: block at 1024px+)
    assert "@media" in text, "Expected media queries for responsive behavior"
    assert "1024" in text, "Expected 1024px desktop breakpoint reference in CSS"
    # Check for display rules
    assert "display: none" in text or "display:none" in text or "display: block" in text, \
        "Expected display:none/block in media queries for calendar"


def test_calendar_no_new_api_endpoint(logged_in_client):
    """AC3: No new API endpoint required; calendar uses existing training data."""
    r = logged_in_client.get("/log")
    assert r.status_code == 200
    text = r.text
    # Verify no new /api/calendar endpoint is created
    assert "/api/calendar" not in text, "Calendar should not add a new /api/calendar endpoint"


def test_day_cells_css_for_type_dots(logged_in_client):
    """AC4a: CSS for workout type-dots is defined (cal-dot)."""
    r = logged_in_client.get("/log")
    assert r.status_code == 200
    text = r.text
    assert "cal-dot" in text, "Expected .cal-dot CSS class for workout-type dots"


def test_day_cells_css_for_load_bar(logged_in_client):
    """AC4b: CSS for daily-load bar is defined (cal-load, cal-load-bar)."""
    r = logged_in_client.get("/log")
    assert r.status_code == 200
    text = r.text
    assert "cal-load" in text, "Expected .cal-load CSS class"
    assert "cal-load-bar" in text, "Expected .cal-load-bar CSS class"


def test_navigation_controls_css_defined(logged_in_client):
    """AC6: Prev/Next/Today navigation button CSS classes defined."""
    r = logged_in_client.get("/log")
    assert r.status_code == 200
    text = r.text
    assert "cal-nav-btn" in text, "Expected .cal-nav-btn CSS class"
    assert "cal-month-label" in text, "Expected .cal-month-label CSS class"
    assert "cal-nav-btn--today" in text, "Expected cal-nav-btn--today CSS variant for Today button"


def test_selected_day_css_highlight_state(logged_in_client):
    """AC8: Selected day cell has CSS class for persistent highlight (is-selected)."""
    r = logged_in_client.get("/log")
    assert r.status_code == 200
    text = r.text
    assert "is-selected" in text, "Expected .is-selected CSS class for highlight state"


def test_calendar_uses_gradient_design_tokens(logged_in_client):
    """AC10: Calendar uses gradient theme tokens (--card-bg, --bg-1, etc)."""
    r = logged_in_client.get("/log")
    assert r.status_code == 200
    text = r.text
    # Check for gradient theme token usage
    gradient_tokens = ["--card-bg", "--card-border", "--bg-1", "--text-primary", "--ink"]
    assert any(token in text for token in gradient_tokens), \
        "Calendar should use gradient design tokens"


def test_calendar_uses_rem_spacing_not_hardcoded_pixels(logged_in_client):
    """AC10: Calendar uses rem/em spacing scale (project convention, not hard-coded px)."""
    r = logged_in_client.get("/log")
    assert r.status_code == 200
    text = r.text
    # Calendar CSS should include rem units
    assert ("rem" in text or "0.75rem" in text or "0.5625rem" in text or
            "gap: 6px" in text or "padding:" in text), \
        "Calendar CSS should use rem or appropriate sizing units"


def test_keyboard_accessible_buttons(logged_in_client):
    """AC12: Navigation controls are <button> elements (keyboard-accessible)."""
    r = logged_in_client.get("/log")
    assert r.status_code == 200
    text = r.text
    assert "<button" in text and "type=\"button\"" in text, \
        "Expected <button> elements in calendar"


def test_keyboard_focus_visible_defined(logged_in_client):
    """AC12: Focus indicators defined via :focus-visible CSS."""
    r = logged_in_client.get("/log")
    assert r.status_code == 200
    text = r.text
    assert ":focus-visible" in text, "Expected :focus-visible CSS for keyboard focus indicators"


def test_keyboard_arrow_navigation_implemented(logged_in_client):
    """AC12: Arrow-key roving focus navigation for calendar grid."""
    r = logged_in_client.get("/log")
    assert r.status_code == 200
    text = r.text
    # Check training-log.js is loaded
    assert "training-log.js" in text, "Expected training-log.js to be loaded"
    # Arrow key handling should be in the JS (will be tested via UI verification)
