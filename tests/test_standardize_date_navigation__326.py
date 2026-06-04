"""Tests for issue #326: Standardize date navigation across Home, Training Log, and Calendar.

Acceptance criteria verified:
(a) Home Log Today card has prev/next/Today buttons with correct markup
(b) Today button is disabled+highlighted when already on today's date
(c) addISODays helper and navigateDateTo function exist in home.js
(d) Training Log week strip has a Today button, disabled when current week shown
(e) Calendar Today button is disabled/enabled based on current month via updateTodayBtn
(f) Calendar Today button CSS handles :disabled state
(g) Training-log edit link uses /training?edit=<id>&return=<url> (not /workout-edit/)
(h) training.js reads ?return= param after save and uses location.replace
(i) Return URL validation rejects non-root-relative paths (security guard)
(j) Static HTML pages load OK from server
"""
import pathlib
import re

import httpx
import pytest

BASE = "http://127.0.0.1:9005"

_REPO = pathlib.Path(__file__).resolve().parents[1]
_CODER = pathlib.Path("/Users/chaiwutchaianuchittrakul/dev/perf-coach/coder")

_HOME_HTML = _CODER / "frontend" / "pages" / "home.html"
_HOME_JS   = _CODER / "frontend" / "js" / "home.js"
_TLOG_HTML = _CODER / "frontend" / "pages" / "training-log.html"
_TLOG_JS   = _CODER / "frontend" / "js" / "training-log.js"
_CAL_HTML  = _CODER / "frontend" / "pages" / "calendar.html"
_CAL_JS    = _CODER / "frontend" / "js" / "calendar.js"
_TRAIN_JS  = _CODER / "frontend" / "js" / "training.js"


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c


# ── (a) Home: prev/next/Today buttons present in renderLogTodayCard ───────────

def test_home_js_has_lt_date_nav_wrapper():
    js = _HOME_JS.read_text()
    assert 'lt-date-nav' in js, "Expected .lt-date-nav wrapper div in home.js"


def test_home_js_has_prev_button():
    js = _HOME_JS.read_text()
    assert 'lt-prev-btn' in js, "Expected #lt-prev-btn in home.js"
    assert 'aria-label="Previous day"' in js or "Previous day" in js


def test_home_js_has_next_button():
    js = _HOME_JS.read_text()
    assert 'lt-next-btn' in js, "Expected #lt-next-btn in home.js"
    assert 'aria-label="Next day"' in js or "Next day" in js


def test_home_js_has_today_button():
    js = _HOME_JS.read_text()
    assert 'lt-today-btn' in js, "Expected #lt-today-btn in home.js"
    assert '>Today<' in js or "'Today'" in js or '"Today"' in js


def test_home_html_has_nav_button_css():
    html = _HOME_HTML.read_text()
    assert '.lt-nav-btn' in html, "Expected .lt-nav-btn CSS in home.html"
    assert '.lt-today-btn' in html, "Expected .lt-today-btn CSS in home.html"
    assert '.lt-date-nav' in html, "Expected .lt-date-nav CSS in home.html"


# ── (b) Today button disabled+highlighted when on today ──────────────────────

def test_home_js_today_btn_disabled_when_on_today():
    js = _HOME_JS.read_text()
    assert 'isOnToday' in js, "Expected isOnToday variable in home.js"
    # Today btn gets disabled attr when isOnToday
    assert "isOnToday ? ' disabled'" in js or "isOnToday?'disabled'" in js or \
           "(isOnToday ? ' disabled' : '')" in js, \
        "Expected conditional disabled attribute on Today button based on isOnToday"


def test_home_js_today_btn_active_class_when_on_today():
    js = _HOME_JS.read_text()
    assert 'lt-today-btn--active' in js, \
        "Expected lt-today-btn--active class applied when isOnToday"


def test_home_html_today_btn_active_css():
    html = _HOME_HTML.read_text()
    assert 'lt-today-btn--active' in html, \
        "Expected .lt-today-btn--active CSS rule in home.html"


