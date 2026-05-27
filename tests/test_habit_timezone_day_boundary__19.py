"""
Tests for issue #19: Habits – correct day boundary handling using user's local timezone.
Covers AC-1 through AC-9.
Server under test: http://127.0.0.1:9001
"""
import datetime
import pathlib
import re

import httpx
import pytest

BASE = "http://127.0.0.1:9001"
TODAY = datetime.date.today()
TODAY_STR = TODAY.isoformat()

HABITS_JS   = pathlib.Path(__file__).parent.parent / "js" / "habits.js"
WEIGHT_JS   = pathlib.Path(__file__).parent.parent / "js" / "weight.js"
HABITS_HTML = pathlib.Path(__file__).parent.parent / "habits.html"
WEIGHT_HTML = pathlib.Path(__file__).parent.parent / "weight.html"
DOCS_TZ     = pathlib.Path(__file__).parent.parent / "docs" / "timezones.md"


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c


@pytest.fixture(scope="module")
def alice_id(client):
    res = client.get("/api/users")
    assert res.status_code == 200
    alice = next((u for u in res.json() if u["name"] == "Alice"), None)
    assert alice is not None, "Alice not found in /api/users"
    return alice["id"]


@pytest.fixture(scope="module")
def alice_habit_id(client, alice_id):
    res = client.get(f"/api/habits?user_id={alice_id}")
    assert res.status_code == 200
    habits = res.json()
    assert habits, "Alice has no habits"
    return habits[0]["id"]


def _date(offset: int) -> str:
    return (TODAY - datetime.timedelta(days=offset)).isoformat()


def _clean_logs_for_habit(client, user_id: str, habit_id: str, from_date: str, to_date: str):
    res = client.get(f"/api/habits/logs?user_id={user_id}&from={from_date}&to={to_date}")
    if res.status_code == 200:
        for log in res.json():
            if log["habit_id"] == habit_id:
                client.delete(f"/api/habits/logs/{log['id']}")


def _post_log(client, user_id: str, habit_id: str, logged_date: str):
    res = client.post(
        "/api/habits/logs",
        json={"habit_id": habit_id, "user_id": user_id, "logged_date": logged_date},
    )
    assert res.status_code in (201, 409), f"POST habit log failed: {res.text}"
    return res


# ── AC-1: Frontend sends logged_date as local date parts (not toISOString) ─────

def test_ac1_habits_js_uses_local_date_parts_not_toisostring():
    """habits.js must not derive today's date from toISOString(); must use local date parts."""
    content = HABITS_JS.read_text()
    # Must NOT contain toISOString() for date derivation
    assert "toISOString" not in content, (
        "habits.js still uses toISOString() — must switch to getFullYear/getMonth/getDate"
    )


def test_ac1_habits_js_has_getlocaldate_helper():
    """habits.js must define a local-date helper using getFullYear/getMonth/getDate."""
    content = HABITS_JS.read_text()
    assert "getFullYear" in content, "habits.js missing getFullYear() — local date helper not implemented"
    assert "getMonth" in content,    "habits.js missing getMonth() — local date helper not implemented"
    assert "getDate" in content,     "habits.js missing getDate() — local date helper not implemented"


def test_ac1_api_accepts_logged_date_field(client, alice_id, alice_habit_id):
    """POST /api/habits/logs with a local-date logged_date field must be accepted."""
    _clean_logs_for_habit(client, alice_id, alice_habit_id, TODAY_STR, TODAY_STR)
    res = _post_log(client, alice_id, alice_habit_id, TODAY_STR)
    assert res.status_code in (201, 409)
    # Clean up
    logs = client.get(f"/api/habits/logs?user_id={alice_id}&from={TODAY_STR}&to={TODAY_STR}").json()
    for log in logs:
        if log["habit_id"] == alice_habit_id:
            client.delete(f"/api/habits/logs/{log['id']}")


# ── AC-2: Page checks for rollover after >5 minutes ────────────────────────────

