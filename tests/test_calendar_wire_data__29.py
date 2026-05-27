"""
Tests for issue #29: Calendar tab — wire weight, habit, and training data into day cells
Server under test: http://127.0.0.1:9001
"""
import pathlib
import re

import httpx
import pytest

BASE = "http://127.0.0.1:9001"

HTML = (pathlib.Path(__file__).parent.parent / "calendar.html").read_text()
JS   = (pathlib.Path(__file__).parent.parent / "js" / "calendar.js").read_text()


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c


@pytest.fixture(scope="module")
def alice_id(client):
    """Return Alice's user_id (user with seeded weight/habits/training data)."""
    users = client.get("/api/users").json()
    alice = next((u for u in users if u["name"].lower() == "alice"), None)
    assert alice, "Alice user not found in UAT database"
    return alice["id"]


# ── AC-1: Fetch weight, habits/logs, and training on page load ────────────────

def test_ac1_js_fetches_weight_api():
    """calendar.js must call /api/weight with user_id on page load."""
    assert "/api/weight" in JS, "calendar.js must fetch /api/weight"
    assert "user_id" in JS, "calendar.js must pass user_id to /api/weight"


def test_ac1_js_fetches_habits_logs_api():
    """calendar.js must call /api/habits/logs with user_id and date range."""
    assert "/api/habits/logs" in JS, "calendar.js must fetch /api/habits/logs"
    assert "from" in JS and "to" in JS, \
        "calendar.js must pass from/to date range params to /api/habits/logs"


def test_ac1_js_fetches_training_api():
    """calendar.js must call a training/workouts endpoint with user_id and date range.
    NOTE: AC specifies /api/training but implementation uses /api/workouts — the
    backend endpoint is /api/workouts; this test accepts either name.
    """
    has_training_fetch = "/api/training" in JS or "/api/workouts" in JS
    assert has_training_fetch, \
        "calendar.js must fetch training/workout data from the API"


def test_ac1_weight_fetch_includes_user_id():
    """calendar.js /api/weight call must include user_id query param."""
    assert "user_id" in JS, "calendar.js must pass user_id to weight API"
    weight_idx = JS.find("/api/weight")
    context = JS[weight_idx:weight_idx + 100]
    assert "user_id" in context, "user_id must appear in the /api/weight fetch call"


def test_ac1_habits_logs_fetch_has_date_range():
    """calendar.js /api/habits/logs call must include from and to date range params."""
    logs_idx = JS.find("/api/habits/logs")
    assert logs_idx != -1, "calendar.js must call /api/habits/logs"
    context = JS[logs_idx:logs_idx + 150]
    assert "from" in context and "to" in context, \
        "/api/habits/logs call must include from and to params for the month range"


def test_ac1_training_fetch_has_date_range():
    """calendar.js training/workouts fetch must include from and to date range params."""
    workouts_idx = JS.find("/api/workouts")
    training_idx = JS.find("/api/training")
    idx = workouts_idx if workouts_idx != -1 else training_idx
    assert idx != -1, "calendar.js must call workouts/training API"
    context = JS[idx:idx + 150]
    assert "from" in context and "to" in context, \
        "Training/workouts fetch must include from and to date range params"


def test_ac1_all_three_fetches_in_parallel():
    """calendar.js must fetch weight, habits/logs, and workouts together (Promise.all)."""
    assert "Promise.all" in JS, \
        "calendar.js must use Promise.all to fetch all three data sources in parallel"


def test_ac1_weight_api_returns_200_for_user(client, alice_id):
    """GET /api/weight?user_id=<alice> must return 200."""
    res = client.get(f"/api/weight?user_id={alice_id}")
    assert res.status_code == 200, f"Expected 200, got {res.status_code}"
    assert isinstance(res.json(), list), "Response must be a list"


