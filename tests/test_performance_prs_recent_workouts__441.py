"""
TDD tests for issue #441: Add Performance PRs and Recent Workouts cards.

Each test is anchored to one Acceptance Criterion.

Performance (PRs) Card — lower grid, left column:
(AC-PERF-1)  Header reads "Personal records" with "All tracks →" link to /settings#personal-records
(AC-PERF-2)  Displays top 3 tracks; shows fewer if fewer exist
(AC-PERF-3)  Each row: colored icon chip (run vs. lift), track name, meta label, PB value with trophy + date
(AC-PERF-4)  "Most recent" column: latest value + improvement delta green when beats PB
(AC-PERF-5)  Shows "—" when no improvement or no recent entry
(AC-PERF-6)  No inline editing; all management routes via header link
(AC-PERF-7)  Empty state: "Set your personal records →" linking to PR management page
(AC-PERF-8)  No console errors (manual UAT)

Recent Workouts Card — lower grid, right column (above Sleep):
(AC-WO-1)   Header reads "Recent workouts" with "View all →" to /log
(AC-WO-2)   Displays last 3 entries from recent_workouts; fewer if fewer exist
(AC-WO-3)   Each row: workout type icon, workout name, meta as relative-day · distance · duration
(AC-WO-4)   Rows with zone2_minutes show a "Z2 {min}" badge
(AC-WO-5)   Clicking any row navigates to /log
(AC-WO-6)   Empty state: "No workouts yet — log your first"
(AC-WO-7)   No console errors (manual UAT)

API:
(AC-API-1)  /api/home/recent-workouts returns zone2_minutes field per workout
(AC-API-2)  /api/home/recent-workouts limit=3 returns at most 3 workouts
"""
import datetime
import pathlib
import uuid

import httpx
import pytest

# ── Root detection ─────────────────────────────────────────────────────────────

_TESTER_ROOT = pathlib.Path(__file__).resolve().parents[1]
_CODER_ROOT = _TESTER_ROOT.parent / "coder"


def _find_root() -> pathlib.Path:
    for root in (_CODER_ROOT, _TESTER_ROOT):
        if (root / "frontend" / "js" / "home.js").exists():
            return root
    return _TESTER_ROOT


_ROOT = _find_root()
_HOME_JS = (_ROOT / "frontend" / "js" / "home.js").read_text()
_HOME_HTML = (_ROOT / "frontend" / "pages" / "home.html").read_text()

BASE = "http://127.0.0.1:9001"
TODAY = datetime.date.today()
TODAY_STR = TODAY.isoformat()
_RUN = uuid.uuid4().hex[:8]


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c


@pytest.fixture(scope="module")
def user_id(client):
    res = client.get("/api/users")
    assert res.status_code == 200
    users = res.json()
    assert len(users) > 0, "No users found; seed the DB first"
    return users[0]["id"]


@pytest.fixture(scope="module")
def workouts_with_z2(client, user_id):
    """Create 4 workouts, 2 with zone2_minutes, to test Z2 badge and limit=3."""
    created = []

    def _post(days_ago, name, wtype, duration=None, distance=None, zone2=None):
        d = (TODAY - datetime.timedelta(days=days_ago)).isoformat()
        body = {
            "user_id": user_id,
            "name": name,
            "workout_date": d,
            "workout_type": wtype,
            "exercises": [],
        }
        if duration is not None:
            body["duration_seconds"] = duration
        if distance is not None:
            body["distance_km"] = distance
        if zone2 is not None:
            body["zone2_minutes"] = zone2
        r = client.post("/api/workouts", json=body)
        assert r.status_code == 201, f"POST workout failed: {r.status_code} {r.text}"
        return r.json()["id"]

    created.append(_post(1, "Easy Z2 run", "run", duration=3600, distance=10.0, zone2=45))
    created.append(_post(2, "Interval run", "run", duration=2700, distance=8.0))
    created.append(_post(3, "Strength session", "strength", duration=3900))
    created.append(_post(4, "Zone 2 ride", "bike", duration=7200, distance=40.0, zone2=65))

    yield created

    for wid in created:
        client.delete(f"/api/workouts/{wid}")


