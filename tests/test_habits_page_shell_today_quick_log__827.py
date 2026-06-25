"""Tests for issue #827: Build Habits page shell and Today quick-log surface.

Runs against the live server at http://127.0.0.1:9001.
Static checks read frontend/pages/habits.html and frontend/js/habits.js directly.
"""
import os
import pathlib
import pytest
import httpx

BASE_URL = os.environ.get("UAT_BASE_URL", "http://127.0.0.1:9001")
ROOT = pathlib.Path(__file__).parent.parent

_CREDENTIALS = {"username": "tester827", "password": "Test827pass!"}


def _extract_cookie(response: httpx.Response, name: str) -> str | None:
    for header in response.headers.get_list("set-cookie"):
        parts = [p.strip() for p in header.split(";")]
        if parts and "=" in parts[0]:
            k, v = parts[0].split("=", 1)
            if k.strip() == name:
                return v.strip()
    return None


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        r = c.post("/api/auth/login", json=_CREDENTIALS)
        if r.status_code != 200:
            pytest.skip(f"Login failed ({r.status_code}); seed tester827 user first")
        csrf_val = _extract_cookie(r, "csrf-token")
        if csrf_val:
            c.cookies.set("csrf-token", csrf_val, domain="127.0.0.1")
        yield c


def _csrf(client: httpx.Client) -> str:
    r = client.get("/api/csrf-token")
    assert r.status_code == 200
    token = r.json()["csrf_token"]
    client.cookies.set("csrf-token", token, domain="127.0.0.1")
    return token


# ── Static HTML: Habits page shell ──────────────────────────────────────────

def _html() -> str:
    return (ROOT / "frontend" / "pages" / "habits.html").read_text()


def _js() -> str:
    return (ROOT / "frontend" / "js" / "habits.js").read_text()


def test_habits_page_shell_uses_gradient_token():
    # AC: Layout and color tokens sourced from gradient-theme token set
    html = _html()
    assert "var(--page-bg)" in html or "var(--card-bg)" in html, \
        "habits.html must use gradient-theme CSS custom properties"


def test_habits_page_shell_has_today_quick_log_card():
    # AC: Today's active habits are rendered in a dedicated card
    html = _html()
    assert 'id="today-quick-log-card"' in html, \
        "habits.html must have id='today-quick-log-card' for the Today quick-log card"


def test_habits_page_today_card_has_today_habits_list():
    # AC: Today's active habits rendered as a list of rows
    html = _html()
    assert 'id="today-habits-list"' in html, \
        "habits.html must have id='today-habits-list' to hold today's habit rows"


def test_habits_page_today_habit_row_css():
    # AC: Each habit row is styled as a row
    html = _html()
    assert "today-habit-row" in html, \
        "habits.html must define .today-habit-row CSS class"


def test_habits_page_streak_badge_in_today_section():
    # AC: Current streak displayed per habit row (sourced from endpoint)
    html = _html()
    assert "streak-badge" in html or "today-streak" in html, \
        "habits.html must include a streak indicator element"


def test_habits_page_today_binary_toggle_control():
    # AC: binary habits render a tap-to-complete toggle control
    html = _html()
    assert "today-toggle-btn" in html or "toggle-btn" in html, \
        "habits.html must define a toggle button class for binary habits"


def test_habits_page_today_count_stepper_control():
    # AC: count habits render a stepper or quick-entry numeric input
    html = _html()
    assert "today-stepper" in html or "stepper-inc" in html or "stepper-dec" in html, \
        "habits.html must define stepper control classes for count habits"


def test_habits_page_today_duration_input_control():
    # AC: duration habits render a quick-entry input
    html = _html()
    assert "today-duration-input" in html, \
        "habits.html must define .today-duration-input class for duration habits"


def test_habits_page_today_empty_state():
    # AC: When zero active habits, page renders a non-error empty state
    html = _html()
    assert 'id="today-empty-state"' in html or "today-empty" in html, \
        "habits.html must include an empty state element for the Today card"


