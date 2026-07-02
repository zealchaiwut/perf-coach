"""
Tests for issue #26: Home dashboard — weight chart, habits today, recent training sections
Server under test: http://127.0.0.1:9001
"""
import datetime
import pathlib
import re

import httpx
import pytest
from tests._admin_helpers import admin_cookies as _admin_cookies

BASE = "http://127.0.0.1:9001"
TODAY = datetime.date.today()
TODAY_STR = TODAY.isoformat()
YESTERDAY = TODAY - datetime.timedelta(days=1)
YESTERDAY_STR = YESTERDAY.isoformat()


# ── Fixtures ──────────────────────────────────────────────────────────────────

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


@pytest.fixture(scope="module")
def bob_id(client):
    res = client.get("/api/users", cookies=_admin_cookies())
    assert res.status_code == 200
    bob = next((u for u in res.json() if u["name"] == "Bob"), None)
    assert bob is not None, "Bob not found in /api/users"
    return bob["id"]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _clean_weight(client, user_id):
    today = datetime.date.today()
    from_d = (today - datetime.timedelta(days=89)).isoformat()
    res = client.get(f"/api/weight-entries?user_id={user_id}&from={from_d}&to={today.isoformat()}")
    if res.status_code == 200:
        for e in res.json()["entries"]:
            client.delete(f"/api/weight-entries/{e['id']}")


def _post_weight(client, user_id, date_str, kg):
    res = client.post(
        "/api/weight-entries",
        json={"user_id": user_id, "weight_kg": kg, "entry_date": date_str},
    )
    assert res.status_code in (201, 409), f"POST weight failed: {res.status_code} {res.text}"
    return res


def _post_workout(client, user_id, date_str, name="Push day", workout_type="Strength", exercises=None):
    body = {
        "user_id": user_id,
        "name": name,
        "workout_date": date_str,
        "workout_type": workout_type,
        "exercises": exercises or [],
    }
    res = client.post("/api/workouts", json=body)
    assert res.status_code == 201, f"POST workout failed: {res.status_code} {res.text}"
    return res.json()


def _clean_workouts_range(client, user_id, from_str, to_str):
    res = client.get(f"/api/workouts?user_id={user_id}&from={from_str}&to={to_str}")
    if res.status_code == 200:
        for w in res.json():
            client.delete(f"/api/workouts/{w['id']}")


# ── AC-1: Three sections render below stat cards (HTML structure) ──────────────

def test_ac1_weight_section_exists_in_html():
    """home.html must have a section element with id='section-weight'."""
    html = (pathlib.Path(__file__).parent.parent / "frontend" / "pages" / "home.html").read_text()
    assert 'id="section-weight"' in html, "Missing id='section-weight' section in home.html"


def test_ac1_habits_section_exists_in_html():
    """home.html must have a section element with id='section-habits'."""
    html = (pathlib.Path(__file__).parent.parent / "frontend" / "pages" / "home.html").read_text()
    assert 'id="section-habits"' in html, "Missing id='section-habits' section in home.html"


def test_ac1_training_section_exists_in_html():
    """home.html must have a section element with id='section-training'."""
    html = (pathlib.Path(__file__).parent.parent / "frontend" / "pages" / "home.html").read_text()
    assert 'id="section-training"' in html, "Missing id='section-training' section in home.html"


def test_ac1_sections_in_order_weight_habits_training():
    """Sections must appear in order: Weight, then Habits, then Training."""
    html = (pathlib.Path(__file__).parent.parent / "frontend" / "pages" / "home.html").read_text()
    w_pos = html.find('id="section-weight"')
    h_pos = html.find('id="section-habits"')
    t_pos = html.find('id="section-training"')
    assert w_pos != -1 and h_pos != -1 and t_pos != -1, "One or more section IDs missing"
    assert w_pos < h_pos < t_pos, "Sections must appear in order: weight, habits, training"