def test_ac1_habits_logs_api_returns_200_with_range(client, alice_id):
    """GET /api/habits/logs with user_id and date range must return 200."""
    res = client.get(
        f"/api/habits/logs?user_id={alice_id}&from=2026-05-01&to=2026-05-31"
    )
    assert res.status_code == 200, f"Expected 200, got {res.status_code}"
    assert isinstance(res.json(), list), "Response must be a list"


def test_ac1_workouts_api_returns_200_with_range(client, alice_id):
    """GET /api/workouts with user_id and date range must return 200.
    AC specifies /api/training; implementation uses /api/workouts — testing actual endpoint.
    """
    res = client.get(
        f"/api/workouts?user_id={alice_id}&from=2026-05-01&to=2026-05-31"
    )
    assert res.status_code == 200, f"Expected 200, got {res.status_code}"
    assert isinstance(res.json(), list), "Response must be a list"


# ── AC-2: Per-day cell layout ─────────────────────────────────────────────────

def test_ac2_weight_value_rendered_top_right():
    """calendar.js must create a .cal-weight-val element for days with a weight entry."""
    assert "cal-weight-val" in JS, \
        "calendar.js must create .cal-weight-val element for the weight value"


def test_ac2_weight_value_formatted_with_kg():
    """calendar.js must format weight as e.g. '72.4kg' (toFixed(1) + 'kg')."""
    assert "toFixed(1)" in JS, "calendar.js must format weight with toFixed(1)"
    assert "kg" in JS, "calendar.js must append 'kg' to the weight value"


def test_ac2_weight_in_top_right_position():
    """calendar.html CSS must position weight value top-right in the cell layout."""
    assert "cal-cell-top" in HTML, "Missing .cal-cell-top layout container in calendar.html"
    assert "justify-content" in HTML or "space-between" in HTML, \
        "cal-cell-top must use flex layout to position weight top-right"


def test_ac2_habit_dots_created_per_habit():
    """calendar.js must create one .cal-habit-dot per habit in the habits row."""
    assert "cal-habit-dot" in JS, "calendar.js must create .cal-habit-dot per habit"
    assert "cal-habits-row" in JS, "calendar.js must create .cal-habits-row container"


def test_ac2_habit_dot_done_class():
    """calendar.js must add 'done' class to a dot when habit is logged for the day."""
    assert "done" in JS, "calendar.js must add 'done' class to completed habit dots"
    done_idx = JS.find('"done"')
    if done_idx == -1:
        done_idx = JS.find("'done'")
    assert done_idx != -1, "calendar.js must use string 'done' for completed habit class"


def test_ac2_habit_dot_missed_class():
    """calendar.js must add 'missed' class to a dot for past days where habit wasn't logged."""
    assert "missed" in JS, "calendar.js must add 'missed' class to missed habit dots"


def test_ac2_habit_dot_dashed_today_pending():
    """calendar.js must add 'today-pending' class for today's unlogged habits (dashed border)."""
    assert "today-pending" in JS, \
        "calendar.js must add 'today-pending' class for today's not-yet-logged habits"
    assert "dashed" in HTML or "today-pending" in HTML, \
        "calendar.html CSS must define dashed border for .today-pending dots"


def test_ac2_training_icon_rendered():
    """calendar.js must create a training icon element for days with a workout."""
    assert "cal-training-row" in JS, "calendar.js must create .cal-training-row container"
    assert "cal-training-icon" in JS, "calendar.js must create .cal-training-icon element"


def test_ac2_training_icon_types_correct():
    """calendar.js must map workout types to correct tabler icon classes."""
    assert "ti-run" in JS, "calendar.js must use ti-run for cardio/running workouts"
    assert "ti-barbell" in JS, "calendar.js must use ti-barbell for strength workouts"
    assert "ti-yoga" in JS, "calendar.js must use ti-yoga for yoga/flexibility workouts"


