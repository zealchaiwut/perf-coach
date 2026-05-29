"""
UAT tests for issue #146: Habits stats graph card (row 4, right).
Server under test: http://127.0.0.1:9001
"""
import datetime
import pathlib

import httpx
import pytest

BASE = "http://127.0.0.1:9001"
TODAY = datetime.date.today()
TODAY_STR = TODAY.isoformat()

_weekday = TODAY.weekday()  # 0 = Monday
MONDAY = TODAY - datetime.timedelta(days=_weekday)
SUNDAY = MONDAY + datetime.timedelta(days=6)
MONDAY_STR = MONDAY.isoformat()
SUNDAY_STR = SUNDAY.isoformat()


# ── Fixtures ──────────────────────────────────────────────────────────────────

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
def habit_id(client, user_id):
    res = client.post("/api/habits", json={"user_id": user_id, "name": "Test Habit #146"})
    assert res.status_code == 201, f"POST /api/habits failed: {res.status_code} {res.text}"
    hid = res.json()["id"]
    yield hid
    client.delete(f"/api/habits/{hid}")


# ── Static HTML: structure ────────────────────────────────────────────────────

def test_home_html_has_row4():
    html = (pathlib.Path(__file__).parent.parent / "home.html").read_text()
    assert 'id="row-4"' in html

def test_home_html_row4_is_two_col_desktop():
    html = (pathlib.Path(__file__).parent.parent / "home.html").read_text()
    assert "#row-4" in html and "2fr" in html, \
        "#row-4 must use a 2fr grid column for the desktop layout"

def test_home_html_habits_graph_css():
    html = (pathlib.Path(__file__).parent.parent / "home.html").read_text()
    assert ".habits-graph" in html, "home.html must define .habits-graph CSS"

def test_home_html_hg_body_css():
    html = (pathlib.Path(__file__).parent.parent / "home.html").read_text()
    assert ".hg-body" in html, "home.html must define .hg-body for the two-column layout"

def test_home_html_hg_chart_css():
    html = (pathlib.Path(__file__).parent.parent / "home.html").read_text()
    assert ".hg-chart" in html, "home.html must define .hg-chart for the bar chart grid"

def test_home_html_hg_day_css():
    html = (pathlib.Path(__file__).parent.parent / "home.html").read_text()
    assert ".hg-day" in html, "home.html must define .hg-day"

def test_home_html_hg_day_today_css():
    html = (pathlib.Path(__file__).parent.parent / "home.html").read_text()
    assert ".hg-day.today" in html, "home.html must style .hg-day.today with a darker bar"

def test_home_html_hg_day_future_css():
    html = (pathlib.Path(__file__).parent.parent / "home.html").read_text()
    assert ".hg-day.future" in html, "home.html must style .hg-day.future with a gray bar"

def test_home_html_hg_stats_css():
    html = (pathlib.Path(__file__).parent.parent / "home.html").read_text()
    assert ".hg-stats" in html, "home.html must define .hg-stats"

def test_home_html_hg_stat_css():
    html = (pathlib.Path(__file__).parent.parent / "home.html").read_text()
    assert ".hg-stat" in html, "home.html must define .hg-stat"

def test_home_html_pct_bar_css():
    html = (pathlib.Path(__file__).parent.parent / "home.html").read_text()
    assert "pct-bar" in html, "home.html must define .pct-bar for the fill progress bar"

def test_home_html_mobile_hg_body_stacked():
    html = (pathlib.Path(__file__).parent.parent / "home.html").read_text()
    assert "flex-direction: column" in html or "flex-direction:column" in html, \
        "mobile layout must stack hg-body as a column"

def test_home_html_mobile_hg_stats_grid():
    html = (pathlib.Path(__file__).parent.parent / "home.html").read_text()
    assert "1fr 1fr" in html, "mobile hg-stats must be a 2-column grid"


# ── Static JS: logic ──────────────────────────────────────────────────────────

def test_home_js_defines_load_habits_stats_card():
    js = (pathlib.Path(__file__).parent.parent / "js" / "home.js").read_text()
    assert "loadHabitsStatsCard" in js

def test_home_js_calls_load_habits_stats_card():
    js = (pathlib.Path(__file__).parent.parent / "js" / "home.js").read_text()
    assert js.count("loadHabitsStatsCard") >= 2, \
        "loadHabitsStatsCard must be defined AND called from init()"

def test_home_js_fetches_habits_stats_without_habit_id():
    js = (pathlib.Path(__file__).parent.parent / "js" / "home.js").read_text()
    assert "/api/habits/stats?user_id=" in js or "habits/stats" in js
    assert "days=30" in js

def test_home_js_fetches_habits_logs_for_week():
    js = (pathlib.Path(__file__).parent.parent / "js" / "home.js").read_text()
    assert "/api/habits/logs" in js

def test_home_js_computes_habits_completed_by_day():
    js = (pathlib.Path(__file__).parent.parent / "js" / "home.js").read_text()
    assert "habitsCompletedByDay" in js

def test_home_js_computes_total_possible():
    js = (pathlib.Path(__file__).parent.parent / "js" / "home.js").read_text()
    assert "totalPossible" in js

def test_home_js_computes_completion_rate():
    js = (pathlib.Path(__file__).parent.parent / "js" / "home.js").read_text()
    assert "completionRate" in js

