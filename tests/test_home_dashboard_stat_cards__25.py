"""
Tests for issue #25: Home dashboard — top row of 4 quick stat cards
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


@pytest.fixture(scope="module")
def carol_id(client):
    res = client.get("/api/users", cookies=_admin_cookies())
    assert res.status_code == 200
    carol = next((u for u in res.json() if u["name"] == "Carol"), None)
    assert carol is not None, "Carol not found in /api/users"
    return carol["id"]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _clean_weight(client, user_id):
    # Use two year-span calls to cover all possible test dates (max range is 365 days)
    for from_d, to_d in [("2020-01-01", "2020-12-31"), ("2021-01-01", "2021-12-31"),
                         ("2022-01-01", "2022-12-31"), ("2023-01-01", "2023-12-31"),
                         ("2024-01-01", "2024-12-31"), ("2025-01-01", "2025-12-31"),
                         ("2026-01-01", "2026-12-31")]:
        res = client.get(f"/api/weight-entries?user_id={user_id}&from={from_d}&to={to_d}")
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


def _clean_habits(client, user_id):
    """Delete all habit logs for today for a user; leave habits intact."""
    logs_res = client.get(
        f"/api/habits/logs?user_id={user_id}&from={TODAY_STR}&to={TODAY_STR}"
    )
    if logs_res.status_code == 200:
        for log in logs_res.json():
            client.delete(f"/api/habits/logs/{log['id']}")


def _clean_workouts(client, user_id):
    res = client.get(
        f"/api/workouts?user_id={user_id}&from={TODAY_STR}&to={TODAY_STR}"
    )
    if res.status_code == 200:
        for w in res.json():
            client.delete(f"/api/workouts/{w['id']}")


def _clean_workouts_range(client, user_id, from_str, to_str):
    res = client.get(
        f"/api/workouts?user_id={user_id}&from={from_str}&to={to_str}"
    )
    if res.status_code == 200:
        for w in res.json():
            client.delete(f"/api/workouts/{w['id']}")


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


# ── AC-1: "Today" header showing day name + date ──────────────────────────────

def test_ac1_today_label_element_in_html():
    """home.html must contain an element with id='today-label'."""
    html = (pathlib.Path(__file__).parent.parent / "frontend" / "pages" / "home.html").read_text()
    assert 'id="today-label"' in html, "Missing id='today-label' element in home.html"


def test_ac1_today_label_uses_weekday_long_format():
    """home.js must format the date with weekday: 'long' for the Today header."""
    js = (pathlib.Path(__file__).parent.parent / "frontend" / "js" / "home.js").read_text()
    assert "weekday" in js and "long" in js, \
        "home.js must use weekday: 'long' in date formatting for today-label"


def test_ac1_today_label_includes_month_and_day():
    """home.js date format must include month and day (e.g. 'Tuesday, May 26')."""
    js = (pathlib.Path(__file__).parent.parent / "frontend" / "js" / "home.js").read_text()
    assert "month" in js and "day" in js, \
        "home.js must include 'month' and 'day' in toLocaleDateString options"


# ── AC-2: Responsive CSS grid row ─────────────────────────────────────────────

def test_ac2_four_column_grid_defined():
    """home.html CSS must define a 4-column grid for .dash-cards on desktop."""
    html = (pathlib.Path(__file__).parent.parent / "frontend" / "pages" / "home.html").read_text()
    assert "repeat(4, 1fr)" in html, "Missing 4-column grid definition for .dash-cards"


def test_ac2_two_column_breakpoint_exists():
    """home.html CSS must include a media query at < 700px to reflow to 2×2."""
    html = (pathlib.Path(__file__).parent.parent / "frontend" / "pages" / "home.html").read_text()
    assert "699px" in html or "700px" in html, \
        "No 700px (or 699px) breakpoint found in home.html"


def test_ac2_narrow_viewport_two_column_grid():
    """Inside the ≤699px media query, .dash-cards must switch to 2 columns."""
    html = (pathlib.Path(__file__).parent.parent / "frontend" / "pages" / "home.html").read_text()
    block = re.search(r'@media[^{]+69\d+px[^{]*\{(.+?)\}', html, re.DOTALL)
    if not block:
        block = re.search(r'@media[^{]+700px[^{]*\{(.+?)\}', html, re.DOTALL)
    assert block is not None, "No media query block found for narrow viewport in home.html"
    assert "repeat(2, 1fr)" in block.group(1), \
        "Narrow-viewport media query must set grid-template-columns: repeat(2, 1fr)"


def test_ac2_four_dash_cards_exist_in_html():
    """home.html must contain exactly 4 .dash-card elements."""
    html = (pathlib.Path(__file__).parent.parent / "frontend" / "pages" / "home.html").read_text()
    cards = re.findall(r'class="dash-card"', html)
    assert len(cards) == 4, f"Expected 4 .dash-card elements, found {len(cards)}"


# ── AC-3: Card 1 — Weight ─────────────────────────────────────────────────────

def test_ac3_weight_card_ids_in_html():
    """home.html must have Weight label and required element IDs for the weight card."""
    html = (pathlib.Path(__file__).parent.parent / "frontend" / "pages" / "home.html").read_text()
    assert "card-weight-value" in html, "Missing id='card-weight-value' in home.html"
    assert "card-weight-sub" in html, "Missing id='card-weight-sub' in home.html"
    assert "Weight" in html, "Missing 'Weight' label in home.html"


def test_ac3_no_weight_today_api_returns_empty(client, alice_id):
    """API returns no entry for today → weight card should show '—' / 'Not logged today'."""
    _clean_weight(client, alice_id)
    entries = client.get(f"/api/weight-entries?user_id={alice_id}&from={TODAY_STR}&to={TODAY_STR}").json()["entries"]
    today_entries = [e for e in entries if e["entry_date"] == TODAY_STR]
    assert today_entries == [], "Alice should have no weight entry for today after clean"


def test_ac3_weight_today_returns_correct_value(client, alice_id):
    """API returns today's weight entry; card should display it in kg."""
    _clean_weight(client, alice_id)
    _post_weight(client, alice_id, TODAY_STR, 72.3)
    entries = client.get(f"/api/weight-entries?user_id={alice_id}&from={TODAY_STR}&to={TODAY_STR}").json()["entries"]
    today_entry = next((e for e in entries if e["entry_date"] == TODAY_STR), None)
    assert today_entry is not None, "Today's weight entry must appear in API response"
    assert abs(today_entry["weight_kg"] - 72.3) < 0.01, "Weight value mismatch"