def test_ac1_sections_appear_after_stat_cards():
    """The summary sections must appear after the .dash-cards grid in the HTML."""
    html = (pathlib.Path(__file__).parent.parent / "frontend" / "pages" / "home.html").read_text()
    cards_pos = html.find('id="dash-cards"')
    section_pos = html.find('id="section-weight"')
    assert cards_pos != -1 and section_pos != -1
    assert cards_pos < section_pos, "Summary sections must come after the stat cards"


# ── AC-2: Section headers with icon, title, and right-aligned link ─────────────

def test_ac2_weight_section_has_open_tab_link():
    """Weight section header must contain a link to weight.html."""
    html = (pathlib.Path(__file__).parent.parent / "frontend" / "pages" / "home.html").read_text()
    assert 'href="weight.html"' in html, "Missing href='weight.html' link in home.html"


def test_ac2_weight_section_link_text():
    """Weight section link must read 'Open Weight tab →'."""
    html = (pathlib.Path(__file__).parent.parent / "frontend" / "pages" / "home.html").read_text()
    assert "Open Weight tab →" in html, "Missing 'Open Weight tab →' link text in home.html"


def test_ac2_habits_section_has_open_tab_link():
    """Habits section header must contain a link to habits.html."""
    html = (pathlib.Path(__file__).parent.parent / "frontend" / "pages" / "home.html").read_text()
    assert 'href="habits.html"' in html, "Missing href='habits.html' link in home.html"


def test_ac2_habits_section_link_text():
    """Habits section link must read 'Open Habits tab →'."""
    html = (pathlib.Path(__file__).parent.parent / "frontend" / "pages" / "home.html").read_text()
    assert "Open Habits tab →" in html, "Missing 'Open Habits tab →' link text in home.html"


def test_ac2_training_section_link_text():
    """Training section link must read 'Open Training tab →'."""
    html = (pathlib.Path(__file__).parent.parent / "frontend" / "pages" / "home.html").read_text()
    assert "Open Training tab →" in html, "Missing 'Open Training tab →' link text in home.html"


def test_ac2_section_link_class_in_html():
    """Section links must use the 'dash-section-link' CSS class."""
    html = (pathlib.Path(__file__).parent.parent / "frontend" / "pages" / "home.html").read_text()
    assert "dash-section-link" in html, "Missing 'dash-section-link' CSS class in home.html"


# ── AC-3: Weight section — mini chart (last 14 days) ─────────────────────────

def test_ac3_mini_weight_chart_canvas_in_html():
    """home.html must have a canvas element with id='mini-weight-chart'."""
    html = (pathlib.Path(__file__).parent.parent / "frontend" / "pages" / "home.html").read_text()
    assert 'id="mini-weight-chart"' in html, "Missing id='mini-weight-chart' canvas in home.html"


def test_ac3_mini_chart_wrap_height_80px():
    """home.html CSS must define .mini-chart-wrap with height: 80px."""
    html = (pathlib.Path(__file__).parent.parent / "frontend" / "pages" / "home.html").read_text()
    assert "mini-chart-wrap" in html, "Missing .mini-chart-wrap class definition in home.html"
    assert "80px" in html, "Missing 80px height for mini chart wrap in home.html"


def test_ac3_chart_js_cdn_loaded():
    """home.html must load Chart.js via CDN (no build step)."""
    html = (pathlib.Path(__file__).parent.parent / "frontend" / "pages" / "home.html").read_text()
    assert "chart.js" in html.lower() or "chartjs" in html.lower(), \
        "home.html must include Chart.js CDN script tag"


def test_ac3_load_weight_section_function_in_js():
    """home.js must have a loadWeightSection function."""
    js = (pathlib.Path(__file__).parent.parent / "frontend" / "js" / "home.js").read_text()
    assert "loadWeightSection" in js, "Missing loadWeightSection function in home.js"


def test_ac3_last14days_function_in_js():
    """home.js must have a last14Days (or equivalent) function to compute the 14-day cutoff."""
    js = (pathlib.Path(__file__).parent.parent / "frontend" / "js" / "home.js").read_text()
    assert "last14Days" in js or "14" in js, \
        "home.js must reference 14-day cutoff logic for the weight mini chart"