def test_home_html_next_btn_disabled_when_on_today():
    """Next-day button must be disabled when already on today (can't go forward)."""
    js = _HOME_JS.read_text()
    # The next btn gets disabled when isOnToday
    assert "isOnToday ? ' disabled'" in js or \
           "(isOnToday ? ' disabled' : '')" in js, \
        "Expected next-btn to be conditionally disabled when isOnToday"


# ── (c) addISODays helper and navigateDateTo exist ───────────────────────────

def test_home_js_has_add_iso_days_helper():
    js = _HOME_JS.read_text()
    assert 'addISODays' in js, "Expected addISODays helper function in home.js"
    assert 'setDate' in js, "addISODays should use setDate for day arithmetic"


def test_home_js_has_navigate_date_to():
    js = _HOME_JS.read_text()
    assert 'navigateDateTo' in js, "Expected navigateDateTo function in home.js"
    assert 'renderLogTodayCard' in js, \
        "navigateDateTo must call renderLogTodayCard to re-render the card"


def test_home_js_prev_calls_navigate_minus_one():
    js = _HOME_JS.read_text()
    assert 'addISODays(selectedDate, -1)' in js, \
        "Prev button must call navigateDateTo(addISODays(selectedDate, -1))"


def test_home_js_next_calls_navigate_plus_one():
    js = _HOME_JS.read_text()
    assert 'addISODays(selectedDate, 1)' in js, \
        "Next button must call navigateDateTo(addISODays(selectedDate, 1))"


def test_home_js_today_nav_btn_calls_navigate_today():
    js = _HOME_JS.read_text()
    assert 'navigateDateTo(todayStr)' in js, \
        "Today button must call navigateDateTo(todayStr)"


# ── (d) Training Log: Today button in week strip ──────────────────────────────

def test_training_log_js_has_week_today_button():
    js = _TLOG_JS.read_text()
    assert 'week-today' in js, "Expected #week-today button in training-log.js"


def test_training_log_js_week_today_disabled_when_current_week():
    js = _TLOG_JS.read_text()
    assert 'isCurrentWeek' in js, "Expected isCurrentWeek variable in training-log.js"
    assert "isCurrentWeek ? ' disabled'" in js or \
           "(isCurrentWeek ? ' disabled' : '')" in js, \
        "week-today button must be disabled when isCurrentWeek is true"


def test_training_log_js_uses_week_contains_today():
    js = _TLOG_JS.read_text()
    assert 'weekContainsToday' in js, \
        "Expected weekContainsToday() call to determine isCurrentWeek"


def test_training_log_js_today_click_goes_to_current_monday():
    js = _TLOG_JS.read_text()
    assert 'getMondayOf(new Date())' in js or 'getMondayOf' in js, \
        "Today click handler must compute current Monday via getMondayOf"
    assert "week-today" in js and "addEventListener" in js


def test_training_log_html_has_today_btn_css():
    html = _TLOG_HTML.read_text()
    assert '.ws-today-btn' in html, "Expected .ws-today-btn CSS in training-log.html"


def test_training_log_html_today_btn_disabled_css():
    html = _TLOG_HTML.read_text()
    assert 'ws-today-btn:disabled' in html or \
           '.ws-today-btn:disabled' in html or \
           'ws-today-btn:hover:not(:disabled)' in html, \
        "Expected :disabled CSS for .ws-today-btn in training-log.html"


# ── (e) Calendar: updateTodayBtn disables Today when on current month ─────────

def test_calendar_js_has_update_today_btn():
    js = _CAL_JS.read_text()
    assert 'updateTodayBtn' in js, "Expected updateTodayBtn function in calendar.js"


def test_calendar_js_checks_current_month():
    js = _CAL_JS.read_text()
    assert 'isCurrentMonth' in js, "Expected isCurrentMonth check in updateTodayBtn"
    assert 'btn.disabled' in js or 'btn.disabled =' in js, \
        "updateTodayBtn must set btn.disabled based on isCurrentMonth"


def test_calendar_js_update_today_btn_called_in_render():
    js = _CAL_JS.read_text()
    render_pos = js.find('function render()')
    assert render_pos != -1, "render() function not found in calendar.js"
    # updateTodayBtn must appear within 500 chars after 'function render()' opening
    snippet = js[render_pos:render_pos + 500]
    assert 'updateTodayBtn' in snippet, \
        "render() must call updateTodayBtn() near the top of its body"