def test_ac2_habits_js_has_stale_fetch_check():
    """habits.js must check for stale fetch (>5 min) to detect date rollover."""
    content = HABITS_JS.read_text()
    # Should have a 5-minute interval or threshold (5 * 60 * 1000 ms = 300000)
    has_five_min = re.search(r"5\s*\*\s*60\s*\*\s*1000|300000|5\s*\*\s*60_000", content)
    assert has_five_min, "habits.js missing 5-minute stale-fetch check (5 * 60 * 1000)"


def test_ac2_habits_js_tracks_last_fetch_time():
    """habits.js must store a last-fetch timestamp for rollover detection."""
    content = HABITS_JS.read_text()
    assert re.search(r"lastFetch(ed)?At|lastFetch(Time)?|fetchTime", content), (
        "habits.js does not track last-fetch timestamp"
    )


# ── AC-3: Auto-refresh checkboxes when local date has changed ──────────────────

def test_ac3_habits_js_compares_stored_date_to_current():
    """habits.js must compare a stored fetch-date against the current local date."""
    content = HABITS_JS.read_text()
    assert re.search(r"lastFetch(ed)?Date|lastFetch(Date)?", content), (
        "habits.js does not store a last-fetch date for day-rollover comparison"
    )


def test_ac3_habits_js_reloads_on_date_change():
    """habits.js must call loadAndRender (or equivalent) when the date has rolled over."""
    content = HABITS_JS.read_text()
    # The rollover check should trigger a re-render / reload
    assert re.search(r"loadAndRender|softRefresh|location\.reload", content), (
        "habits.js has no reload/re-render call for date rollover"
    )


# ── AC-4: Streak uses submitted logged_date directly, no server-side tz ────────

def test_ac4_streak_uses_submitted_dates(client, alice_id, alice_habit_id):
    """Streak endpoint must return correct streak based on submitted logged_date values."""
    _clean_logs_for_habit(client, alice_id, alice_habit_id, _date(10), TODAY_STR)

    # Submit logs for yesterday and today
    _post_log(client, alice_id, alice_habit_id, _date(1))
    _post_log(client, alice_id, alice_habit_id, TODAY_STR)

    res = client.get(
        f"/api/habits/stats?user_id={alice_id}&habit_id={alice_habit_id}"
        f"&days=30&reference_date={TODAY_STR}"
    )
    assert res.status_code == 200
    data = res.json()
    assert data["streak"] >= 2, (
        f"Expected streak ≥ 2 for consecutive yesterday+today logs, got {data['streak']}"
    )

    # Clean up
    _clean_logs_for_habit(client, alice_id, alice_habit_id, _date(10), TODAY_STR)


# ── AC-5: Consecutive logged_date values form a streak ─────────────────────────

def test_ac5_consecutive_dates_form_streak(client, alice_id, alice_habit_id):
    """Three consecutive logged_date entries must produce a streak of 3."""
    _clean_logs_for_habit(client, alice_id, alice_habit_id, _date(10), TODAY_STR)

    for offset in (2, 1, 0):
        _post_log(client, alice_id, alice_habit_id, _date(offset))

    res = client.get(
        f"/api/habits/stats?user_id={alice_id}&habit_id={alice_habit_id}"
        f"&days=30&reference_date={TODAY_STR}"
    )
    assert res.status_code == 200
    assert res.json()["streak"] >= 3, (
        f"Expected streak ≥ 3 for 3 consecutive days, got {res.json()['streak']}"
    )

    _clean_logs_for_habit(client, alice_id, alice_habit_id, _date(10), TODAY_STR)


def test_ac5_gap_breaks_streak(client, alice_id, alice_habit_id):
    """A gap in logged_date values must reset the streak."""
    _clean_logs_for_habit(client, alice_id, alice_habit_id, _date(10), TODAY_STR)

    # Log day -3 and today, skipping day -2 and day -1
    _post_log(client, alice_id, alice_habit_id, _date(3))
    _post_log(client, alice_id, alice_habit_id, TODAY_STR)

    res = client.get(
        f"/api/habits/stats?user_id={alice_id}&habit_id={alice_habit_id}"
        f"&days=30&reference_date={TODAY_STR}"
    )
    assert res.status_code == 200
    assert res.json()["streak"] == 1, (
        f"Expected streak = 1 after gap, got {res.json()['streak']}"
    )

    _clean_logs_for_habit(client, alice_id, alice_habit_id, _date(10), TODAY_STR)