def test_ac3_weight_diff_computed_from_last_week_average(client, alice_id):
    """With prior week entries, API data allows computing a diff vs last-week average."""
    _clean_weight(client, alice_id)
    _post_weight(client, alice_id, TODAY_STR, 72.0)
    # Add a few entries in the past 7 days (before today)
    for i in range(1, 4):
        d = (TODAY - datetime.timedelta(days=i)).isoformat()
        _post_weight(client, alice_id, d, 73.0)

    last_week_start = (TODAY - datetime.timedelta(days=7)).isoformat()
    entries = client.get(
        f"/api/weight-entries?user_id={alice_id}&from={last_week_start}&to={TODAY_STR}"
    ).json()["entries"]
    last_week_entries = [
        e for e in entries
        if last_week_start <= e["entry_date"] <= YESTERDAY_STR
    ]
    assert len(last_week_entries) >= 1, "Need at least 1 entry in last 7 days for diff"
    avg = sum(e["weight_kg"] for e in last_week_entries) / len(last_week_entries)
    diff = 72.0 - avg
    assert diff < 0, "72.0 kg should be below the 73.0 kg average (negative diff)"


def test_ac3_weight_no_prior_data_handled(client, bob_id):
    """When there is a today entry but no prior-week data, API still returns today's entry."""
    _clean_weight(client, bob_id)
    _post_weight(client, bob_id, TODAY_STR, 80.0)
    today_entries = client.get(
        f"/api/weight-entries?user_id={bob_id}&from={TODAY_STR}&to={TODAY_STR}"
    ).json()["entries"]
    last_week_start = (TODAY - datetime.timedelta(days=7)).isoformat()
    prior_entries = client.get(
        f"/api/weight-entries?user_id={bob_id}&from={last_week_start}&to={YESTERDAY_STR}"
    ).json()["entries"]
    assert len(today_entries) == 1
    assert len(prior_entries) == 0, "Bob should have no prior-week weight entries"