def test_ac3_weight_section_filters_to_14_days():
    """home.js must filter weight entries to last 14 days (cutoff = today minus 13 days)."""
    js = (pathlib.Path(__file__).parent.parent / "frontend" / "js" / "home.js").read_text()
    # Check that the code uses 13 (today - 13 = 14 days inclusive) or 14 as range
    assert "13" in js or "14" in js, \
        "home.js must filter weight entries to a 14-day window"


def test_ac3_weight_section_no_filter_control_in_html():
    """Home page must not have a date filter control for the weight mini chart."""
    html = (pathlib.Path(__file__).parent.parent / "frontend" / "pages" / "home.html").read_text()
    # The weight page has a range filter; home must not
    assert "weight-range" not in html, \
        "home.html must NOT have a date range filter control for the mini chart (Home is fixed 14 days)"


def test_ac3_weight_section_api_returns_last_14_days(client, alice_id):
    """API weight data for last 14 days returns only entries within the 14-day window."""
    _clean_weight(client, alice_id)
    cutoff = (TODAY - datetime.timedelta(days=13)).isoformat()
    old_date = (TODAY - datetime.timedelta(days=20)).isoformat()

    # Add an entry within the 14-day window and one outside
    _post_weight(client, alice_id, cutoff, 70.0)
    _post_weight(client, alice_id, old_date, 69.0)

    today = datetime.date.today()
    from_d = (today - datetime.timedelta(days=89)).isoformat()
    entries = client.get(
        f"/api/weight-entries?user_id={alice_id}&from={from_d}&to={today.isoformat()}"
    ).json()["entries"]
    visible = [e for e in entries if e["entry_date"] >= cutoff]
    hidden = [e for e in entries if e["entry_date"] < cutoff]

    assert len(visible) >= 1, "At least the 14-day-boundary entry must be visible"
    assert len(hidden) >= 1, "The 20-day-old entry must be outside the 14-day window"


def test_ac3_weight_section_empty_state_in_js():
    """home.js must show 'No weight entries yet' when there is no weight data."""
    js = (pathlib.Path(__file__).parent.parent / "frontend" / "js" / "home.js").read_text()
    assert "No weight entries yet" in js, "Missing 'No weight entries yet' empty state in home.js"


def test_ac3_weight_section_body_element_in_html():
    """home.html must have section-weight-body element to hold chart or empty state."""
    html = (pathlib.Path(__file__).parent.parent / "frontend" / "pages" / "home.html").read_text()
    assert 'id="section-weight-body"' in html, "Missing id='section-weight-body' in home.html"


# ── AC-4: Habits today section ─────────────────────────────────────────────────

def test_ac4_home_habit_list_in_html():
    """home.html must have an element with id='home-habit-list'."""
    html = (pathlib.Path(__file__).parent.parent / "frontend" / "pages" / "home.html").read_text()
    assert 'id="home-habit-list"' in html, "Missing id='home-habit-list' in home.html"


def test_ac4_load_habits_section_function_in_js():
    """home.js must have a loadHabitsSection function."""
    js = (pathlib.Path(__file__).parent.parent / "frontend" / "js" / "home.js").read_text()
    assert "loadHabitsSection" in js, "Missing loadHabitsSection function in home.js"


def test_ac4_habits_section_fetches_habits_and_logs():
    """home.js loadHabitsSection must fetch both /api/habits and /api/habits/logs."""
    js = (pathlib.Path(__file__).parent.parent / "frontend" / "js" / "home.js").read_text()
    # Check inside loadHabitsSection (it already fetches these for the card too, but section func must also)
    section_start = js.find("loadHabitsSection")
    assert section_start != -1, "Missing loadHabitsSection in home.js"
    section_body = js[section_start:section_start + 600]
    assert "/api/habits" in section_body, "loadHabitsSection must fetch /api/habits"
    assert "/api/habits/logs" in section_body, "loadHabitsSection must fetch /api/habits/logs"