def test_ac2_training_icon_cardio_mapping():
    """calendar.js must map cardio/running/swimming/cycling workout types to ti-run."""
    assert "cardio" in JS.lower() or "run" in JS or "swim" in JS, \
        "calendar.js must handle cardio/run/swim workout types for ti-run icon"
    assert "ti-run" in JS, "calendar.js must return ti-run for cardio workouts"


def test_ac2_training_icon_strength_mapping():
    """calendar.js must map strength workout types to ti-barbell."""
    assert "strength" in JS.lower(), "calendar.js must handle 'strength' workout type"
    assert "ti-barbell" in JS, "calendar.js must return ti-barbell for strength workouts"


def test_ac2_training_row_css_defined():
    """calendar.html CSS must define .cal-training-row layout."""
    assert "cal-training-row" in HTML, "Missing .cal-training-row CSS in calendar.html"


# ── AC-3: Today's cell uses info-colored variants ─────────────────────────────

def test_ac3_today_weight_info_color():
    """calendar.html CSS must set info color (#0284c7) for today's weight value."""
    assert "cal-cell.today .cal-weight-val" in HTML or \
           (".cal-cell.today" in HTML and "cal-weight-val" in HTML), \
        "calendar.html must set info-colored text for today's weight value"
    assert "0284c7" in HTML, \
        "calendar.html must use info blue (#0284c7) for today cell highlights"


def test_ac3_today_habit_dots_info_color():
    """calendar.html CSS must apply info-color to habit dots inside today's cell."""
    assert "cal-cell.today" in HTML and "cal-habit-dot" in HTML, \
        "calendar.html must style habit dots differently inside today's cell"
    today_done_match = re.search(
        r'\.cal-cell\.today.*?\.cal-habit-dot', HTML, re.DOTALL
    )
    assert today_done_match or (
        "cal-cell.today" in HTML and "0284c7" in HTML
    ), "calendar.html must use info-color for today's habit dots"


def test_ac3_today_training_icon_info_color():
    """calendar.html CSS must apply info color to today's training icon."""
    assert "cal-cell.today" in HTML and "cal-training-icon" in HTML, \
        "calendar.html must have a CSS rule for today's training icon"


def test_ac3_today_day_num_info_color():
    """calendar.html CSS must set day number to info color (#0284c7) for today's cell."""
    today_num_match = re.search(r'\.cal-cell\.today\s.*?cal-day-num', HTML, re.DOTALL)
    assert today_num_match or (
        "cal-cell.today" in HTML and "cal-day-num" in HTML and "0284c7" in HTML
    ), "calendar.html must use info-color for today's day number"


# ── AC-4: A day with no data shows only the day number ────────────────────────

def test_ac4_weight_only_if_data_present():
    """calendar.js must only render .cal-weight-val when a weight entry exists for the date."""
    weight_check_pattern = re.search(
        r'calData\.weights\[dateStr\].*?undefined|calData\.weights.*?!== undefined',
        JS, re.DOTALL
    )
    assert weight_check_pattern or "calData.weights[dateStr] !== undefined" in JS, \
        "calendar.js must check if weight entry exists before rendering weight value"


def test_ac4_habits_row_only_if_habits_exist():
    """calendar.js must only render habits row when habits data is present."""
    assert "calData.habits.length" in JS or "habits.length" in JS, \
        "calendar.js must check habits.length before rendering habits row"


def test_ac4_training_row_only_if_workout_exists():
    """calendar.js must only render training row when a workout entry exists for the date."""
    assert "dayWorkouts" in JS or "workouts[dateStr]" in JS, \
        "calendar.js must check for workout data before rendering training row"
    assert "dayWorkouts.length > 0" in JS or "dayWorkouts &&" in JS, \
        "calendar.js must guard training row render with a truthy/length check"


def test_ac4_out_of_month_cell_gets_no_data():
    """calendar.js must skip data population for out-of-month cells."""
    assert "if (!inMonth) return" in JS or "!inMonth" in JS, \
        "calendar.js must return early for out-of-month cells to avoid populating data"