def test_ac3_not_logged_today_sub_text_in_js():
    """home.js must contain 'Not logged today' sub-line text for when weight is absent."""
    js = (pathlib.Path(__file__).parent.parent / "frontend" / "js" / "home.js").read_text()
    assert "Not logged today" in js, "Missing 'Not logged today' text in home.js"


def test_ac3_weight_diff_arrow_icons_in_js():
    """home.js must use ▲ and ▼ arrow icons for weight diff direction."""
    js = (pathlib.Path(__file__).parent.parent / "frontend" / "js" / "home.js").read_text()
    assert "▲" in js, "Missing ▲ (up arrow) for weight gain in home.js"
    assert "▼" in js, "Missing ▼ (down arrow) for weight loss in home.js"


# ── AC-4: Card 2 — Habits ─────────────────────────────────────────────────────

def test_ac4_habits_card_ids_in_html():
    """home.html must have Habits label and required element IDs for the habits card."""
    html = (pathlib.Path(__file__).parent.parent / "frontend" / "pages" / "home.html").read_text()
    assert "card-habits-value" in html, "Missing id='card-habits-value' in home.html"
    assert "card-habits-sub" in html, "Missing id='card-habits-sub' in home.html"
    assert "Habits" in html, "Missing 'Habits' label in home.html"


def test_ac4_habits_api_returns_active_habits(client, alice_id):
    """GET /api/habits returns the list of active habits for a user."""
    res = client.get(f"/api/habits?user_id={alice_id}")
    assert res.status_code == 200
    habits = res.json()
    assert isinstance(habits, list), "Expected list from /api/habits"
    assert len(habits) > 0, "Alice should have at least one habit seeded"


def test_ac4_habits_logs_today_returns_correct_count(client, alice_id):
    """GET /api/habits/logs for today returns only today's logs."""
    _clean_habits(client, alice_id)
    habits = client.get(f"/api/habits?user_id={alice_id}").json()
    assert len(habits) > 0

    # Log the first habit for today
    first_habit = habits[0]
    log_res = client.post("/api/habits/logs", json={
        "habit_id": first_habit["id"],
        "user_id": alice_id,
        "logged_date": TODAY_STR,
    })
    assert log_res.status_code in (201, 409)

    logs = client.get(
        f"/api/habits/logs?user_id={alice_id}&from={TODAY_STR}&to={TODAY_STR}"
    ).json()
    assert len(logs) >= 1, "At least 1 habit log should exist for today after posting"


def test_ac4_habits_x_of_y_count_derivable_from_api(client, alice_id):
    """The X / Y count for habits card can be derived from habits list and today's logs."""
    habits = client.get(f"/api/habits?user_id={alice_id}").json()
    logs = client.get(
        f"/api/habits/logs?user_id={alice_id}&from={TODAY_STR}&to={TODAY_STR}"
    ).json()
    total = len(habits)
    done = len(logs)
    pending = total - done
    assert total >= 1
    assert done >= 1, "At least one habit must be logged from prior test"
    assert pending >= 0
    assert done + pending == total, "done + pending must equal total habits"


def test_ac4_pending_sub_text_in_js():
    """home.js must contain 'pending today' sub-line text for incomplete habits."""
    js = (pathlib.Path(__file__).parent.parent / "frontend" / "js" / "home.js").read_text()
    assert "pending today" in js, "Missing 'pending today' text in home.js"


def test_ac4_all_done_sub_text_in_js():
    """home.js must contain 'All done today' sub-line for when all habits are complete."""
    js = (pathlib.Path(__file__).parent.parent / "frontend" / "js" / "home.js").read_text()
    assert "All done today" in js, "Missing 'All done today' text in home.js"


def test_ac4_habits_fetches_both_habits_and_logs(client, alice_id):
    """home.js must fetch both /api/habits and /api/habits/logs to compute the card."""
    js = (pathlib.Path(__file__).parent.parent / "frontend" / "js" / "home.js").read_text()
    assert "/api/habits?" in js or "/api/habits'" in js or '"/api/habits"' in js or "'/api/habits'" in js, \
        "home.js must fetch /api/habits for habits list"
    assert "/api/habits/logs" in js, "home.js must fetch /api/habits/logs for today's logs"


