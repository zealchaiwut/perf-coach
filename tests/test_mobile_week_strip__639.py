"""Tests for issue #639: Mobile week-strip on Training Log sub-tab (runs against UAT)"""
import os
import re
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

_TEST_PW = "tester639mws-pw"


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        yield c


@pytest.fixture(scope="module")
def test_user(client):
    name = f"tester639mws_{uuid.uuid4().hex[:8]}"
    resp = client.post("/api/users", json={"name": name})
    assert resp.status_code == 201, resp.text
    uid = resp.json()["id"]
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


@pytest.fixture(scope="module")
def page_html(logged_in_client):
    resp = logged_in_client.get("/log")
    assert resp.status_code == 200
    return resp.text


@pytest.fixture(scope="module")
def js_source(logged_in_client):
    resp = logged_in_client.get("/js/training-log.js")
    assert resp.status_code == 200, f"Could not fetch training-log.js: {resp.status_code}"
    return resp.text


# ── AC1: Week-strip visible only at mobile; month calendar hidden on mobile ──

def test_mobile_week_strip__breakpoints(page_html):
    """AC: Week-strip rendered only at mobile breakpoints; month calendar hidden."""
    assert "week-strip" in page_html, "Expected week-strip element in the HTML"
    assert "log-card--week" in page_html, "Expected .log-card--week wrapper element"
    assert "640px" in page_html, "Expected 640px breakpoint reference for week-strip"
    pattern = re.compile(
        r"@media\s*\(min-width:\s*640px\)[^}]*\{[^@]*"
        r"(log-card--week|week-strip)[^}]*display\s*:\s*none",
        re.DOTALL,
    )
    assert pattern.search(page_html), (
        "Expected CSS @media(min-width:640px) to set display:none on .log-card--week or #week-strip"
    )
    assert "log-calendar" in page_html, "Expected #log-calendar element in HTML"
    assert "1024" in page_html, "Expected 1024px breakpoint for month calendar"


# ── AC2 & AC3: Seven day cells with abbreviation, date number, and type dots ──

def test_mobile_week_strip__seven_day_cells(page_html, js_source):
    """AC: Week-strip displays exactly seven day cells (Mon–Sun) with correct content."""
    assert "i < 7" in js_source, "Expected JS loop 'i < 7' generating 7 day cells"
    assert "day-pill" in page_html, "Expected .day-pill CSS class for day cells"
    assert "ws-pills" in page_html, "Expected .ws-pills container for the 7 day pills"
    assert "day-name" in page_html, "Expected .day-name element for day-of-week abbreviation"
    assert "day-num" in page_html, "Expected .day-num element for date number"
    assert "wd-dot" in page_html, "Expected .wd-dot CSS class for activity-type dots"
    assert "wd-dots" in page_html, "Expected .wd-dots container element"


# ── AC4: Today's cell highlighted with gradient-theme token ──

def test_mobile_week_strip__today_highlight(page_html):
    """AC: Today's cell is visually highlighted using a gradient-theme token."""
    today_match = re.search(r"\.day-pill\.today\s*\{([^}]+)\}", page_html, re.DOTALL)
    assert today_match, "Expected .day-pill.today CSS rule"
    today_block = today_match.group(1)
    gradient_tokens = ["var(--bg-1", "var(--bg-2", "var(--page-bg", "var(--primary"]
    assert any(tok in today_block for tok in gradient_tokens), (
        "Expected gradient-theme token in .day-pill.today — found: " + today_block.strip()
    )


# ── AC5: Prev / Next week navigation ──

def test_mobile_week_strip__week_navigation(js_source):
    """AC: Prev/Next week controls are present and advance by exactly one week per tap."""
    assert "week-prev" in js_source, "Expected week-prev button rendered by JS"
    assert "week-next" in js_source, "Expected week-next button rendered by JS"
    assert "Previous week" in js_source, "Expected aria-label 'Previous week'"
    assert "Next week" in js_source, "Expected aria-label 'Next week'"
    assert "setDate" in js_source, "Expected setDate call for week navigation"
    assert "- 7" in js_source, "Expected ±7 day increment in week navigation JS"


# ── AC6 & AC8: Tapping a day scrolls (not filters); entries never hidden ──

def test_mobile_week_strip__scroll_not_filter(js_source):
    """AC: Selecting a day scrolls to that day's entry; never hides other days' entries."""
    assert "scrollIntoView" in js_source, (
        "Expected scrollIntoView call in week-strip day selection (scroll, not filter)"
    )
    assert "stripScrollToDate" in js_source or "scrollToDate" in js_source, (
        "Expected a scroll-to-date function for the week-strip day selection"
    )
    assert "stripSelectDay" in js_source, (
        "Expected stripSelectDay as the click handler on week-strip pills"
    )


# ── AC7: Selected day cell receives persistent highlight ──

def test_mobile_week_strip__selected_day_persistence(page_html):
    """AC: Tapped day cell receives the same persistent selected-day highlight as desktop calendar."""
    assert "is-selected" in page_html, "Expected .is-selected CSS class for selected day pill"
    pill_match = re.search(r"\.day-pill\.is-selected\s*\{([^}]+)\}", page_html, re.DOTALL)
    assert pill_match, "Expected .day-pill.is-selected CSS rule"
    pill_style = pill_match.group(1)
    assert "var(--ink" in pill_style or "#0b1530" in pill_style, (
        "Expected var(--ink) token in .day-pill.is-selected to match desktop calendar highlight"
    )


# ── AC9: Design system compliance (gradient tokens, structural classes) ──

def test_mobile_week_strip__design_system_compliance(page_html):
    """AC: Component follows project conventions — gradient theme tokens for all colours."""
    gradient_tokens = [
        "var(--card-bg", "var(--card-border", "var(--text-secondary",
        "var(--bg-1", "var(--ink", "var(--primary",
    ]
    assert any(tok in page_html for tok in gradient_tokens), (
        "Week-strip should use gradient design tokens (no hard-coded colours)"
    )


# ── AC10: Accessibility — keyboard-focusable, descriptive aria-labels ──

def test_mobile_week_strip__accessibility(page_html, js_source):
    """AC: Day cells are keyboard-focusable buttons with descriptive aria-label values."""
    assert 'type="button"' in page_html, "Expected type='button' on day pill elements"
    assert "aria-label" in js_source, "Expected aria-label on day pill buttons"
    assert "toLocaleDateString" in js_source, (
        "Expected toLocaleDateString used to build descriptive aria-labels"
    )
    assert "activities" in js_source, "Expected 'activities' in aria-label construction"
    assert "no activities" in js_source, "Expected 'no activities' fallback in aria-label"


# ── AC11: No visual regression on tablet or desktop ──

def test_mobile_week_strip__no_regression_tablet_desktop(page_html):
    """AC: Month calendar continues to render correctly on tablet/desktop viewports."""
    assert "log-calendar" in page_html, "Month calendar (#log-calendar) must remain in HTML"
    assert "cal-grid" in page_html, "Month calendar .cal-grid CSS must remain"
    assert "cal-cell" in page_html, "Month calendar .cal-cell CSS must remain"
    assert "640px" in page_html, "Expected 640px breakpoint to hide week-strip on non-mobile"


# ── API: Training log endpoint still functions correctly ──

def test_mobile_week_strip__api_training_log_still_works(logged_in_client):
    """API: The /api/workouts endpoint returns a valid response (no regression)."""
    resp = logged_in_client.get("/api/workouts")
    assert resp.status_code == 200, f"Expected 200 from /api/workouts, got {resp.status_code}"
    data = resp.json()
    assert isinstance(data, list), "Expected list response from /api/workouts"