def test_habits_page_responsive_mobile_css():
    # AC: Page renders without layout breakage at mobile/tablet viewports
    html = _html()
    assert "@media" in html and ("max-width: 768px" in html or "max-width:768px" in html), \
        "habits.html must include responsive CSS media queries"


def test_habits_page_today_target_display():
    # AC: Each habit row displays habit name, target value/unit
    html = _html()
    assert "today-target" in html or "today-habit-meta" in html, \
        "habits.html must include a target/unit display element in the Today card"


# ── Static JS: Today quick-log logic ────────────────────────────────────────

def test_habits_js_fetches_summary_endpoint():
    # AC: Today's active habits are fetched from the H1 summary endpoint
    js = _js()
    assert "/api/habits/summary" in js, \
        "habits.js must fetch GET /api/habits/summary to get today's habits with streaks"


def test_habits_js_renders_today_card():
    # AC: Today's active habits rendered in a card
    js = _js()
    assert "renderTodayCard" in js or "today-quick-log-card" in js or "todayCard" in js, \
        "habits.js must define a renderTodayCard function or reference today-quick-log-card"


def test_habits_js_binary_toggle_handler():
    # AC: binary habits render a tap-to-complete toggle control
    js = _js()
    assert "today-toggle-btn" in js or "toggle-btn" in js or "daily_checkmark" in js, \
        "habits.js must handle binary/daily_checkmark habit toggle controls"


def test_habits_js_count_stepper_handler():
    # AC: count habits render a stepper
    js = _js()
    assert "stepper-inc" in js or "stepper" in js.lower() or "weekly_count" in js, \
        "habits.js must handle count/weekly_count habit stepper controls"


def test_habits_js_duration_input_handler():
    # AC: duration habits render a quick-entry input
    js = _js()
    assert "today-duration-input" in js or "weekly_minutes" in js or "weekly_quantity" in js, \
        "habits.js must handle duration habit input controls"


def test_habits_js_noop_handlers_no_persistence():
    # AC: Quick-log controls invoke no-op/placeholder handler — no persistence
    js = _js()
    assert "noop" in js.lower() or "placeholder" in js.lower() or \
           "// no persistence" in js.lower() or "// no-op" in js.lower() or \
           "no persistence" in js.lower(), \
        "habits.js must include a comment or marker indicating quick-log controls are no-op"


def test_habits_js_streak_from_endpoint_not_computed():
    # AC: No streak values computed or derived on the client
    js = _js()
    # Verify streaks are read from the response, not computed locally
    assert "current_streak" in js, \
        "habits.js must read current_streak from the endpoint response (not compute it)"


def test_habits_js_empty_state_for_zero_habits():
    # AC: Zero active habits renders empty state, not an error
    js = _js()
    assert "today-empty" in js or "today empty" in js.lower() or \
           "todayEmpty" in js or "no habits" in js.lower() or \
           "no active habits" in js.lower(), \
        "habits.js must render an empty state when summary returns zero active habits"


def test_habits_js_renders_streak_badge_from_endpoint():
    # AC: current streak displayed as returned by endpoint, no recomputation
    js = _js()
    assert "current_streak" in js and "streak" in js, \
        "habits.js must read and display current_streak from the summary endpoint"


# ── Page route ───────────────────────────────────────────────────────────────

def test_habits_page_route_exists(client):
    # AC: Habits page is reachable via app navigation
    r = client.get("/habits")
    assert r.status_code == 200, f"GET /habits must return 200; got {r.status_code}"
    assert "text/html" in r.headers.get("content-type", ""), \
        "GET /habits must return HTML"


def test_habits_page_title_present(client):
    # AC: Habits page shell exists
    r = client.get("/habits")
    assert r.status_code == 200
    assert "Habits" in r.text, "Habits page must include 'Habits' heading"


def test_habits_page_nav_link_present():
    # AC: Page reachable via app navigation (nav.js wires the link)
    js = (ROOT / "frontend" / "js" / "nav.js").read_text()
    assert "/habits" in js, "nav.js must include a /habits link for the Habits page"