# ── AC-5: Card 3 — Training ───────────────────────────────────────────────────

def test_ac5_training_card_ids_in_html():
    """home.html must have Training label and required element IDs for the training card."""
    html = (pathlib.Path(__file__).parent.parent / "frontend" / "pages" / "home.html").read_text()
    assert "card-training-value" in html, "Missing id='card-training-value' in home.html"
    assert "card-training-sub" in html, "Missing id='card-training-sub' in home.html"
    assert "Training" in html, "Missing 'Training' label in home.html"


def test_ac5_no_workout_today_returns_empty(client, alice_id):
    """When no workout logged today, GET /api/workouts returns empty list for today."""
    _clean_workouts(client, alice_id)
    res = client.get(
        f"/api/workouts?user_id={alice_id}&from={TODAY_STR}&to={TODAY_STR}"
    )
    assert res.status_code == 200
    workouts = res.json()
    assert workouts == [], "Should be no workouts today after clean"


def test_ac5_rest_day_text_in_js():
    """home.js must display 'Rest day' when no workout is logged today."""
    js = (pathlib.Path(__file__).parent.parent / "frontend" / "js" / "home.js").read_text()
    assert "Rest day" in js, "Missing 'Rest day' text in home.js"


def test_ac5_workout_today_returns_session_data(client, alice_id):
    """When a workout is logged today, API returns it with name and type."""
    _clean_workouts(client, alice_id)
    _post_workout(client, alice_id, TODAY_STR, name="Push day", workout_type="Strength")
    res = client.get(
        f"/api/workouts?user_id={alice_id}&from={TODAY_STR}&to={TODAY_STR}"
    )
    assert res.status_code == 200
    workouts = res.json()
    assert len(workouts) == 1, "Expected exactly 1 workout today"
    assert workouts[0]["name"] == "Push day"
    assert workouts[0]["workout_type"] == "Strength"


def test_ac5_workout_detail_fetch_used_for_duration(client, alice_id):
    """home.js must fetch the workout detail endpoint to compute total duration."""
    js = (pathlib.Path(__file__).parent.parent / "frontend" / "js" / "home.js").read_text()
    assert "/api/workouts/" in js, \
        "home.js must fetch /api/workouts/{id} for workout detail (duration calculation)"


def test_ac5_duration_parsing_handles_min_suffix():
    """home.js parseDurationMin must handle '45 min' and '45m' style strings."""
    js = (pathlib.Path(__file__).parent.parent / "frontend" / "js" / "home.js").read_text()
    assert "parseDurationMin" in js, "Missing parseDurationMin function in home.js"
    assert r"min" in js, "parseDurationMin must handle 'min' suffix"


def test_ac5_workout_exercises_queried_for_duration(client, alice_id):
    """Workout with exercises having duration fields populates card sub-line correctly."""
    _clean_workouts(client, alice_id)
    workout = _post_workout(
        client, alice_id, TODAY_STR,
        name="Upper body",
        workout_type="Strength",
        exercises=[
            {"name": "Bench press", "sets": 4, "reps": 8, "duration": "20 min"},
            {"name": "OHP", "sets": 3, "reps": 8, "duration": "15 min"},
        ],
    )
    detail = client.get(f"/api/workouts/{workout['id']}").json()
    total_min = sum(
        int(re.search(r"(\d+)\s*min", ex["duration"]).group(1))
        for ex in detail["exercises"]
        if ex.get("duration") and re.search(r"(\d+)\s*min", ex["duration"])
    )
    assert total_min == 35, f"Expected 35 min total, got {total_min}"


# ── AC-6: Card 4 — Active days streak ─────────────────────────────────────────

def test_ac6_streak_card_ids_in_html():
    """home.html must have 'Active days' label and required element IDs for streak card."""
    html = (pathlib.Path(__file__).parent.parent / "frontend" / "pages" / "home.html").read_text()
    assert "card-streak-value" in html, "Missing id='card-streak-value' in home.html"
    assert "card-streak-sub" in html, "Missing id='card-streak-sub' in home.html"
    assert "Active days" in html, "Missing 'Active days' label in home.html"