def test_home_js_computes_best_day():
    js = (pathlib.Path(__file__).parent.parent / "js" / "home.js").read_text()
    assert "bestDay" in js or "bestDayNames" in js

def test_home_js_computes_longest_streak():
    js = (pathlib.Path(__file__).parent.parent / "js" / "home.js").read_text()
    assert "longestStreak" in js or "longestStreakNum" in js

def test_home_js_zero_habits_hides_card():
    js = (pathlib.Path(__file__).parent.parent / "js" / "home.js").read_text()
    assert "activeCount === 0" in js or "activeCount == 0" in js, \
        "Zero-habits edge case must hide the card"

def test_home_js_future_bar_label_dash():
    js = (pathlib.Path(__file__).parent.parent / "js" / "home.js").read_text()
    assert "'—'" in js or '"—"' in js, "Future day bar label must show '—'"

def test_home_js_today_bar_class():
    js = (pathlib.Path(__file__).parent.parent / "js" / "home.js").read_text()
    assert "hg-day" in js and "today" in js

def test_home_js_future_bar_class():
    js = (pathlib.Path(__file__).parent.parent / "js" / "home.js").read_text()
    assert "hg-day" in js and "future" in js

def test_home_js_streak_from_list_response():
    js = (pathlib.Path(__file__).parent.parent / "js" / "home.js").read_text()
    assert "habit_name" in js, "longestStreak must read habit_name from stats list response"

def test_home_js_streak_text_format():
    js = (pathlib.Path(__file__).parent.parent / "js" / "home.js").read_text()
    assert "days ·" in js or "days·" in js, \
        "Longest streak must be formatted as 'X days · [Habit Name]'"


# ── API: GET /api/habits/stats (list mode — no habit_id) ─────────────────────

def test_api_habits_stats_list_returns_array(client, user_id, habit_id):
    res = client.get(f"/api/habits/stats?user_id={user_id}&days=30")
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
    data = res.json()
    assert isinstance(data, list), "Without habit_id the endpoint must return a JSON array"

def test_api_habits_stats_list_includes_test_habit(client, user_id, habit_id):
    res = client.get(f"/api/habits/stats?user_id={user_id}&days=30")
    assert res.status_code == 200
    ids = [item["habit_id"] for item in res.json()]
    assert habit_id in ids, "Stats list must include the test habit"

def test_api_habits_stats_list_item_fields(client, user_id, habit_id):
    res = client.get(f"/api/habits/stats?user_id={user_id}&days=30")
    assert res.status_code == 200
    item = next((i for i in res.json() if i["habit_id"] == habit_id), None)
    assert item is not None
    assert "habit_id" in item
    assert "habit_name" in item
    assert "streak" in item
    assert "completion_rate" in item
    assert "days_completed" in item
    assert "days_total" in item

def test_api_habits_stats_list_days_total(client, user_id, habit_id):
    res = client.get(f"/api/habits/stats?user_id={user_id}&days=30")
    assert res.status_code == 200
    item = next((i for i in res.json() if i["habit_id"] == habit_id), None)
    assert item["days_total"] == 30

def test_api_habits_stats_list_zero_streak_no_logs(client, user_id):
    new_res = client.post("/api/habits", json={"user_id": user_id, "name": "Zero streak #146"})
    assert new_res.status_code == 201
    hid = new_res.json()["id"]
    try:
        res = client.get(f"/api/habits/stats?user_id={user_id}&days=30")
        assert res.status_code == 200
        item = next((i for i in res.json() if i["habit_id"] == hid), None)
        assert item is not None
        assert item["streak"] == 0
        assert item["days_completed"] == 0
    finally:
        client.delete(f"/api/habits/{hid}")

def test_api_habits_stats_list_streak_increments_with_log(client, user_id, habit_id):
    log_res = client.post("/api/habits/logs", json={
        "habit_id": habit_id, "user_id": user_id, "logged_date": TODAY_STR,
    })
    log_id = log_res.json().get("id") if log_res.status_code == 201 else None
    try:
        res = client.get(f"/api/habits/stats?user_id={user_id}&days=30")
        assert res.status_code == 200
        item = next((i for i in res.json() if i["habit_id"] == habit_id), None)
        assert item is not None
        assert item["streak"] >= 1
    finally:
        if log_id:
            client.delete(f"/api/habits/logs/{log_id}")

def test_api_habits_stats_list_excludes_archived(client, user_id):
    arch_res = client.post("/api/habits", json={"user_id": user_id, "name": "Archived #146"})
    assert arch_res.status_code == 201
    hid = arch_res.json()["id"]
    client.delete(f"/api/habits/{hid}")
    res = client.get(f"/api/habits/stats?user_id={user_id}&days=30")
    assert res.status_code == 200
    ids = [item["habit_id"] for item in res.json()]
    assert hid not in ids, "Archived habits must not appear in the stats list"

def test_api_habits_stats_list_invalid_user_id(client):
    res = client.get("/api/habits/stats?user_id=not-a-uuid&days=30")
    assert res.status_code == 400

def test_api_habits_stats_single_still_works(client, user_id, habit_id):
    """Backward-compat: single-habit mode (habit_id provided) still returns an object."""
    res = client.get(f"/api/habits/stats?user_id={user_id}&habit_id={habit_id}&days=30")
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, dict), "Single-habit mode must still return a JSON object"
    assert "streak" in data
    assert "days_total" in data