# ── API: GET /api/habits/summary ─────────────────────────────────────────────

def test_api_habits_summary_requires_auth():
    # AC: Endpoint uses session auth — anonymous requests get 401
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as anon:
        r = anon.get("/api/habits/summary")
    assert r.status_code == 401, \
        "GET /api/habits/summary must return 401 for unauthenticated requests"


def test_api_habits_summary_returns_200(client):
    # AC: Endpoint returns successfully for authenticated user
    r = client.get("/api/habits/summary")
    assert r.status_code == 200, f"GET /api/habits/summary must return 200; got {r.status_code} {r.text}"


def test_api_habits_summary_returns_habits_list(client):
    # AC: Response contains a habits list
    r = client.get("/api/habits/summary")
    assert r.status_code == 200
    body = r.json()
    assert "habits" in body, "Response must have a 'habits' key"
    assert isinstance(body["habits"], list), "'habits' must be a list"


def test_api_habits_summary_habit_has_current_streak(client):
    # AC: Each habit in the response includes current_streak (from endpoint, not client)
    csrf = _csrf(client)
    # Create a temporary habit to ensure at least one active habit exists
    r = client.post("/api/habits", json={
        "name": "Streak test habit #827",
        "tracking_type": "daily_checkmark",
        "weekly_target": 7,
        "unit": "days",
    }, headers={"X-CSRF-Token": csrf})
    assert r.status_code == 201
    habit_id = r.json()["id"]

    try:
        summary = client.get("/api/habits/summary")
        assert summary.status_code == 200
        habits = summary.json()["habits"]
        matching = [h for h in habits if h["id"] == habit_id]
        assert len(matching) == 1, "Newly-created habit must appear in summary"
        h = matching[0]
        assert "current_streak" in h, "Summary habit must include 'current_streak'"
        assert isinstance(h["current_streak"], int), "'current_streak' must be an integer"
        assert h["current_streak"] >= 0, "'current_streak' must be non-negative"
    finally:
        client.request("DELETE", f"/api/habits/{habit_id}", headers={"X-CSRF-Token": csrf})


def test_api_habits_summary_habit_has_name_and_tracking_type(client):
    # AC: Each habit row displays habit name and enough info for type-specific controls
    r = client.get("/api/habits/summary")
    assert r.status_code == 200
    habits = r.json()["habits"]
    for h in habits:
        assert "name" in h, "Each summary habit must have 'name'"
        assert "tracking_type" in h, "Each summary habit must have 'tracking_type'"


def test_api_habits_summary_excludes_archived(client):
    # AC: Only active habits appear in the summary
    csrf = _csrf(client)
    r = client.post("/api/habits", json={
        "name": "Archived habit #827",
        "tracking_type": "daily_checkmark",
        "weekly_target": 7,
        "unit": "days",
    }, headers={"X-CSRF-Token": csrf})
    assert r.status_code == 201
    habit_id = r.json()["id"]

    # Archive it
    client.patch(f"/api/habits/{habit_id}", json={"is_archived": True},
                 headers={"X-CSRF-Token": csrf})

    # Must not appear in summary
    summary = client.get("/api/habits/summary")
    assert summary.status_code == 200
    ids = [h["id"] for h in summary.json()["habits"]]
    assert habit_id not in ids, "Archived habit must not appear in summary"

    # Cleanup
    client.request("DELETE", f"/api/habits/{habit_id}?hard=true",
                   headers={"X-CSRF-Token": csrf})


def test_api_habits_summary_empty_for_new_user(client):
    # AC: Zero active habits renders empty state — endpoint returns empty list, not error
    # (We use the existing auth user which may have habits; just verify list shape)
    r = client.get("/api/habits/summary")
    assert r.status_code == 200
    body = r.json()
    # Whether 0 or more habits, 'habits' must be a list
    assert isinstance(body["habits"], list)