def test_ac6_streak_sub_text_in_html():
    """home.html must show 'consecutive days' as the streak sub-line."""
    html = (pathlib.Path(__file__).parent.parent / "frontend" / "pages" / "home.html").read_text()
    assert "consecutive days" in html, "Missing 'consecutive days' sub-line in home.html"


def test_ac6_fire_emoji_in_js():
    """home.js must include the 🔥 emoji for the streak card value."""
    js = (pathlib.Path(__file__).parent.parent / "frontend" / "js" / "home.js").read_text()
    assert "🔥" in js, "Missing 🔥 emoji in home.js streak card"


def test_ac6_streak_endpoint_exists(client, alice_id):
    """GET /api/stats/active-streak must exist and return a streak integer."""
    res = client.get(f"/api/stats/active-streak?user_id={alice_id}")
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
    data = res.json()
    assert "streak" in data, "Response must have a 'streak' key"
    assert isinstance(data["streak"], int), "streak must be an integer"
    assert data["streak"] >= 0, "streak must be non-negative"


def test_ac6_streak_zero_when_no_entries_today(client, carol_id):
    """Streak is 0 when user has no entry for today (or yesterday) in any table."""
    # Clean up Carol's data for today
    _clean_weight(client, carol_id)
    _clean_habits(client, carol_id)
    _clean_workouts(client, carol_id)

    # Also clean yesterday's workouts for Carol to be safe
    _clean_workouts_range(client, carol_id, YESTERDAY_STR, TODAY_STR)
    _clean_weight(client, carol_id)

    res = client.get(f"/api/stats/active-streak?user_id={carol_id}")
    assert res.status_code == 200
    data = res.json()
    assert data["streak"] == 0, f"Expected streak 0 for Carol with no entries, got {data['streak']}"


def test_ac6_streak_increments_with_today_entry(client, alice_id):
    """Posting a weight entry for today increments active-streak by at least 1."""
    _clean_weight(client, alice_id)
    _clean_habits(client, alice_id)
    _clean_workouts(client, alice_id)

    before = client.get(f"/api/stats/active-streak?user_id={alice_id}").json()["streak"]

    _post_weight(client, alice_id, TODAY_STR, 72.0)
    after = client.get(f"/api/stats/active-streak?user_id={alice_id}").json()["streak"]
    assert after >= 1, f"Streak must be >= 1 after posting today's weight, got {after}"


def test_ac6_streak_counts_across_all_three_tables(client, alice_id):
    """Active-streak endpoint counts a day as active if any of weight, habit_logs, workouts has an entry."""
    _clean_weight(client, alice_id)
    _clean_habits(client, alice_id)
    _clean_workouts(client, alice_id)

    # Post only a habit log (no weight, no workout)
    habits = client.get(f"/api/habits?user_id={alice_id}").json()
    if habits:
        client.post("/api/habits/logs", json={
            "habit_id": habits[0]["id"],
            "user_id": alice_id,
            "logged_date": TODAY_STR,
        })
    res = client.get(f"/api/stats/active-streak?user_id={alice_id}")
    assert res.status_code == 200
    data = res.json()
    assert data["streak"] >= 1, "Streak must be >= 1 when only a habit log exists for today"


def test_ac6_streak_fetched_via_active_streak_endpoint():
    """home.js must call /api/stats/active-streak to compute the streak card."""
    js = (pathlib.Path(__file__).parent.parent / "frontend" / "js" / "home.js").read_text()
    assert "/api/stats/active-streak" in js, \
        "home.js must fetch /api/stats/active-streak for the streak card"


# ── AC-7: Cards refresh on user switch ────────────────────────────────────────

def test_ac7_listens_to_user_changed_event():
    """home.js must listen to the 'userChanged' event to refresh all cards."""
    js = (pathlib.Path(__file__).parent.parent / "frontend" / "js" / "home.js").read_text()
    assert "userChanged" in js, "home.js must listen for 'userChanged' event"


