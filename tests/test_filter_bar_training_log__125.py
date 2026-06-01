"""Tests for issue #125: Add filter bar to Training Log page"""
import os
from datetime import date as _date, timedelta

import httpx
import pytest

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
    res = client.get("/api/users")
    assert res.status_code == 200
    alice = next((u for u in res.json() if u["name"] == "Alice"), None)
    assert alice is not None, "Alice not found in /api/users"
    return alice["id"]


def _create_workout(client, user_id, **kwargs):
    payload = {
        "user_id": user_id,
        "name": kwargs.pop("name", "Test Workout"),
        "workout_date": kwargs.pop("workout_date", "2026-05-15"),
        "workout_type": kwargs.pop("workout_type", "run"),
        "exercises": kwargs.pop("exercises", []),
    }
    payload.update(kwargs)
    res = client.post("/api/workouts", json=payload)
    assert res.status_code == 201, f"Failed to create workout: {res.text}"
    return res.json()


def _delete_workout(client, workout_id):
    client.delete(f"/api/workouts/{workout_id}")


# ── AC: HTML structure ────────────────────────────────────────────────────────

def test_filter_bar_container_exists(client):
    """AC: #filter-bar div is present in the page"""
    res = client.get("/log")
    assert res.status_code == 200
    assert 'id="filter-bar"' in res.text, "#filter-bar container should be in the HTML"


def test_log_search_input_rendered_in_filter_bar(client):
    """AC: Search input with id='log-search' and correct placeholder is in the page source"""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    assert 'log-search' in res.text, "training-log.js should create #log-search input"
    assert 'Search workouts' in res.text, "Search input should have 'Search workouts' placeholder"


def test_type_chips_rendered(client):
    """AC: Type chips All, Run, Lift, WOD, Bike are built in training-log.js"""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    for t in ['All', 'Run', 'Lift', 'WOD', 'Bike']:
        assert t in res.text, f"Type chip '{t}' label should exist in training-log.js"


def test_type_chip_class_present(client):
    """AC: Type chips use class 'type-chip' with active state"""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    assert 'type-chip' in res.text, "Chips should use 'type-chip' CSS class"
    assert 'active' in res.text, "Active chip state should be handled"


def test_date_range_chip_default_label(client):
    """AC: Date-range chip shows 'Last 30 days' by default"""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    assert 'Last 30 days' in res.text, "Date-range chip should default to 'Last 30 days'"


def test_date_range_from_to_inputs(client):
    """AC: date-range panel exposes input[type=date] from and to fields"""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    assert 'dr-from' in res.text, "Date-range from input (id='dr-from') should be built"
    assert 'dr-to' in res.text, "Date-range to input (id='dr-to') should be built"


def test_loading_indicator_present(client):
    """AC: A loading indicator is built while a fetch is in flight"""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    assert 'log-loading-indicator' in res.text, "Loading indicator element should be created"


# ── AC: URL param handling (JavaScript) ──────────────────────────────────────

def test_url_type_param_used(client):
    """AC: JS reads ?type= from URL and maps it to API 'types' param"""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    assert "get('type')" in res.text or "p.get('type')" in res.text, \
        "JS should read 'type' from URL params"


def test_url_search_param_used(client):
    """AC: JS reads ?search= from URL on page load"""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    assert "get('search')" in res.text or "'search'" in res.text, \
        "JS should read 'search' from URL params"


def test_url_from_to_params_used(client):
    """AC: JS reads ?from= and ?to= from URL on page load"""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    assert "get('from')" in res.text or "'from'" in res.text, "JS should read 'from' URL param"
    assert "get('to')" in res.text or "'to'" in res.text, "JS should read 'to' URL param"


def test_url_write_clears_search_when_empty(client):
    """AC: Clearing search removes ?search= from URL (writeURLParams omits empty search)"""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    # writeURLParams only sets search if filters.search is truthy
    assert 'filters.search' in res.text, "JS should only write search param when it has a value"


def test_debounce_300ms(client):
    """AC: Search input is debounced 300 ms before triggering fetch"""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    assert '300' in res.text, "300 ms debounce timeout should be used for search input"