# ══════════════════════════════════════════════════════════════════════════════
# Performance (PRs) Card — HTML structure
# ══════════════════════════════════════════════════════════════════════════════

def test_home_html_has_row2_for_performance():
    """AC-PERF-1: home.html must have row-2 container for the Performance PRs card."""
    assert 'id="row-2"' in _HOME_HTML, (
        "home.html must have id='row-2' as the left-column container for the Performance PRs card"
    )


# ══════════════════════════════════════════════════════════════════════════════
# AC-PERF-1: Header reads "Personal records" with "All tracks →" to /settings#personal-records
# ══════════════════════════════════════════════════════════════════════════════

def test_home_js_perf_header_personal_records():
    """AC-PERF-1: Performance card header must read 'Personal records'."""
    assert "Personal records" in _HOME_JS, (
        "home.js must render 'Personal records' as the Performance card header"
    )


def test_home_js_perf_all_tracks_arrow_link():
    """AC-PERF-1: Performance card header must have 'All tracks →' link."""
    assert "All tracks" in _HOME_JS, (
        "home.js must render 'All tracks' link in the Performance card header"
    )


def test_home_js_perf_all_tracks_link_target():
    """AC-PERF-1: 'All tracks →' link must point to /settings#personal-records."""
    idx = _HOME_JS.find("All tracks")
    assert idx != -1
    context = _HOME_JS[max(0, idx - 200): idx + 300]
    assert "/settings#personal-records" in context, (
        "'All tracks →' link must route to /settings#personal-records"
    )


# ══════════════════════════════════════════════════════════════════════════════
# AC-PERF-2: Displays top 3 tracks; shows fewer if fewer exist
# ══════════════════════════════════════════════════════════════════════════════

def test_home_js_perf_limits_to_3_tracks():
    """AC-PERF-2: Performance card must display at most 3 tracks."""
    assert (
        "slice(0, 3)" in _HOME_JS
        or ".slice(0,3)" in _HOME_JS
        or "limit=3" in _HOME_JS
        or ".length > 3" in _HOME_JS
        or "top 3" in _HOME_JS.lower()
    ), (
        "home.js must limit the Performance card to 3 tracks"
    )


# ══════════════════════════════════════════════════════════════════════════════
# AC-PERF-3: Each row: icon chip, track name, meta label, PB value with trophy + date
# ══════════════════════════════════════════════════════════════════════════════

def test_home_js_perf_has_run_icon_chip():
    """AC-PERF-3: Performance card must have a 'run' icon chip style."""
    assert "icon-wrap" in _HOME_JS and "run" in _HOME_JS, (
        "home.js must render a run icon chip in the Performance card rows"
    )


def test_home_js_perf_has_lift_icon_chip():
    """AC-PERF-3: Performance card must have a 'lift' icon chip style."""
    assert "icon-wrap" in _HOME_JS and "lift" in _HOME_JS, (
        "home.js must render a lift icon chip in the Performance card rows"
    )


def test_home_html_has_run_lift_icon_css():
    """AC-PERF-3: home.html must have CSS for run and lift icon chips."""
    assert "icon-wrap.run" in _HOME_HTML, (
        "home.html must have CSS for .icon-wrap.run (blue chip for running tracks)"
    )
    assert "icon-wrap.lift" in _HOME_HTML, (
        "home.html must have CSS for .icon-wrap.lift (purple chip for lift tracks)"
    )


def test_home_js_perf_renders_pb_with_trophy():
    """AC-PERF-3: PB value must be displayed with a trophy indicator."""
    assert (
        "trophy" in _HOME_JS.lower()
        or "ti-trophy" in _HOME_JS
        or "\U0001f3c6" in _HOME_JS  # 🏆 emoji
    ), (
        "home.js must render a trophy indicator alongside the PB value"
    )


def test_home_js_perf_renders_pb_date():
    """AC-PERF-3: PB value must be displayed with the date it was achieved."""
    assert "achieved_on" in _HOME_JS or "pb_date" in _HOME_JS, (
        "home.js must render the date when the PB was achieved"
    )


# ══════════════════════════════════════════════════════════════════════════════
# AC-PERF-4: "Most recent" column: delta green when beats PB
# ══════════════════════════════════════════════════════════════════════════════

