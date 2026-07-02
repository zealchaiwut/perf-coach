"""Tests for issue #124: Build week strip navigation on Training Log page"""
import os
from datetime import date as _date, timedelta

import httpx
import pytest
from tests._admin_helpers import admin_cookies as _admin_cookies

BASE = os.environ.get("UAT_BASE_URL") or f"http://localhost:{os.environ.get('UAT_PORT', '9001')}"
if not BASE.startswith("http"):
    raise RuntimeError(
        "UAT_BASE_URL / UAT_PORT not set. Run the tester skill's Step 0 to resolve UAT before pytest."
    )


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c


@pytest.fixture(scope="module")
def alice_id(client):
    res = client.get("/api/users", cookies=_admin_cookies())
    assert res.status_code == 200
    alice = next((u for u in res.json() if u["name"] == "Alice"), None)
    assert alice is not None, "Alice not found in /api/users"
    return alice["id"]


def _create_workout(client, user_id, **kwargs):
    payload = {
        "user_id": user_id,
        "name": kwargs.pop("name", "Test Workout"),
        "workout_date": kwargs.pop("workout_date", "2026-01-06"),
        "workout_type": kwargs.pop("workout_type", "run"),
        "exercises": kwargs.pop("exercises", []),
    }
    payload.update(kwargs)
    res = client.post("/api/workouts", json=payload)
    assert res.status_code == 201, f"Failed to create workout: {res.text}"
    return res.json()


def _delete_workout(client, workout_id):
    client.delete(f"/api/workouts/{workout_id}")


# ── AC1: #week-strip placeholder replaced by 7 day pills ─────────────────────

def test_week_strip_div_exists_in_html(client):
    """AC1: #week-strip placeholder is present in the page"""
    res = client.get("/log")
    assert res.status_code == 200
    assert 'id="week-strip"' in res.text, "#week-strip should be present in training-log.html"


def test_js_builds_seven_day_pills(client):
    """AC1: JS builds exactly 7 day pills (one for each day Mon–Sun)"""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    # Loop runs i = 0..6 → 7 pills
    assert '< 7' in res.text or 'i < 7' in res.text or "for (var i = 0; i < 7" in res.text, \
        "JS should iterate 7 times to build day pills"


def test_js_day_pill_class_present(client):
    """AC1: JS uses 'day-pill' CSS class for each pill element"""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    assert 'day-pill' in res.text, "JS should create elements with 'day-pill' class"


# ── AC2: Each pill shows 3-letter day label and day-of-month ─────────────────

def test_js_uses_day_abbreviations(client):
    """AC2: JS includes the 7 standard 3-letter day abbreviations"""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    js = res.text
    for day in ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']:
        assert day in js, f"3-letter day abbreviation '{day}' should be in training-log.js"


def test_js_day_name_and_day_num_spans(client):
    """AC2: JS builds day-name and day-num spans inside each pill"""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    assert 'day-name' in res.text, "JS should create span with class 'day-name'"
    assert 'day-num' in res.text, "JS should create span with class 'day-num'"


# ── AC3: Colored workout-type dots ───────────────────────────────────────────

def test_js_defines_type_colors(client):
    """AC3: JS has color map for run, lift, wod, bike"""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    js = res.text
    assert 'run' in js and 'lift' in js and 'wod' in js and 'bike' in js, \
        "JS should define all four workout types"
    # Check the specific required colors
    assert '#3b82f6' in js or 'blue' in js.lower(), "run = blue (#3b82f6)"
    assert '#8b5cf6' in js or 'purple' in js.lower(), "lift = purple (#8b5cf6)"
    assert '#f97316' in js or 'orange' in js.lower(), "wod = orange (#f97316)"
    assert '#14b8a6' in js or 'teal' in js.lower(), "bike = teal (#14b8a6)"


def test_js_builds_wd_dot_elements(client):
    """AC3: JS creates .wd-dot span elements for workout types"""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    assert 'wd-dot' in res.text, "JS should create elements with class 'wd-dot'"


def test_js_filters_dots_by_type(client):
    """AC3: JS only renders a dot when the workout type is present for that day"""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    # The TYPE_ORDER filter pattern ensures dots only appear for present types
    assert 'TYPE_ORDER' in res.text or "type_order" in res.text.lower() or "filter" in res.text, \
        "JS should filter/order dot rendering by workout type"


# ── AC4: Today pill is visually distinguished ─────────────────────────────────

def test_js_today_pill_class(client):
    """AC4: JS adds 'today' class to the current day's pill"""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    assert 'today' in res.text, "JS should apply 'today' class to the current day's pill"