# ── AC-6: "Last refreshed: HH:MM (timezone)" stamp on habits page ──────────────

def test_ac6_habits_html_has_last_refreshed_element():
    """habits.html must contain an element for the 'Last refreshed' timestamp."""
    content = HABITS_HTML.read_text()
    assert re.search(r'id=["\']habits-last-refreshed["\']|id=["\']last-refreshed["\']', content), (
        "habits.html is missing a #last-refreshed or #habits-last-refreshed element"
    )


def test_ac6_habits_js_populates_last_refreshed():
    """habits.js must write 'Last refreshed: HH:MM (tz)' into the refresh element."""
    content = HABITS_JS.read_text()
    assert re.search(r"Last refreshed", content), (
        "habits.js does not write 'Last refreshed' text"
    )
    assert re.search(r"Intl\.DateTimeFormat|timeZone", content), (
        "habits.js does not include timezone name in the refresh timestamp"
    )


# ── AC-7: "Days logged this week" on weight page uses local-date convention ─────

def test_ac7_weight_html_has_days_logged_card():
    """weight.html must contain a 'Days logged' (this week) summary card."""
    content = WEIGHT_HTML.read_text()
    assert re.search(r"[Dd]ays\s+logged", content), (
        "weight.html missing 'Days logged' card text"
    )


def test_ac7_weight_js_uses_local_date_not_toisostring():
    """weight.js must not use toISOString() for date logic; must use local date parts."""
    content = WEIGHT_JS.read_text()
    assert "toISOString" not in content, (
        "weight.js still uses toISOString() — must use local date parts"
    )
    assert "getFullYear" in content or re.search(r"todayISO|localDateString|isoDateStr", content), (
        "weight.js must derive today's date from local date parts"
    )


# ── AC-8: setTimeout fires soft refresh at local midnight; cleared on navigate ──

def test_ac8_habits_js_has_midnight_settimeout():
    """habits.js must schedule a setTimeout targeting the next local midnight."""
    content = HABITS_JS.read_text()
    assert "setTimeout" in content, "habits.js has no setTimeout for midnight refresh"
    # Must compute ms until midnight using local date arithmetic
    assert re.search(r"midnight|msUntil|getDate\(\)\s*\+\s*1|new Date.*\+\s*1", content), (
        "habits.js setTimeout does not appear to target local midnight"
    )


def test_ac8_habits_js_clears_timeout_on_navigate_away():
    """habits.js must call clearTimeout when the user navigates away."""
    content = HABITS_JS.read_text()
    assert "clearTimeout" in content, "habits.js has no clearTimeout call"
    # Must clear on pagehide, beforeunload, or visibilitychange
    assert re.search(r"pagehide|beforeunload|visibilitychange", content), (
        "habits.js does not register a pagehide/beforeunload/visibilitychange listener to clear the timer"
    )


# ── AC-9: docs/timezones.md documents local-date convention ────────────────────

def test_ac9_docs_timezones_md_exists():
    """docs/timezones.md must exist."""
    assert DOCS_TZ.exists(), "docs/timezones.md does not exist"


def test_ac9_timezones_md_documents_local_date_convention():
    """docs/timezones.md must state that Perf Coach uses the user's local date."""
    content = DOCS_TZ.read_text()
    assert re.search(r"local\s+date", content, re.IGNORECASE), (
        "docs/timezones.md does not mention 'local date'"
    )
    assert re.search(r"daily\s+reset|reset\s+logic|day.*reset", content, re.IGNORECASE), (
        "docs/timezones.md does not document daily reset logic"
    )


def test_ac9_timezones_md_mentions_submission_time():
    """docs/timezones.md must state records are interpreted as the user's local date at submission."""
    content = DOCS_TZ.read_text()
    assert re.search(r"submission\s+time|submitted|at submission", content, re.IGNORECASE), (
        "docs/timezones.md does not mention that dates are the user's local date at submission time"
    )