# ── AC-5: Show/Hide checkboxes filter rendered data ───────────────────────────

def test_ac5_filter_weight_checkbox_exists():
    """calendar.html must have filter-weight checkbox."""
    assert 'id="filter-weight"' in HTML, "Missing id='filter-weight' in calendar.html"
    assert "Show Weight" in HTML, "Missing 'Show Weight' label"


def test_ac5_filter_habits_checkbox_exists():
    """calendar.html must have filter-habits checkbox."""
    assert 'id="filter-habits"' in HTML, "Missing id='filter-habits' in calendar.html"
    assert "Show Habits" in HTML, "Missing 'Show Habits' label"


def test_ac5_filter_training_checkbox_exists():
    """calendar.html must have filter-training checkbox."""
    assert 'id="filter-training"' in HTML, "Missing id='filter-training' in calendar.html"
    assert "Show Training" in HTML, "Missing 'Show Training' label"


def test_ac5_filter_checkboxes_default_checked():
    """All three filter checkboxes must default to checked."""
    for cb_id in ("filter-weight", "filter-habits", "filter-training"):
        idx = HTML.find(f'id="{cb_id}"')
        assert idx != -1, f"Missing {cb_id} checkbox"
        surrounding = HTML[max(0, idx - 60):idx + 120]
        assert "checked" in surrounding, f"{cb_id} must default to checked"


def test_ac5_apply_filters_function_exists():
    """calendar.js must have an applyFilters function that toggles element visibility."""
    assert "applyFilters" in JS, "calendar.js must have applyFilters function"


def test_ac5_filter_hides_weight_elements():
    """calendar.js applyFilters must hide/show .cal-weight-val based on filter-weight."""
    assert "cal-weight-val" in JS, "calendar.js must reference .cal-weight-val in filter logic"
    apply_idx = JS.find("applyFilters")
    func_body = JS[apply_idx:apply_idx + 400]
    assert "cal-weight-val" in func_body, \
        "applyFilters must toggle .cal-weight-val visibility"


def test_ac5_filter_hides_habits_rows():
    """calendar.js applyFilters must hide/show .cal-habits-row based on filter-habits."""
    apply_idx = JS.find("applyFilters")
    func_body = JS[apply_idx:apply_idx + 400]
    assert "cal-habits-row" in func_body, \
        "applyFilters must toggle .cal-habits-row visibility"


def test_ac5_filter_hides_training_rows():
    """calendar.js applyFilters must hide/show .cal-training-row based on filter-training."""
    apply_idx = JS.find("applyFilters")
    func_body = JS[apply_idx:apply_idx + 700]
    assert "cal-training-row" in func_body, \
        "applyFilters must toggle .cal-training-row visibility"


def test_ac5_filter_change_listeners_attached():
    """calendar.js must attach change listeners to all three filter checkboxes."""
    for cb_id in ("filter-weight", "filter-habits", "filter-training"):
        # Search all occurrences of cb_id; at least one must be paired with change/addEventListener
        idx = 0
        found = False
        while True:
            idx = JS.find(cb_id, idx)
            if idx == -1:
                break
            context = JS[idx:idx + 200]
            if "change" in context or "addEventListener" in context:
                found = True
                break
            idx += 1
        assert found, f"calendar.js must attach a change listener to {cb_id}"


# ── AC-6: Data refetches on month navigation ──────────────────────────────────

def test_ac6_navigate_triggers_data_load():
    """calendar.js navigate() must trigger a data reload for the new month."""
    assert "navigate" in JS, "calendar.js must have a navigate function"
    assert "loadData" in JS, "calendar.js must call loadData after navigating"
    nav_idx = JS.find("function navigate")
    if nav_idx == -1:
        nav_idx = JS.find("navigate(")
    context = JS[nav_idx:nav_idx + 400]
    assert "loadData" in context or "withFade" in context, \
        "navigate() must trigger data reload (directly or via withFade)"