def test_home_js_perf_has_most_recent_column():
    """AC-PERF-4: Performance card must have a 'Most recent' column."""
    assert (
        "Most recent" in _HOME_JS
        or "most recent" in _HOME_JS.lower()
        or "recent" in _HOME_JS
    ), (
        "home.js must render a 'Most recent' column in the Performance card"
    )


def test_home_js_perf_delta_green_class_on_improvement():
    """AC-PERF-4: Improvement delta must use green styling."""
    assert (
        "'ahead'" in _HOME_JS
        or '"ahead"' in _HOME_JS
        or "pc-delta ahead" in _HOME_JS
        or "pc-delta.ahead" in _HOME_HTML
        or "var(--green)" in _HOME_JS
        or "color: var(--green" in _HOME_JS
    ), (
        "home.js must apply green styling to the delta when the most recent value beats the PB"
    )


# ══════════════════════════════════════════════════════════════════════════════
# AC-PERF-5: Shows "—" when no improvement or no recent entry
# ══════════════════════════════════════════════════════════════════════════════

def test_home_js_perf_dash_when_no_recent():
    """AC-PERF-5: Performance card must show '—' when there is no recent entry."""
    assert (
        "pc-dash" in _HOME_JS
        or '"—"' in _HOME_JS
        or "'—'" in _HOME_JS
    ), (
        "home.js must render a dash '—' when there is no recent entry or no improvement"
    )


# ══════════════════════════════════════════════════════════════════════════════
# AC-PERF-7: Empty state: "Set your personal records →" link
# ══════════════════════════════════════════════════════════════════════════════

def test_home_js_perf_empty_state_set_personal_records():
    """AC-PERF-7: Empty state must show 'Set your personal records →' link."""
    assert (
        "Set your personal records" in _HOME_JS
    ), (
        "home.js must render 'Set your personal records →' in the Performance card empty state"
    )


def test_home_js_perf_empty_state_links_to_pr_settings():
    """AC-PERF-7: Empty state link must point to PR management page."""
    idx = _HOME_JS.find("Set your personal records")
    assert idx != -1
    context = _HOME_JS[max(0, idx - 100): idx + 300]
    assert "/settings#personal-records" in context or "/settings" in context, (
        "Empty state 'Set your personal records →' must link to the PR management page"
    )


# ══════════════════════════════════════════════════════════════════════════════
# Recent Workouts Card — HTML structure
# ══════════════════════════════════════════════════════════════════════════════

def test_home_html_has_home_workouts_card():
    """AC-WO-1/AC-WO-5: home.html must have a home-workouts-card container."""
    assert 'id="home-workouts-card"' in _HOME_HTML, (
        "home.html must have id='home-workouts-card' for the Recent Workouts card"
    )


def test_home_html_workouts_card_before_sleep_card():
    """AC-WO-2: If home-sleep-card exists, home-workouts-card must appear before it."""
    workouts_pos = _HOME_HTML.find('id="home-workouts-card"')
    assert workouts_pos != -1, "home.html must have id='home-workouts-card'"
    sleep_pos = _HOME_HTML.find('id="home-sleep-card"')
    if sleep_pos != -1:
        # Issue #440 (Sleep card) has been merged; verify ordering.
        assert workouts_pos < sleep_pos, (
            "home-workouts-card must appear before home-sleep-card in the HTML "
            "(Recent Workouts is above Sleep in the right column)"
        )
    # If home-sleep-card is absent (issue #440 not yet merged), ordering is confirmed later.


# ══════════════════════════════════════════════════════════════════════════════
# AC-WO-1: Header reads "Recent workouts" with "View all →" to /log
# ══════════════════════════════════════════════════════════════════════════════

def test_home_js_recent_workouts_header():
    """AC-WO-1: Recent Workouts card header must read 'Recent workouts'."""
    assert "Recent workouts" in _HOME_JS, (
        "home.js must render 'Recent workouts' as the card header"
    )


def test_home_js_recent_workouts_view_all_link():
    """AC-WO-1: Recent Workouts card must have a 'View all' link to /log."""
    assert "View all" in _HOME_JS, (
        "home.js must render a 'View all' link in the Recent Workouts card header"
    )