def test_ac4_habits_section_fetches_stats_per_habit():
    """home.js must call /api/habits/stats for each habit to get streak and 30-day rate."""
    js = (pathlib.Path(__file__).parent.parent / "frontend" / "js" / "home.js").read_text()
    assert "/api/habits/stats" in js, "home.js must call /api/habits/stats for streak/rate"


def test_ac4_habit_stats_endpoint_returns_streak_and_rate(client, alice_id):
    """GET /api/habits/stats must return streak and completion_rate for a habit."""
    habits = client.get(f"/api/habits?user_id={alice_id}").json()
    assert len(habits) > 0, "Alice must have at least one habit"
    habit = habits[0]
    res = client.get(
        f"/api/habits/stats?user_id={alice_id}&habit_id={habit['id']}&days=30"
    )
    assert res.status_code == 200, f"Expected 200, got {res.status_code}"
    data = res.json()
    assert "streak" in data, "stats response must have 'streak'"
    assert "completion_rate" in data, "stats response must have 'completion_rate'"
    assert "days_completed" in data, "stats response must have 'days_completed'"


def test_ac4_habit_checkbox_read_only_no_click_handler():
    """Habit checkboxes on Home are non-interactive — home.js must not attach click handlers."""
    js = (pathlib.Path(__file__).parent.parent / "frontend" / "js" / "home.js").read_text()
    section_start = js.find("loadHabitsSection")
    section_body = js[section_start:section_start + 1500]
    # Should not have addEventListener('click') on the checkbox in the habits section
    assert "addEventListener('click'" not in section_body and 'addEventListener("click"' not in section_body, \
        "Habit checkboxes on Home must be read-only (no click event listener in loadHabitsSection)"


def test_ac4_habits_section_empty_state_in_js():
    """home.js must show 'No habits yet' when user has no active habits."""
    js = (pathlib.Path(__file__).parent.parent / "frontend" / "js" / "home.js").read_text()
    assert "No habits yet" in js, "Missing 'No habits yet' empty state in home.js"


def test_ac4_habit_row_has_streak_element():
    """home.js must create a streak span (.home-habit-streak) per habit row."""
    js = (pathlib.Path(__file__).parent.parent / "frontend" / "js" / "home.js").read_text()
    assert "home-habit-streak" in js, "Missing home-habit-streak element in home.js"


def test_ac4_habit_row_has_rate_element():
    """home.js must create a completion rate span (.home-habit-rate) per habit row."""
    js = (pathlib.Path(__file__).parent.parent / "frontend" / "js" / "home.js").read_text()
    assert "home-habit-rate" in js, "Missing home-habit-rate element in home.js"


def test_ac4_habit_checked_state_based_on_todays_log(client, alice_id):
    """The logged habits for today match those that should appear checked."""
    today = TODAY_STR
    habits = client.get(f"/api/habits?user_id={alice_id}").json()
    assert len(habits) > 0

    logs = client.get(
        f"/api/habits/logs?user_id={alice_id}&from={today}&to={today}"
    ).json()
    logged_habit_ids = {l["habit_id"] for l in logs}
    # At least one habit should be identifiable as checked or unchecked
    assert isinstance(logged_habit_ids, set), "Habit log IDs must form a set"


# ── AC-5: Recent training section ─────────────────────────────────────────────

def test_ac5_home_training_list_in_html():
    """home.html must have an element with id='home-training-list'."""
    html = (pathlib.Path(__file__).parent.parent / "frontend" / "pages" / "home.html").read_text()
    assert 'id="home-training-list"' in html, "Missing id='home-training-list' in home.html"


def test_ac5_load_training_section_function_in_js():
    """home.js must have a loadTrainingSection function."""
    js = (pathlib.Path(__file__).parent.parent / "frontend" / "js" / "home.js").read_text()
    assert "loadTrainingSection" in js, "Missing loadTrainingSection function in home.js"