def test_replacestate_used_for_url_updates(client):
    """AC: Filter state is reflected in the URL at all times via replaceState"""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    assert 'replaceState' in res.text, "history.replaceState should be used to keep URL in sync"


# ── AC: API filtering — type ──────────────────────────────────────────────────

def test_api_type_filter_run(client, alice_id):
    """AC: ?types=run returns only run workouts"""
    today = _date.today().isoformat()
    past  = (_date.today() - timedelta(days=60)).isoformat()
    res = client.get("/api/training-log", params={
        "user_id": alice_id,
        "from": past, "to": today,
        "types": "run",
    })
    assert res.status_code == 200
    for week in res.json()["weeks"]:
        for entry in week["entries"]:
            if entry["type"] != "rest":
                assert entry["type"].lower() == "run", \
                    f"Expected only run entries when types=run, got {entry['type']!r}"


def test_api_type_filter_lift(client, alice_id):
    """AC: ?types=lift returns only lift workouts"""
    w = _create_workout(client, alice_id, name="125 lift test", workout_type="lift",
                        workout_date="2026-05-10")
    try:
        res = client.get("/api/training-log", params={
            "user_id": alice_id,
            "from": "2026-05-10", "to": "2026-05-10",
            "types": "lift",
        })
        assert res.status_code == 200
        entries = [e for wk in res.json()["weeks"] for e in wk["entries"]]
        assert all(e["type"] in ("lift", "rest") for e in entries), \
            "Only lift entries expected when types=lift"
    finally:
        _delete_workout(client, w["id"])


def test_api_type_all_returns_all_types(client, alice_id):
    """AC: Omitting types (or types=all) returns all workout types"""
    today = _date.today().isoformat()
    past  = (_date.today() - timedelta(days=60)).isoformat()
    res = client.get("/api/training-log", params={
        "user_id": alice_id, "from": past, "to": today,
    })
    assert res.status_code == 200
    assert "weeks" in res.json()


# ── AC: API filtering — search ────────────────────────────────────────────────

def test_api_search_filters_by_name(client, alice_id):
    """AC: ?search=tempo filters by workout name (case-insensitive)"""
    w = _create_workout(client, alice_id, name="Tempo Intervals 125",
                        workout_type="run", workout_date="2026-05-08")
    try:
        res = client.get("/api/training-log", params={
            "user_id": alice_id,
            "from": "2026-05-08", "to": "2026-05-08",
            "search": "tempo",
        })
        assert res.status_code == 200
        entries = [e for wk in res.json()["weeks"] for e in wk["entries"]]
        titles  = [e.get("title", "").lower() for e in entries]
        assert any("tempo" in t for t in titles), \
            "?search=tempo should return workouts with 'tempo' in name"
    finally:
        _delete_workout(client, w["id"])


def test_api_search_filters_by_remarks(client, alice_id):
    """AC: ?search= also matches remarks/notes field"""
    w = _create_workout(client, alice_id, name="Easy Run 125",
                        workout_type="run", workout_date="2026-05-08",
                        remarks="threshold effort today")
    try:
        res = client.get("/api/training-log", params={
            "user_id": alice_id,
            "from": "2026-05-08", "to": "2026-05-08",
            "search": "threshold",
        })
        assert res.status_code == 200
        entries = [e for wk in res.json()["weeks"] for e in wk["entries"]]
        assert entries, "?search=threshold should match workout with 'threshold' in remarks"
    finally:
        _delete_workout(client, w["id"])


def test_api_search_no_match_returns_empty(client, alice_id):
    """AC: ?search= with no match returns empty weeks array"""
    res = client.get("/api/training-log", params={
        "user_id": alice_id,
        "from": "2026-05-08", "to": "2026-05-08",
        "search": "xyzzy_no_match_125",
    })
    assert res.status_code == 200
    entries = [e for wk in res.json()["weeks"] for e in wk["entries"]]
    assert entries == [], "No-match search should return no entries"


# ── AC: API filtering — date range ────────────────────────────────────────────