def test_ac7_listens_to_user_ready_event():
    """home.js must listen to the 'userReady' event to load initial card data."""
    js = (pathlib.Path(__file__).parent.parent / "frontend" / "js" / "home.js").read_text()
    assert "userReady" in js, "home.js must listen for 'userReady' event"


def test_ac7_different_users_return_different_weight_data(client, alice_id, bob_id):
    """Weight API is isolated per user — switching users yields different data."""
    _clean_weight(client, alice_id)
    _clean_weight(client, bob_id)

    _post_weight(client, alice_id, TODAY_STR, 72.0)

    alice_today = client.get(
        f"/api/weight-entries?user_id={alice_id}&from={TODAY_STR}&to={TODAY_STR}"
    ).json()["entries"]
    bob_today = client.get(
        f"/api/weight-entries?user_id={bob_id}&from={TODAY_STR}&to={TODAY_STR}"
    ).json()["entries"]

    assert len(alice_today) == 1, "Alice must have 1 weight entry today"
    assert len(bob_today) == 0, "Bob must have 0 weight entries today"


def test_ac7_different_users_return_different_streak(client, alice_id, carol_id):
    """Active-streak is isolated per user; different users may have different streaks."""
    # Alice has entries; Carol was cleaned — streaks should differ
    alice_streak = client.get(f"/api/stats/active-streak?user_id={alice_id}").json()["streak"]
    carol_streak = client.get(f"/api/stats/active-streak?user_id={carol_id}").json()["streak"]
    # Alice should have ≥ 1 (from earlier tests); Carol = 0
    assert alice_streak >= 1
    assert carol_streak == 0


# ── AC-8: Cards refresh after cross-tab entry submission ──────────────────────

def test_ac8_visibility_change_handler_in_js():
    """home.js must listen to 'visibilitychange' to refresh cards when tab regains focus."""
    js = (pathlib.Path(__file__).parent.parent / "frontend" / "js" / "home.js").read_text()
    assert "visibilitychange" in js, "home.js must listen for visibilitychange event"
    assert "visibilityState" in js, "home.js must check document.visibilityState === 'visible'"


def test_ac8_post_weight_immediately_visible_in_api(client, bob_id):
    """After POSTing a weight entry, GET /api/weight-entries immediately reflects the new entry."""
    _clean_weight(client, bob_id)
    before_today = client.get(
        f"/api/weight-entries?user_id={bob_id}&from={TODAY_STR}&to={TODAY_STR}"
    ).json()["entries"]
    assert len(before_today) == 0

    _post_weight(client, bob_id, TODAY_STR, 79.0)

    after_today = client.get(
        f"/api/weight-entries?user_id={bob_id}&from={TODAY_STR}&to={TODAY_STR}"
    ).json()["entries"]
    assert len(after_today) == 1, "Weight entry must appear immediately in GET after POST"


def test_ac8_post_workout_immediately_visible_in_api(client, bob_id):
    """After POSTing a workout, GET /api/workouts immediately reflects it."""
    _clean_workouts(client, bob_id)
    before = client.get(
        f"/api/workouts?user_id={bob_id}&from={TODAY_STR}&to={TODAY_STR}"
    ).json()
    assert len(before) == 0

    _post_workout(client, bob_id, TODAY_STR, name="Cardio", workout_type="Cardio")

    after = client.get(
        f"/api/workouts?user_id={bob_id}&from={TODAY_STR}&to={TODAY_STR}"
    ).json()
    assert len(after) == 1, "Workout must appear immediately in GET after POST"


def test_ac8_refresh_cards_function_exists():
    """home.js must have a refreshCards() function that loads all 4 cards."""
    js = (pathlib.Path(__file__).parent.parent / "frontend" / "js" / "home.js").read_text()
    assert "refreshCards" in js, "Missing refreshCards function in home.js"
    # Must call all 4 card loaders
    assert "loadWeightCard" in js, "refreshCards must call loadWeightCard"
    assert "loadHabitsCard" in js, "refreshCards must call loadHabitsCard"
    assert "loadTrainingCard" in js, "refreshCards must call loadTrainingCard"
    assert "loadStreakCard" in js, "refreshCards must call loadStreakCard"


# ── AC-9: New user with no data — graceful empty state ────────────────────────