# ── (f) Calendar Today button disabled CSS ────────────────────────────────────

def test_calendar_html_today_btn_disabled_css():
    html = _CAL_HTML.read_text()
    assert 'cal-today-btn:disabled' in html or \
           '.cal-today-btn:disabled' in html, \
        "Expected .cal-today-btn:disabled CSS rule in calendar.html"


def test_calendar_html_today_btn_hover_not_disabled():
    """Hover effect must not apply when button is disabled."""
    html = _CAL_HTML.read_text()
    assert ':hover:not(:disabled)' in html or 'hover:not(:disabled)' in html, \
        "Expected :hover:not(:disabled) selector in calendar.html (disabled btn should not show hover)"


# ── (g) Training Log edit link uses /training?edit=<id>&return=<url> ─────────

def test_training_log_js_edit_link_uses_training_route():
    js = _TLOG_JS.read_text()
    assert "'/training?edit='" in js or '"/training?edit="' in js or \
           '/training?edit=' in js, \
        "Edit link must use /training?edit=<id> route, not /workout-edit/"


def test_training_log_js_edit_link_includes_return_param():
    js = _TLOG_JS.read_text()
    assert "returnUrl" in js, "Expected returnUrl variable in training-log.js"
    assert "encodeURIComponent(returnUrl)" in js, \
        "Return URL must be encodeURIComponent-encoded in the edit link"


def test_training_log_js_return_url_includes_week_param():
    js = _TLOG_JS.read_text()
    assert "'/log?week='" in js or '"/log?week="' in js or \
           '/log?week=' in js, \
        "returnUrl must include /log?week=<monday> to return to correct week"


def test_training_log_js_no_workout_edit_route():
    js = _TLOG_JS.read_text()
    assert '/workout-edit/' not in js, \
        "training-log.js must not reference the deprecated /workout-edit/ route"


# ── (h) training.js reads ?return= param and uses location.replace ────────────

def test_training_js_reads_return_param():
    js = _TRAIN_JS.read_text()
    assert "returnParam" in js or '.get(\'return\')' in js or '.get("return")' in js, \
        "training.js must read the ?return= query parameter after save"


def test_training_js_uses_location_replace_not_href():
    js = _TRAIN_JS.read_text()
    assert 'location.replace' in js, \
        "training.js must use location.replace() for post-save redirect (clean history)"
    # Ensure the OLD pattern (location.href = '/log') is gone
    assert "location.href = '/log'" not in js and \
           'location.href="/log"' not in js, \
        "Old location.href = '/log' redirect must be replaced with location.replace(dest)"


# ── (i) Return param security: only root-relative paths accepted ──────────────

def test_training_js_return_param_validates_leading_slash():
    js = _TRAIN_JS.read_text()
    assert '/^\\//' in js or "test(returnParam)" in js or \
           "returnParam && /^\\/" in js or "returnParam&&/^\\/" in js, \
        "Return param must be validated to start with / (prevent open redirect)"


def test_training_js_fallback_to_log_on_bad_return():
    js = _TRAIN_JS.read_text()
    assert "'/log'" in js or '"/log"' in js, \
        "training.js must fall back to /log when return param is absent/invalid"


# ── (j) Pages served correctly by server ─────────────────────────────────────

def test_home_page_reachable(client):
    """/ returns 200 (authenticated) or 302 to /login — route must exist."""
    res = client.get("/")
    assert res.status_code in (200, 302), f"/ returned {res.status_code}"
    if res.status_code == 302:
        assert "/login" in res.headers.get("location", ""), \
            "Unexpected redirect target from /"


def test_training_log_page_reachable(client):
    res = client.get("/log")
    assert res.status_code in (200, 302), f"/log returned {res.status_code}"


def test_calendar_page_reachable(client):
    res = client.get("/calendar")
    assert res.status_code in (200, 302), f"/calendar returned {res.status_code}"


def test_training_page_reachable(client):
    res = client.get("/training")
    assert res.status_code in (200, 302), f"/training returned {res.status_code}"