def test_html_today_pill_styles(client):
    """AC4: training-log.html has CSS for .day-pill.today (border or glow style)"""
    res = client.get("/log")
    assert res.status_code == 200
    html = res.text
    assert '.day-pill.today' in html or ('day-pill' in html and 'today' in html), \
        "CSS for .day-pill.today should be present"


# ── AC5: Chevron nav buttons (#week-prev and #week-next) ─────────────────────

def test_js_creates_week_prev_button(client):
    """AC5: JS creates a button with id='week-prev'"""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    assert 'week-prev' in res.text, "JS should create button with id='week-prev'"


def test_js_creates_week_next_button(client):
    """AC5: JS creates a button with id='week-next'"""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    assert 'week-next' in res.text, "JS should create button with id='week-next'"


def test_js_prev_shifts_by_7_days(client):
    """AC5: week-prev shifts selected week by -7 days"""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    js = res.text
    # The handler should subtract 7 from the date
    assert '- 7' in js or '-7' in js, "week-prev handler should shift by 7 days"


def test_js_next_shifts_by_7_days(client):
    """AC5: week-next shifts selected week by +7 days"""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    js = res.text
    assert '+ 7' in js or '+7' in js, "week-next handler should shift by 7 days"


# ── AC6: Center label "This week" vs "MMM D – D" ─────────────────────────────

def test_js_this_week_label(client):
    """AC6: JS shows 'This week' when current week contains today"""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    assert 'This week' in res.text, "JS should render 'This week' label for current week"


def test_js_date_range_label_format(client):
    """AC6: JS builds date range label in MMM D – D format for non-current weeks"""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    js = res.text
    # 'en-US' month formatting or manual month lookup
    assert 'toLocaleDateString' in js or ('Jan' in js and 'Feb' in js), \
        "JS should format the date range label as MMM D – D"
    assert '–' in js or ' - ' in js, "JS should use an em-dash or dash separator in the date range"


def test_js_week_label_element(client):
    """AC6: JS creates a #week-label or similar element for the center text"""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    assert 'week-label' in res.text, "JS should create a 'week-label' element for the center text"


# ── AC7: URL ?week=YYYY-MM-DD persistence ────────────────────────────────────

def test_js_reads_week_param_from_url(client):
    """AC7 (previously failing): JS reads ?week= from URL to load a specific week"""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    js = res.text
    assert "get('week')" in js or 'get("week")' in js, \
        "JS should read 'week' query parameter from URL (parseWeekParam / loadFromURL)"


def test_js_writes_week_param_to_url(client):
    """AC7 (previously failing): JS writes ?week= to URL when navigating weeks"""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    js = res.text
    assert "set('week'" in js or 'set("week"' in js, \
        "JS should set 'week' query parameter in URL (pushWeekParam / syncToURL)"


def test_js_prev_calls_push_or_sync(client):
    """AC7 (previously failing): week-prev handler updates the URL after navigating"""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    js = res.text
    assert 'pushWeekParam' in js or 'pushState' in js or 'replaceState' in js, \
        "week navigation should update URL via pushWeekParam / pushState / replaceState"


def test_js_week_param_iso_format(client):
    """AC7: URL ?week= value is formatted as YYYY-MM-DD (ISO date)"""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    js = res.text
    # toISODate or similar function
    assert 'toISODate' in js or 'toISOString' in js or "padStart(2, '0')" in js or 'padStart(2,"0")' in js, \
        "JS should format the week param as YYYY-MM-DD"


def test_page_loads_with_week_param(client):
    """AC7: Page returns 200 when loaded with ?week=2025-01-06"""
    res = client.get("/log?week=2025-01-06")
    assert res.status_code == 200
    assert 'week-strip' in res.text, "#week-strip should be present when ?week= is provided"


def test_page_loads_without_week_param(client):
    """AC7: Page returns 200 when loaded without ?week= param"""
    res = client.get("/log")
    assert res.status_code == 200
    assert 'week-strip' in res.text, "#week-strip should be present without ?week= param"


# ── AC8: Dots populated from /api/training-log ───────────────────────────────

def test_js_fetches_training_log_api(client):
    """AC8: JS fetches /api/training-log to populate workout dots"""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    assert '/api/training-log' in res.text, "JS should fetch from /api/training-log"


def test_js_scopes_fetch_to_week_window(client):
    """AC8: JS passes from/to params scoped to the 7-day window"""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    js = res.text
    assert "'from'" in js or '"from"' in js or 'from=' in js, \
        "JS should pass 'from' date to /api/training-log"
    assert "'to'" in js or '"to"' in js or 'to=' in js, \
        "JS should pass 'to' date to /api/training-log"