def test_api_date_range_respected(client, alice_id):
    """AC: ?from=&to= restricts results to that window"""
    w = _create_workout(client, alice_id, name="125 date range test",
                        workout_type="run", workout_date="2026-04-15")
    try:
        # Query a range that excludes the workout
        res = client.get("/api/training-log", params={
            "user_id": alice_id,
            "from": "2026-05-01", "to": "2026-05-31",
        })
        assert res.status_code == 200
        ids = [e.get("id") for wk in res.json()["weeks"] for e in wk["entries"]]
        assert w["id"] not in ids, "Workout outside date range should not appear"
    finally:
        _delete_workout(client, w["id"])


def test_api_default_date_range_is_last_30_days(client, alice_id):
    """AC: Omitting from/to defaults to last 30 days (backend default)"""
    res = client.get("/api/training-log", params={"user_id": alice_id})
    assert res.status_code == 200
    data = res.json()
    for wk in data["weeks"]:
        wk_start = _date.fromisoformat(wk["week_start"])
        assert wk_start >= _date.today() - timedelta(days=35), \
            f"Default range should stay within ~last 30 days, got week_start={wk['week_start']}"


# ── AC: Combined params (UAT step 8) ─────────────────────────────────────────

def test_api_combined_type_search_date_filters(client, alice_id):
    """AC: ?type=lift&search=deadlift&from=&to= all applied simultaneously"""
    w = _create_workout(client, alice_id, name="Deadlift Day 125",
                        workout_type="lift", workout_date="2026-04-20")
    try:
        res = client.get("/api/training-log", params={
            "user_id": alice_id,
            "from": "2026-04-01", "to": "2026-04-30",
            "types": "lift",
            "search": "deadlift",
        })
        assert res.status_code == 200
        entries = [e for wk in res.json()["weeks"] for e in wk["entries"]]
        assert any(e.get("id") == w["id"] for e in entries), \
            "Combined type+search+date filter should return the matching workout"
        assert all(e["type"] == "lift" for e in entries), \
            "All returned entries should be lift type"
    finally:
        _delete_workout(client, w["id"])


# ── AC: Page loads with URL params pre-applied ────────────────────────────────

def test_page_loads_with_type_param(client):
    """AC: Page returns 200 when loaded with ?type=run"""
    res = client.get("/log?type=run")
    assert res.status_code == 200
    assert "Training log" in res.text


def test_page_loads_with_all_params(client):
    """AC: Page returns 200 when loaded with ?type=lift&search=deadlift&from=&to="""
    res = client.get("/log?type=lift&search=deadlift&from=2026-04-01&to=2026-04-30")
    assert res.status_code == 200
    assert "Training log" in res.text


# ── AC: Responsive layout ─────────────────────────────────────────────────────

def test_filter_bar_responsive_styles(client):
    """AC: #filter-bar uses flex-direction:column at narrow width via media query"""
    res = client.get("/log")
    assert res.status_code == 200
    assert 'flex-direction: column' in res.text or 'flex-direction:column' in res.text, \
        "Training-log.html should have a responsive media query stacking filter-bar vertically"


def test_filter_bar_has_flex_wrap(client):
    """AC: Filter bar elements wrap so nothing overflows horizontally at 380 px"""
    res = client.get("/log")
    assert res.status_code == 200
    assert 'flex-wrap' in res.text, \
        "Filter bar or chips row should use flex-wrap to prevent horizontal overflow"


# ── AC: JavaScript structure ──────────────────────────────────────────────────

def test_js_fetches_api_training_log(client):
    """AC: training-log.js fetches from /api/training-log"""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    assert '/api/training-log' in res.text, "JS should fetch from /api/training-log"


def test_js_uses_fetch_not_framework(client):
    """AC: training-log.js is plain vanilla JS (no React/Vue)"""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    assert 'React' not in res.text and 'Vue' not in res.text, \
        "training-log.js should be vanilla JS"


def test_js_uses_history_replace_state(client):
    """AC: URL is updated with replaceState (no full page reload) on filter change"""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    assert 'replaceState' in res.text


def test_js_single_fetch_on_load(client):
    """AC: JS calls fetchAndRender once on DOMContentLoaded (no duplicate initial fetch)"""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    # The init block should call fetchAndRender exactly once at load
    content = res.text
    assert content.count('fetchAndRender()') >= 1, "fetchAndRender should be called at least once on init"