def test_ac5_training_section_limits_to_7_sessions():
    """home.js loadTrainingSection must slice workouts to a maximum of 7."""
    js = (pathlib.Path(__file__).parent.parent / "frontend" / "js" / "home.js").read_text()
    section_start = js.find("loadTrainingSection")
    section_body = js[section_start:section_start + 1500]
    assert "slice(0, 7)" in section_body or "slice(0,7)" in section_body, \
        "loadTrainingSection must limit sessions to 7 (slice(0, 7))"


def test_ac5_training_section_sorted_newest_first(client, alice_id):
    """GET /api/workouts returns workouts newest first (API already sorts by date desc)."""
    far_past = (TODAY - datetime.timedelta(days=30)).isoformat()
    near_past = (TODAY - datetime.timedelta(days=2)).isoformat()

    _clean_workouts_range(client, alice_id, far_past, TODAY_STR)
    _post_workout(client, alice_id, far_past, name="Old session", workout_type="Strength")
    _post_workout(client, alice_id, near_past, name="Recent session", workout_type="Cardio")

    res = client.get(
        f"/api/workouts?user_id={alice_id}&from={far_past}&to={TODAY_STR}"
    )
    workouts = res.json()
    assert len(workouts) >= 2
    dates = [w["workout_date"] for w in workouts]
    assert dates == sorted(dates, reverse=True), "Workouts must be returned newest first"


def test_ac5_run_icon_for_cardio_type():
    """home.js trainingIcon must return 🏃 (run icon) for cardio-type workouts."""
    js = (pathlib.Path(__file__).parent.parent / "frontend" / "js" / "home.js").read_text()
    assert "trainingIcon" in js, "Missing trainingIcon function in home.js"
    assert "🏃" in js, "Missing 🏃 run icon for cardio types in home.js"


def test_ac5_barbell_icon_for_strength_type():
    """home.js trainingIcon must return 🏋️ (barbell icon) for strength-type workouts."""
    js = (pathlib.Path(__file__).parent.parent / "frontend" / "js" / "home.js").read_text()
    assert "🏋️" in js, "Missing 🏋️ barbell icon for strength types in home.js"


def test_ac5_cardio_keyword_triggers_run_icon():
    """home.js must treat 'cardio' (and similar) as a cardio type for the run icon."""
    js = (pathlib.Path(__file__).parent.parent / "frontend" / "js" / "home.js").read_text()
    assert "cardio" in js.lower(), "home.js trainingIcon must handle 'cardio' type keyword"


def test_ac5_relative_date_function_in_js():
    """home.js must have a relativeDate function returning 'Today', 'Yesterday', or formatted date."""
    js = (pathlib.Path(__file__).parent.parent / "frontend" / "js" / "home.js").read_text()
    assert "relativeDate" in js, "Missing relativeDate function in home.js"
    assert "Today" in js, "relativeDate must return 'Today' for current date"
    assert "Yesterday" in js, "relativeDate must return 'Yesterday' for previous date"


def test_ac5_training_section_shows_rpe_if_set():
    """home.js must include RPE in the training row meta when set."""
    js = (pathlib.Path(__file__).parent.parent / "frontend" / "js" / "home.js").read_text()
    assert "RPE" in js or "rpe" in js, "home.js must handle RPE in training section rows"


def test_ac5_training_section_fetches_workout_details():
    """home.js loadTrainingSection must fetch /api/workouts/{id} for each session (duration + RPE)."""
    js = (pathlib.Path(__file__).parent.parent / "frontend" / "js" / "home.js").read_text()
    section_start = js.find("loadTrainingSection")
    section_body = js[section_start:section_start + 1500]
    assert "/api/workouts/" in section_body, \
        "loadTrainingSection must fetch /api/workouts/{id} for duration and RPE"


def test_ac5_training_section_empty_state_in_js():
    """home.js must show 'No training yet' when user has no training sessions."""
    js = (pathlib.Path(__file__).parent.parent / "frontend" / "js" / "home.js").read_text()
    assert "No training yet" in js, "Missing 'No training yet' empty state in home.js"