def test_home_js_recent_workouts_view_all_points_to_log():
    """AC-WO-1: 'View all →' link must point to /log."""
    assert '"/log"' in _HOME_JS or "'/log'" in _HOME_JS, (
        "home.js must link 'View all →' to /log in the Recent Workouts card"
    )


# ══════════════════════════════════════════════════════════════════════════════
# AC-WO-2: Displays last 3 entries; fewer if fewer exist
# ══════════════════════════════════════════════════════════════════════════════

def test_home_js_recent_workouts_uses_limit_3():
    """AC-WO-2: Recent Workouts card must request/display at most 3 workouts."""
    assert (
        "limit=3" in _HOME_JS
        or "limit: 3" in _HOME_JS
        or "&limit=3" in _HOME_JS
        or "?limit=3" in _HOME_JS
        or ".slice(0, 3)" in _HOME_JS
        or ".slice(0,3)" in _HOME_JS
    ), (
        "home.js must limit the Recent Workouts card to 3 workouts"
    )


# ══════════════════════════════════════════════════════════════════════════════
# AC-WO-3: Each row: workout type icon, workout name, meta as relative-day · distance · duration
# ══════════════════════════════════════════════════════════════════════════════

def test_home_js_recent_workouts_uses_relative_date():
    """AC-WO-3: Workout rows must show relative-day (Today, Yesterday, etc.) in meta."""
    assert (
        "relative_date" in _HOME_JS
        or "Today" in _HOME_JS
        or "Yesterday" in _HOME_JS
    ), (
        "home.js must use relative_date (e.g. 'Today', 'Yesterday') in workout row meta"
    )


def test_home_js_recent_workouts_meta_includes_distance():
    """AC-WO-3: Workout row meta must include distance."""
    assert "distance_km" in _HOME_JS, (
        "home.js must include distance_km in the workout row meta line"
    )


def test_home_js_recent_workouts_meta_includes_duration():
    """AC-WO-3: Workout row meta must include duration."""
    assert (
        "duration_seconds" in _HOME_JS
        or "fmtWorkoutDuration" in _HOME_JS
        or "duration" in _HOME_JS
    ), (
        "home.js must include duration in the workout row meta line"
    )


# ══════════════════════════════════════════════════════════════════════════════
# AC-WO-4: Rows with zone2_minutes show a Z2 badge
# ══════════════════════════════════════════════════════════════════════════════

def test_home_js_z2_badge_rendered():
    """AC-WO-4: Workout rows with zone2_minutes must show a Z2 badge."""
    assert (
        "zone2_minutes" in _HOME_JS
        and (
            "Z2" in _HOME_JS
            or "z2" in _HOME_JS.lower()
        )
    ), (
        "home.js must render a 'Z2 {min}' badge for workouts that have zone2_minutes"
    )


def test_home_html_has_z2_badge_css():
    """AC-WO-4: home.html must have CSS for the Z2 badge."""
    assert (
        "z2-badge" in _HOME_HTML.lower()
        or ".z2" in _HOME_HTML
        or "Z2" in _HOME_HTML
    ), (
        "home.html must define CSS for the Z2 badge (.z2-badge or similar)"
    )


# ══════════════════════════════════════════════════════════════════════════════
# AC-WO-5: Clicking any row navigates to /log
# ══════════════════════════════════════════════════════════════════════════════

def test_home_js_workout_row_click_navigates_to_log():
    """AC-WO-5: Clicking a workout row must navigate to /log."""
    assert (
        "location.href" in _HOME_JS
        or "window.location" in _HOME_JS
        or "href=\"/log\"" in _HOME_JS
        or "'/log'" in _HOME_JS
    ), (
        "home.js must navigate to /log when a workout row is clicked"
    )


# ══════════════════════════════════════════════════════════════════════════════
# AC-WO-6: Empty state: "No workouts yet — log your first"
# ══════════════════════════════════════════════════════════════════════════════

def test_home_js_workouts_empty_state():
    """AC-WO-6: Recent Workouts card empty state must read 'No workouts yet'."""
    assert (
        "No workouts yet" in _HOME_JS
    ), (
        "home.js must show 'No workouts yet' in the Recent Workouts card empty state"
    )