def test_ac6_stale_data_cleared_on_navigate():
    """calendar.js must clear stale data before fetching new month's data."""
    assert "emptyData" in JS or "calData = {" in JS or "calData = emptyData" in JS, \
        "calendar.js must clear calData before navigating to a new month"


def test_ac6_month_range_passed_to_fetch():
    """calendar.js must compute and pass month date range to the fetch calls."""
    assert "monthRange" in JS or ("from" in JS and "to" in JS), \
        "calendar.js must compute from/to date range for the current month"


# ── AC-7: Data refetches when user switches ───────────────────────────────────

def test_ac7_user_changed_event_listener():
    """calendar.js must listen for userChanged event to refresh data for the new user."""
    assert "userChanged" in JS, "calendar.js must listen for 'userChanged' event"


def test_ac7_user_changed_reloads_data():
    """calendar.js userChanged handler must clear stale data and trigger loadData."""
    user_changed_idx = JS.find("userChanged")
    context = JS[user_changed_idx:user_changed_idx + 300]
    assert "loadData" in context or "fetchCalendarData" in context, \
        "userChanged handler must trigger a data reload"


def test_ac7_user_changed_clears_stale_data():
    """calendar.js userChanged handler must clear previous user's data before reloading."""
    user_changed_idx = JS.find("userChanged")
    context = JS[user_changed_idx:user_changed_idx + 300]
    assert "emptyData" in context or "calData = emptyData()" in context or \
           "calData =" in context, \
        "userChanged handler must reset calData to avoid showing stale data"


def test_ac7_user_ready_event_triggers_initial_load():
    """calendar.js must listen for userReady event to start the initial data load."""
    assert "userReady" in JS, \
        "calendar.js must listen for 'userReady' to load initial calendar data"


# ── AC-8: Legend below the grid ───────────────────────────────────────────────

def test_ac8_legend_present_in_html():
    """calendar.html must have a legend element below the calendar grid."""
    assert "cal-legend" in HTML, "Missing .cal-legend element in calendar.html"


def test_ac8_legend_after_grid():
    """Legend must appear after the calendar grid in the DOM."""
    grid_pos = HTML.find("cal-grid-cells")
    legend_pos = HTML.find("cal-legend")
    assert grid_pos != -1 and legend_pos != -1
    assert legend_pos > grid_pos, \
        "Legend must appear after the calendar grid in calendar.html"


def _legend_html_block():
    """Return the HTML content of the <div class="cal-legend"> element."""
    # Use the aria-label to find the actual HTML element (not the CSS definition)
    aria_idx = HTML.find('aria-label="Calendar legend"')
    if aria_idx != -1:
        return HTML[aria_idx:aria_idx + 1200]
    # Fallback: find last occurrence of cal-legend (HTML element comes after CSS)
    idx = HTML.rfind("cal-legend")
    return HTML[idx:idx + 1200] if idx != -1 else ""


def test_ac8_legend_explains_habit_dots():
    """Legend must explain what the colored habit dots mean."""
    block = _legend_html_block()
    has_done = "done" in block.lower() or "Habit done" in block
    has_missed = "missed" in block.lower() or "Habit missed" in block
    assert has_done and has_missed, \
        "Legend must explain done (green) and missed (grey) habit dot meanings"


def test_ac8_legend_explains_training_icons():
    """Legend must explain what the training icons represent."""
    block = _legend_html_block()
    has_cardio = "cardio" in block.lower() or "ti-run" in block
    has_strength = "strength" in block.lower() or "ti-barbell" in block
    assert has_cardio or has_strength, \
        "Legend must explain training icon types (cardio/strength)"


def test_ac8_legend_explains_today_highlight():
    """Legend must explain the today cell highlight."""
    block = _legend_html_block()
    assert "today" in block.lower() or "Today" in block, \
        "Legend must include a 'Today' indicator explanation"