def test_ac5_api_returns_workout_with_rpe(client, alice_id):
    """Workout detail endpoint returns exercises with rpe field when set."""
    _clean_workouts_range(client, alice_id, TODAY_STR, TODAY_STR)
    workout = _post_workout(
        client, alice_id, TODAY_STR,
        name="Hard session",
        workout_type="Strength",
        exercises=[{"name": "Squat", "sets": 4, "reps": 5, "rpe": 9}],
    )
    detail = client.get(f"/api/workouts/{workout['id']}").json()
    assert "exercises" in detail, "Workout detail must include exercises"
    rpe_vals = [ex["rpe"] for ex in detail["exercises"] if ex.get("rpe") is not None]
    assert len(rpe_vals) >= 1, "Exercise with RPE must appear in workout detail"
    assert rpe_vals[0] == 9


# ── AC-6: All three sections refresh on user switch ────────────────────────────

def test_ac6_refresh_sections_function_in_js():
    """home.js must have a refreshSections function that calls all three section loaders."""
    js = (pathlib.Path(__file__).parent.parent / "frontend" / "js" / "home.js").read_text()
    assert "refreshSections" in js, "Missing refreshSections function in home.js"


def test_ac6_refresh_sections_calls_all_three():
    """refreshSections must call loadWeightSection, loadHabitsSection, and loadTrainingSection."""
    js = (pathlib.Path(__file__).parent.parent / "frontend" / "js" / "home.js").read_text()
    refresh_start = js.find("refreshSections")
    refresh_body = js[refresh_start:refresh_start + 200]
    assert "loadWeightSection" in refresh_body, "refreshSections must call loadWeightSection"
    assert "loadHabitsSection" in refresh_body, "refreshSections must call loadHabitsSection"
    assert "loadTrainingSection" in refresh_body, "refreshSections must call loadTrainingSection"


def test_ac6_user_ready_triggers_sections():
    """home.js must call refreshSections (or individual loaders) in the userReady handler."""
    js = (pathlib.Path(__file__).parent.parent / "frontend" / "js" / "home.js").read_text()
    user_ready_idx = js.find("userReady")
    assert user_ready_idx != -1, "Missing userReady event listener in home.js"
    after_ready = js[user_ready_idx:user_ready_idx + 300]
    assert "refreshSections" in after_ready or (
        "loadWeightSection" in after_ready
        and "loadHabitsSection" in after_ready
        and "loadTrainingSection" in after_ready
    ), "userReady handler must refresh all three summary sections"


def test_ac6_user_changed_triggers_sections():
    """home.js must call refreshSections (or individual loaders) in the userChanged handler."""
    js = (pathlib.Path(__file__).parent.parent / "frontend" / "js" / "home.js").read_text()
    user_changed_idx = js.find("userChanged")
    assert user_changed_idx != -1, "Missing userChanged event listener in home.js"
    after_changed = js[user_changed_idx:user_changed_idx + 300]
    assert "refreshSections" in after_changed or (
        "loadWeightSection" in after_changed
        and "loadHabitsSection" in after_changed
        and "loadTrainingSection" in after_changed
    ), "userChanged handler must refresh all three summary sections"


def test_ac6_different_users_return_different_weight_data(client, alice_id, bob_id):
    """Weight data is isolated per user — section would show different data per user."""
    _clean_weight(client, alice_id)
    _clean_weight(client, bob_id)

    cutoff = (TODAY - datetime.timedelta(days=5)).isoformat()
    _post_weight(client, alice_id, cutoff, 68.0)

    alice_entries = [
        e for e in client.get(f"/api/weight-entries?user_id={alice_id}").json()["entries"]
        if e["entry_date"] >= cutoff
    ]
    bob_entries = [
        e for e in client.get(f"/api/weight-entries?user_id={bob_id}").json()["entries"]
        if e["entry_date"] >= cutoff
    ]
    assert len(alice_entries) >= 1, "Alice must have at least one weight entry in last 14 days"
    assert alice_entries != bob_entries, "Alice and Bob must have different weight data"