def test_home_js_workouts_empty_state_has_link():
    """AC-WO-6: Empty state must include a link to the workout logging entry point."""
    idx = _HOME_JS.find("No workouts yet")
    assert idx != -1
    context = _HOME_JS[max(0, idx - 50): idx + 400]
    assert (
        "/training" in context
        or "/log" in context
        or "href" in context
    ), (
        "The 'No workouts yet' empty state must include a link to the workout logging entry point"
    )


# ══════════════════════════════════════════════════════════════════════════════
# AC-API-1: /api/home/recent-workouts returns zone2_minutes field
# ══════════════════════════════════════════════════════════════════════════════

def test_api_recent_workouts_returns_zone2_minutes(client, user_id, workouts_with_z2):
    """AC-API-1: /api/home/recent-workouts must include zone2_minutes in each workout dict."""
    res = client.get(
        "/api/home/recent-workouts",
        params={"user_id": user_id, "limit": 4},
    )
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
    body = res.json()
    assert "workouts" in body, "Response must have 'workouts' key"
    workouts = body["workouts"]
    assert len(workouts) >= 1, "At least one workout must be returned"

    for w in workouts:
        assert "zone2_minutes" in w, (
            f"Each workout in /api/home/recent-workouts must have 'zone2_minutes' field; "
            f"workout {w.get('id')} is missing it"
        )


def test_api_recent_workouts_z2_value_is_int_or_null(client, user_id, workouts_with_z2):
    """AC-API-1: zone2_minutes must be an integer or null."""
    res = client.get(
        "/api/home/recent-workouts",
        params={"user_id": user_id, "limit": 4},
    )
    assert res.status_code == 200
    workouts = res.json()["workouts"]
    for w in workouts:
        z2 = w.get("zone2_minutes")
        assert z2 is None or isinstance(z2, int), (
            f"zone2_minutes must be int or null, got {type(z2).__name__} for workout {w.get('id')}"
        )


def test_api_recent_workouts_z2_workouts_have_value(client, user_id, workouts_with_z2):
    """AC-API-1: Workouts posted with zone2_minutes must return that value in the API."""
    res = client.get(
        "/api/home/recent-workouts",
        params={"user_id": user_id, "limit": 4},
    )
    assert res.status_code == 200
    workouts = res.json()["workouts"]
    z2_workouts = [w for w in workouts if w.get("zone2_minutes") is not None]
    assert len(z2_workouts) >= 1, (
        "At least one workout with zone2_minutes must be returned; "
        "check that zone2_minutes is included in the response"
    )


# ══════════════════════════════════════════════════════════════════════════════
# AC-API-2: /api/home/recent-workouts limit=3 returns at most 3 workouts
# ══════════════════════════════════════════════════════════════════════════════

def test_api_recent_workouts_limit_3(client, user_id, workouts_with_z2):
    """AC-API-2: /api/home/recent-workouts with limit=3 must return at most 3 workouts."""
    res = client.get(
        "/api/home/recent-workouts",
        params={"user_id": user_id, "limit": 3},
    )
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
    body = res.json()
    workouts = body["workouts"]
    assert len(workouts) <= 3, (
        f"/api/home/recent-workouts with limit=3 must return at most 3 workouts, "
        f"got {len(workouts)}"
    )


def test_api_recent_workouts_returns_relative_date(client, user_id, workouts_with_z2):
    """AC-WO-3: /api/home/recent-workouts must return relative_date for each workout."""
    res = client.get(
        "/api/home/recent-workouts",
        params={"user_id": user_id, "limit": 3},
    )
    assert res.status_code == 200
    workouts = res.json()["workouts"]
    assert len(workouts) >= 1
    for w in workouts:
        assert "relative_date" in w, (
            f"Each workout must include 'relative_date'; "
            f"workout {w.get('id')} is missing it"
        )


# ══════════════════════════════════════════════════════════════════════════════
# No console errors — manual UAT
# ══════════════════════════════════════════════════════════════════════════════

def test_no_console_errors_manual():
    """AC-PERF-8 / AC-WO-7: No console errors — verified manually via browser DevTools."""
    pytest.skip("Manual UAT step — verify via browser DevTools during UAT")