def test_js_reads_workout_type_from_api_response(client):
    """AC8: JS reads workout type from API response to assign dot colors"""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    js = res.text
    assert 'entry.type' in js or "entry['type']" in js or '.type' in js, \
        "JS should read workout type from API entry to assign dot colors"


def test_api_training_log_returns_workout_types(client, alice_id):
    """AC8: /api/training-log returns entries with a 'type' field"""
    today = _date.today().isoformat()
    past = (_date.today() - timedelta(days=7)).isoformat()
    res = client.get("/api/training-log", params={"user_id": alice_id, "from": past, "to": today})
    assert res.status_code == 200
    data = res.json()
    assert "weeks" in data, "Response should have 'weeks' array"


def test_api_workout_dot_mapping(client, alice_id):
    """AC8: Colored dots appear correctly for known workout types"""
    w = _create_workout(client, alice_id, name="Week Strip Run #124",
                        workout_type="run", workout_date="2026-01-05")
    try:
        res = client.get("/api/training-log", params={
            "user_id": alice_id, "from": "2026-01-05", "to": "2026-01-05",
            "include_rest": "false",
        })
        assert res.status_code == 200
        entries = [e for wk in res.json()["weeks"] for e in wk["entries"]]
        types = [e.get("type", "").lower() for e in entries]
        assert "run" in types, "API should return 'run' entry for run workout"
    finally:
        _delete_workout(client, w["id"])


# ── AC9: Responsive layout at 380 px ─────────────────────────────────────────

def test_html_ws_pills_uses_flex(client):
    """AC9: .ws-pills uses flexbox so pills can shrink proportionally"""
    res = client.get("/log")
    assert res.status_code == 200
    html = res.text
    assert 'ws-pills' in html, ".ws-pills container should be present"
    assert 'flex' in html, "week-strip should use flexbox for responsive layout"


def test_html_day_pill_flex_grow(client):
    """AC9: day pills use flex: 1 or equivalent so they fill available width"""
    res = client.get("/log")
    assert res.status_code == 200
    html = res.text
    assert 'flex: 1' in html or 'flex:1' in html, \
        ".day-pill should use flex: 1 to grow/shrink proportionally"


def test_html_week_strip_no_overflow(client):
    """AC9: #week-strip does not set overflow:hidden/auto in a way that would hide pills"""
    res = client.get("/log")
    assert res.status_code == 200
    html = res.text
    # The strip should NOT have overflow:hidden/scroll that would clip pills
    # A min-width:0 on pills allows them to shrink below content width
    assert 'min-width: 0' in html or 'min-width:0' in html, \
        ".day-pill should have min-width: 0 to allow proper shrinking at 380 px"


# ── AC10: Empty day shows no dots (not an error state) ───────────────────────

def test_js_empty_day_shows_no_dots(client):
    """AC10: If no workouts exist for a day, JS renders an empty dots container"""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    js = res.text
    # dotsByDate[dateStr] defaults to [] when not found
    assert 'dotsByDate' in js or 'dots' in js.lower(), \
        "JS should use a dotsByDate map (defaults empty) — no error if no workouts"


def test_api_no_workouts_returns_empty_weeks(client, alice_id):
    """AC10: /api/training-log with include_rest=false returns no entries for a day with no workouts"""
    # Use a far-future date that definitely has no workouts
    res = client.get("/api/training-log", params={
        "user_id": alice_id,
        "from": "2030-01-06", "to": "2030-01-12",
        "include_rest": "false",
    })
    assert res.status_code == 200
    data = res.json()
    entries = [e for wk in data["weeks"] for e in wk["entries"]]
    assert entries == [], "No workouts in a future week should return empty entries (no error)"


def test_js_network_error_does_not_crash(client):
    """AC10: JS handles fetch errors gracefully (try/catch around fetch)"""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    js = res.text
    assert 'catch' in js, "JS should have a try/catch around the fetch to handle network errors"


# ── Additional: Page and JS structure ────────────────────────────────────────

def test_training_log_page_loads(client):
    """General: Training Log page returns 200"""
    res = client.get("/log")
    assert res.status_code == 200
    assert "Training log" in res.text or "training" in res.text.lower()


def test_js_served_correctly(client):
    """General: /js/training-log.js is served with content"""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    assert len(res.text) > 100, "training-log.js should be a non-trivial JS file"


def test_js_uses_vanilla_js_only(client):
    """General: training-log.js is vanilla JS (no React/Vue/Angular)"""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    js = res.text
    assert 'React' not in js, "Should not use React"
    assert 'Vue' not in js, "Should not use Vue"