# ── AC-9: Loading state ────────────────────────────────────────────────────────

def test_ac9_loading_clears_stale_data_first():
    """calendar.js must clear previous month's data before rendering during load."""
    assert "emptyData" in JS, "calendar.js must have emptyData() to clear stale data"
    assert "calData = emptyData()" in JS, \
        "calendar.js must reset calData to emptyData() to prevent stale data showing"


def test_ac9_cells_empty_during_load():
    """calendar.js must render cells empty while data is being fetched (no stale data)."""
    assert "render()" in JS, "calendar.js must call render() before data arrives"
    with_fade_idx = JS.find("withFade")
    if with_fade_idx != -1:
        fade_body = JS[with_fade_idx:with_fade_idx + 400]
        assert "render()" in fade_body and "loadData()" in fade_body, \
            "withFade must render empty cells then fetch data asynchronously"


def test_ac9_fade_transition_exists():
    """calendar.html CSS must define a fade/opacity transition for the loading state."""
    assert "transition" in HTML and "opacity" in HTML, \
        "calendar.html must use opacity transition for the loading state"
    assert "fading" in HTML or "fading" in JS, \
        "calendar.js must toggle a CSS class to trigger the fade animation"


def test_ac9_load_seq_prevents_race_condition():
    """calendar.js must guard against race conditions when fetching (loadSeq pattern)."""
    assert "loadSeq" in JS or "seq" in JS, \
        "calendar.js must use a sequence counter to discard stale fetch results"


# ── Structural ────────────────────────────────────────────────────────────────

def test_structural_calendar_html_served(client):
    """GET /calendar.html must return 200."""
    res = client.get("/calendar.html")
    assert res.status_code == 200, f"Expected 200, got {res.status_code}"
    assert "text/html" in res.headers.get("content-type", ""), \
        "Response must be text/html"


def test_structural_calendar_js_exists():
    """js/calendar.js must exist in the project."""
    assert (pathlib.Path(__file__).parent.parent / "js" / "calendar.js").exists()


def test_structural_calendar_js_loaded_in_html():
    """calendar.html must load js/calendar.js via a script tag."""
    assert "calendar.js" in HTML, "calendar.html must include js/calendar.js"


def test_structural_fetch_calls_inside_iife():
    """calendar.js must be wrapped in an IIFE (no global scope pollution)."""
    assert "(function" in JS or "(() =>" in JS, \
        "calendar.js must be wrapped in an IIFE"


# ── API contract ──────────────────────────────────────────────────────────────

def test_api_weight_entry_has_required_fields(client, alice_id):
    """Weight API response must include recorded_date and weight_kg fields."""
    res = client.get(f"/api/weight?user_id={alice_id}")
    assert res.status_code == 200
    entries = res.json()
    if entries:
        entry = entries[0]
        assert "recorded_date" in entry, "Weight entry must have recorded_date"
        assert "weight_kg" in entry, "Weight entry must have weight_kg"


def test_api_habit_log_has_required_fields(client, alice_id):
    """Habit log API response must include habit_id and logged_date fields."""
    res = client.get(
        f"/api/habits/logs?user_id={alice_id}&from=2026-05-01&to=2026-05-31"
    )
    assert res.status_code == 200
    logs = res.json()
    if logs:
        log = logs[0]
        assert "habit_id" in log, "Habit log must have habit_id"
        assert "logged_date" in log, "Habit log must have logged_date"


def test_api_workout_has_required_fields(client, alice_id):
    """Workouts API response must include workout_date and workout_type fields."""
    res = client.get(
        f"/api/workouts?user_id={alice_id}&from=2026-05-01&to=2026-05-31"
    )
    assert res.status_code == 200
    workouts = res.json()
    if workouts:
        w = workouts[0]
        assert "workout_date" in w, "Workout must have workout_date"
        assert "workout_type" in w, "Workout must have workout_type"
        assert "exercise_count" in w, "Workout must have exercise_count"