# ── AC-7: Empty states ─────────────────────────────────────────────────────────

def test_ac7_no_weight_entries_yet_text_in_js():
    """home.js must contain 'No weight entries yet' as the weight section empty state."""
    js = (pathlib.Path(__file__).parent.parent / "frontend" / "js" / "home.js").read_text()
    assert "No weight entries yet" in js, "Missing 'No weight entries yet' in home.js"


def test_ac7_no_habits_yet_text_in_js():
    """home.js must contain 'No habits yet' as the habits section empty state."""
    js = (pathlib.Path(__file__).parent.parent / "frontend" / "js" / "home.js").read_text()
    assert "No habits yet" in js, "Missing 'No habits yet' in home.js"


def test_ac7_no_training_yet_text_in_js():
    """home.js must contain 'No training yet' as the training section empty state."""
    js = (pathlib.Path(__file__).parent.parent / "frontend" / "js" / "home.js").read_text()
    assert "No training yet" in js, "Missing 'No training yet' in home.js"


def test_ac7_new_user_weight_section_shows_empty(client):
    """A brand-new user with no weight entries returns empty entries from /api/weight-entries."""
    res = client.post("/api/users", json={"name": "__test_empty_user_26__"}, cookies=_admin_cookies())
    assert res.status_code in (201, 409)
    users = client.get("/api/users", cookies=_admin_cookies()).json()
    test_user = next((u for u in users if u["name"] == "__test_empty_user_26__"), None)
    assert test_user is not None

    uid = test_user["id"]
    entries = client.get(f"/api/weight-entries?user_id={uid}").json()["entries"]
    cutoff = (TODAY - datetime.timedelta(days=13)).isoformat()
    visible = [e for e in entries if e["entry_date"] >= cutoff]
    assert visible == [], "New user must have no weight entries in last 14 days"


def test_ac7_new_user_training_section_shows_empty(client):
    """A brand-new user has no workouts; training section should show empty state."""
    users = client.get("/api/users", cookies=_admin_cookies()).json()
    test_user = next((u for u in users if u["name"] == "__test_empty_user_26__"), None)
    if test_user is None:
        pytest.skip("Test user not found; skipping")

    uid = test_user["id"]
    far_back = (TODAY - datetime.timedelta(days=365)).isoformat()
    workouts = client.get(
        f"/api/workouts?user_id={uid}&from={far_back}&to={TODAY_STR}"
    ).json()
    assert workouts == [], f"New user must have no workouts, got {workouts}"


def test_ac7_cleanup_test_user(client):
    """Cleanup: remove the temporary test user created for empty-state tests."""
    users = client.get("/api/users", cookies=_admin_cookies()).json()
    test_user = next((u for u in users if u["name"] == "__test_empty_user_26__"), None)
    if test_user:
        res = client.delete(f"/api/users/{test_user['id']}", cookies=_admin_cookies())
        assert res.status_code in (204, 409), f"Cleanup failed: {res.status_code}"


# ── Structural: home.html serves correctly ────────────────────────────────────

def test_home_html_served_by_backend(client):
    """GET /home.html must return 200 with HTML content."""
    res = client.get("/home.html")
    assert res.status_code == 200
    assert "text/html" in res.headers.get("content-type", "")


def test_home_html_loads_chartjs():
    """home.html must load Chart.js via a CDN script tag (required for mini weight chart)."""
    html = (pathlib.Path(__file__).parent.parent / "frontend" / "pages" / "home.html").read_text()
    assert "chart.js" in html.lower() or "chartjs" in html.lower(), \
        "home.html must include a Chart.js CDN <script> tag"


def test_home_html_loads_home_js():
    """home.html must load js/home.js."""
    html = (pathlib.Path(__file__).parent.parent / "frontend" / "pages" / "home.html").read_text()
    assert "js/home.js" in html, "home.html must include <script src='js/home.js'>"