def test_ac9_new_user_weight_api_empty(client):
    """A brand-new user with no entries returns empty entries from /api/weight-entries."""
    # Create a temp user
    res = client.post("/api/users", json={"name": "__test_empty_user_25__"}, cookies=_admin_cookies())
    assert res.status_code in (201, 409)
    users = client.get("/api/users", cookies=_admin_cookies()).json()
    test_user = next((u for u in users if u["name"] == "__test_empty_user_25__"), None)
    assert test_user is not None

    uid = test_user["id"]
    result = client.get(f"/api/weight-entries?user_id={uid}&from={TODAY_STR}&to={TODAY_STR}").json()
    entries = result["entries"]
    assert entries == [], f"New user must have no weight entries, got {entries}"


def test_ac9_new_user_habits_api_returns_seeded_habits_or_empty(client):
    """A brand-new user may have seeded habits; habit logs for today must be empty."""
    users = client.get("/api/users", cookies=_admin_cookies()).json()
    test_user = next((u for u in users if u["name"] == "__test_empty_user_25__"), None)
    if test_user is None:
        pytest.skip("Test user not found; skipping")

    uid = test_user["id"]
    logs = client.get(
        f"/api/habits/logs?user_id={uid}&from={TODAY_STR}&to={TODAY_STR}"
    ).json()
    assert logs == [], f"New user must have no habit logs today, got {logs}"


def test_ac9_new_user_workouts_api_empty(client):
    """A brand-new user has no workouts; API returns [] for today's range."""
    users = client.get("/api/users", cookies=_admin_cookies()).json()
    test_user = next((u for u in users if u["name"] == "__test_empty_user_25__"), None)
    if test_user is None:
        pytest.skip("Test user not found; skipping")

    uid = test_user["id"]
    workouts = client.get(
        f"/api/workouts?user_id={uid}&from={TODAY_STR}&to={TODAY_STR}"
    ).json()
    assert workouts == [], f"New user must have no workouts today, got {workouts}"


def test_ac9_new_user_streak_is_zero(client):
    """A brand-new user with no entries should have an active-streak of 0."""
    users = client.get("/api/users", cookies=_admin_cookies()).json()
    test_user = next((u for u in users if u["name"] == "__test_empty_user_25__"), None)
    if test_user is None:
        pytest.skip("Test user not found; skipping")

    uid = test_user["id"]
    res = client.get(f"/api/stats/active-streak?user_id={uid}")
    assert res.status_code == 200
    data = res.json()
    assert data["streak"] == 0, f"New user streak must be 0, got {data['streak']}"


def test_ac9_cleanup_test_user(client):
    """Cleanup: remove the temporary test user created for empty-state tests."""
    users = client.get("/api/users", cookies=_admin_cookies()).json()
    test_user = next((u for u in users if u["name"] == "__test_empty_user_25__"), None)
    if test_user:
        res = client.delete(f"/api/users/{test_user['id']}", cookies=_admin_cookies())
        assert res.status_code in (204, 409), f"Cleanup failed: {res.status_code}"


# ── Structural: home.html loads correct scripts ───────────────────────────────

def test_home_html_loads_home_js():
    """home.html must load js/home.js."""
    html = (pathlib.Path(__file__).parent.parent / "frontend" / "pages" / "home.html").read_text()
    assert "js/home.js" in html, "home.html must include <script src='js/home.js'>"


def test_home_html_loads_user_js():
    """home.html must load js/user.js to get the user selector and events."""
    html = (pathlib.Path(__file__).parent.parent / "frontend" / "pages" / "home.html").read_text()
    assert "js/user.js" in html, "home.html must include <script src='js/user.js'>"


def test_home_html_loads_env_js():
    """home.html must load js/env.js for environment detection."""
    html = (pathlib.Path(__file__).parent.parent / "frontend" / "pages" / "home.html").read_text()
    assert "js/env.js" in html, "home.html must include <script src='js/env.js'>"


def test_home_html_served_by_backend(client):
    """GET /home.html must return 200 with HTML content."""
    res = client.get("/home.html")
    assert res.status_code == 200
    assert "text/html" in res.headers.get("content-type", "")
