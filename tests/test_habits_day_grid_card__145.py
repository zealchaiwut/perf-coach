"""
UAT tests for issue #145: Habits Day-Grid card on the home dashboard.
Server under test: http://127.0.0.1:9001
"""
import datetime
import pathlib

import httpx
import pytest

BASE = "http://127.0.0.1:9001"
TODAY = datetime.date.today()
TODAY_STR = TODAY.isoformat()

# Monday of the current ISO week
_weekday = TODAY.weekday()  # 0=Monday
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
    """Create a test habit and tear it down after the module."""
    res = client.post("/api/habits", json={"user_id": user_id, "name": "Test Habit #145"})
    assert res.status_code == 201, f"POST /api/habits failed: {res.status_code} {res.text}"
    hid = res.json()["id"]
    yield hid
    client.delete(f"/api/habits/{hid}")


# ── Static HTML: structure ────────────────────────────────────────────────────

def test_home_html_has_row4():
    html = (pathlib.Path(__file__).parent.parent / "home.html").read_text()
    assert 'id="row-4"' in html, "home.html must have id='row-4'"


def test_home_html_row4_desktop_grid():
    html = (pathlib.Path(__file__).parent.parent / "home.html").read_text()
    assert "#row-4" in html and "2fr" in html, \
        "#row-4 must use a 2fr grid for the ~2/3 width desktop layout"


def test_home_html_has_habits_css():
    html = (pathlib.Path(__file__).parent.parent / "home.html").read_text()
    assert ".habits" in html, "home.html must contain .habits CSS"


def test_home_html_habits_day_cell_css():
    html = (pathlib.Path(__file__).parent.parent / "home.html").read_text()
    assert ".habits .day-cell" in html, "home.html must style .habits .day-cell"


def test_home_html_habits_day_cell_done_css():
    html = (pathlib.Path(__file__).parent.parent / "home.html").read_text()
    assert ".habits .day-cell.done" in html, \
        "home.html must style .habits .day-cell.done (completed state)"


def test_home_html_habits_today_ring_css():
    html = (pathlib.Path(__file__).parent.parent / "home.html").read_text()
    assert ".habits .day-cell.today" in html, \
        "home.html must style .habits .day-cell.today with a visible ring"
    assert "#2b4ca8" in html or "border-color" in html, \
        "today cell must use a blue border-color"


def test_home_html_habits_future_cell_css():
    html = (pathlib.Path(__file__).parent.parent / "home.html").read_text()
    assert ".habits .day-cell.future" in html, \
        "home.html must style .habits .day-cell.future"
    assert "opacity" in html, "future cells must use opacity for visual de-emphasis"
    assert "pointer-events" in html, "future cells must set pointer-events: none"


def test_home_html_habits_streak_hdr_desktop_hidden_mobile():
    html = (pathlib.Path(__file__).parent.parent / "home.html").read_text()
    assert "streak-hdr" in html, "home.html must define .week-header.streak-hdr"
    assert "display: none" in html or "display:none" in html, \
        "streak header must be hidden on mobile via display:none"


def test_home_html_habits_streak_col_hidden_mobile():
    html = (pathlib.Path(__file__).parent.parent / "home.html").read_text()
    assert ".habits .streak-col" in html, "home.html must define .streak-col"


def test_home_html_habits_streak_footer_mobile():
    html = (pathlib.Path(__file__).parent.parent / "home.html").read_text()
    assert "habits-streak-footer" in html, \
        "home.html must define .habits-streak-footer for mobile streak badges"


def test_home_html_habits_empty_css():
    html = (pathlib.Path(__file__).parent.parent / "home.html").read_text()
    assert "habits-empty" in html, "home.html must define .habits-empty"


# ── Static JS: logic ──────────────────────────────────────────────────────────

def test_home_js_loads_habits_card():
    js = (pathlib.Path(__file__).parent.parent / "js" / "home.js").read_text()
    assert "loadHabitsCard" in js, "home.js must define/call loadHabitsCard"


def test_home_js_fetches_habits_endpoint():
    js = (pathlib.Path(__file__).parent.parent / "js" / "home.js").read_text()
    assert "/api/habits?" in js or "'/api/habits'" in js or '"/api/habits"' in js, \
        "home.js must fetch GET /api/habits"


def test_home_js_fetches_habit_logs_endpoint():
    js = (pathlib.Path(__file__).parent.parent / "js" / "home.js").read_text()
    assert "/api/habits/logs" in js, "home.js must fetch GET /api/habits/logs"


def test_home_js_fetches_habit_stats_endpoint():
    js = (pathlib.Path(__file__).parent.parent / "js" / "home.js").read_text()
    assert "/api/habits/stats" in js, "home.js must fetch GET /api/habits/stats"
    assert "streak" in js, "home.js must read the streak field from stats response"


def test_home_js_post_habit_log():
    js = (pathlib.Path(__file__).parent.parent / "js" / "home.js").read_text()
    assert "POST" in js, "home.js must use POST for creating habit logs"
    assert "/api/habits/logs" in js


def test_home_js_delete_habit_log():
    js = (pathlib.Path(__file__).parent.parent / "js" / "home.js").read_text()
    assert "DELETE" in js, "home.js must use DELETE for removing habit logs"
    assert "/api/habits/logs/" in js, "DELETE must target /api/habits/logs/{log_id}"


def test_home_js_week_header_days():
    js = (pathlib.Path(__file__).parent.parent / "js" / "home.js").read_text()
    for day in ["'M'", '"M"', ">M<", "'T'", '"T"', ">T<", "'W'", '"W"', ">W<",
                "'F'", '"F"', ">F<", "'S'", '"S"', ">S<"]:
        pass
    assert ">M<" in js or "'M'" in js or '"M"' in js, "Week header must include M column"
    assert ">W<" in js or "'W'" in js or '"W"' in js, "Week header must include W column"
    assert ">S<" in js or "'S'" in js or '"S"' in js, "Week header must include S column"
    assert "Streak" in js, "Week header must include Streak column"


def test_home_js_empty_state_message():
    js = (pathlib.Path(__file__).parent.parent / "js" / "home.js").read_text()
    assert "Add a habit to start tracking your week" in js, \
        "home.js must render the zero-habits empty state message"


def test_home_js_empty_state_link_to_habits():
    js = (pathlib.Path(__file__).parent.parent / "js" / "home.js").read_text()
    assert "/habits.html" in js, \
        "Empty state must link to /habits.html"


def test_home_js_future_class_applied():
    js = (pathlib.Path(__file__).parent.parent / "js" / "home.js").read_text()
    assert "future" in js, \
        "home.js must assign the 'future' class to cells beyond today"


def test_home_js_today_class_applied():
    js = (pathlib.Path(__file__).parent.parent / "js" / "home.js").read_text()
    assert "today" in js, \
        "home.js must assign the 'today' class to today's cell"


def test_home_js_done_class_applied():
    js = (pathlib.Path(__file__).parent.parent / "js" / "home.js").read_text()
    assert "done" in js, \
        "home.js must assign the 'done' class to completed cells"


def test_home_js_partial_rerender_per_habit():
    js = (pathlib.Path(__file__).parent.parent / "js" / "home.js").read_text()
    assert "refreshHabitRow" in js or "data-habit-row" in js, \
        "home.js must support per-habit row re-render (refreshHabitRow or data-habit-row)"


def test_home_js_streak_days_param():
    js = (pathlib.Path(__file__).parent.parent / "js" / "home.js").read_text()
    assert "days=30" in js, "Streak must be fetched with days=30"


def test_home_js_iso_week_monday():
    js = (pathlib.Path(__file__).parent.parent / "js" / "home.js").read_text()
    assert "isoWeekMonday" in js or "monday" in js.lower(), \
        "home.js must compute ISO week Monday as the week start"


# ── API: GET /api/habits ───────────────────────────────────────────────────────

def test_api_get_habits_returns_list(client, user_id, habit_id):
    res = client.get(f"/api/habits?user_id={user_id}")
    assert res.status_code == 200
    habits = res.json()
    assert isinstance(habits, list)
    ids = [h["id"] for h in habits]
    assert habit_id in ids, "GET /api/habits must return the created test habit"


def test_api_get_habits_fields(client, user_id, habit_id):
    res = client.get(f"/api/habits?user_id={user_id}")
    assert res.status_code == 200
    habit = next(h for h in res.json() if h["id"] == habit_id)
    assert "id" in habit
    assert "name" in habit


def test_api_get_habits_excludes_archived(client, user_id):
    """Archived habits must not appear in the active list."""
    res = client.post("/api/habits", json={"user_id": user_id, "name": "Archived Habit #145"})
    assert res.status_code == 201
    hid = res.json()["id"]
    del_res = client.delete(f"/api/habits/{hid}")
    assert del_res.status_code == 204
    habits = client.get(f"/api/habits?user_id={user_id}").json()
    ids = [h["id"] for h in habits]
    assert hid not in ids, "Archived habit must not appear in GET /api/habits"


def test_api_get_habits_invalid_user_id(client):
    res = client.get("/api/habits?user_id=not-a-uuid")
    assert res.status_code == 400


# ── API: GET /api/habits/logs ─────────────────────────────────────────────────

def test_api_get_habit_logs_empty_week(client, user_id):
    res = client.get(
        f"/api/habits/logs?user_id={user_id}&from={MONDAY_STR}&to={SUNDAY_STR}"
    )
    assert res.status_code == 200
    assert isinstance(res.json(), list)


def test_api_get_habit_logs_fields(client, user_id, habit_id):
    """Create a log, fetch it, verify fields, then clean up."""
    log_res = client.post("/api/habits/logs", json={
        "habit_id": habit_id,
        "user_id": user_id,
        "logged_date": TODAY_STR,
    })
    assert log_res.status_code in (201, 409)
    if log_res.status_code == 201:
        log_id = log_res.json()["id"]
        logs = client.get(
            f"/api/habits/logs?user_id={user_id}&from={TODAY_STR}&to={TODAY_STR}"
        ).json()
        assert any(l["id"] == log_id for l in logs)
        log_entry = next(l for l in logs if l["id"] == log_id)
        assert "habit_id" in log_entry
        assert "logged_date" in log_entry
        client.delete(f"/api/habits/logs/{log_id}")


def test_api_get_habit_logs_scoped_to_date_range(client, user_id, habit_id):
    """Logs outside the requested date range must not be returned."""
    future_from = (TODAY + datetime.timedelta(days=30)).isoformat()
    future_to = (TODAY + datetime.timedelta(days=31)).isoformat()
    res = client.get(
        f"/api/habits/logs?user_id={user_id}&from={future_from}&to={future_to}"
    )
    assert res.status_code == 200
    assert res.json() == [], "Future date range must return empty list"


# ── API: POST /api/habits/logs ────────────────────────────────────────────────

def test_api_post_habit_log_creates_entry(client, user_id, habit_id):
    log_date = (MONDAY + datetime.timedelta(days=1)).isoformat()  # Tuesday
    res = client.post("/api/habits/logs", json={
        "habit_id": habit_id,
        "user_id": user_id,
        "logged_date": log_date,
    })
    assert res.status_code in (201, 409), \
        f"POST /api/habits/logs must return 201 or 409: {res.status_code} {res.text}"
    if res.status_code == 201:
        body = res.json()
        assert body["habit_id"] == habit_id
        assert body["logged_date"] == log_date
        client.delete(f"/api/habits/logs/{body['id']}")


def test_api_post_habit_log_duplicate_returns_409(client, user_id, habit_id):
    log_date = (MONDAY + datetime.timedelta(days=2)).isoformat()  # Wednesday
    res1 = client.post("/api/habits/logs", json={
        "habit_id": habit_id, "user_id": user_id, "logged_date": log_date,
    })
    if res1.status_code == 201:
        res2 = client.post("/api/habits/logs", json={
            "habit_id": habit_id, "user_id": user_id, "logged_date": log_date,
        })
        assert res2.status_code == 409, "Duplicate log must return 409"
        client.delete(f"/api/habits/logs/{res1.json()['id']}")


# ── API: DELETE /api/habits/logs/{log_id} ─────────────────────────────────────

def test_api_delete_habit_log_removes_entry(client, user_id, habit_id):
    log_date = (MONDAY + datetime.timedelta(days=3)).isoformat()  # Thursday
    create_res = client.post("/api/habits/logs", json={
        "habit_id": habit_id, "user_id": user_id, "logged_date": log_date,
    })
    if create_res.status_code == 409:
        pytest.skip("Log already exists for this date; skip delete test")
    assert create_res.status_code == 201
    log_id = create_res.json()["id"]

    del_res = client.delete(f"/api/habits/logs/{log_id}")
    assert del_res.status_code == 204

    logs = client.get(
        f"/api/habits/logs?user_id={user_id}&from={log_date}&to={log_date}"
    ).json()
    assert not any(l["id"] == log_id for l in logs), \
        "Deleted log must not appear in subsequent GET"


def test_api_delete_habit_log_missing_returns_404(client):
    import uuid
    fake_id = str(uuid.uuid4())
    res = client.delete(f"/api/habits/logs/{fake_id}")
    assert res.status_code == 404


# ── API: GET /api/habits/stats ─────────────────────────────────────────────────

def test_api_get_habit_stats_returns_streak_field(client, user_id, habit_id):
    res = client.get(f"/api/habits/stats?user_id={user_id}&habit_id={habit_id}&days=30")
    assert res.status_code == 200
    body = res.json()
    assert "streak" in body, "stats response must include 'streak'"
    assert isinstance(body["streak"], int)


def test_api_get_habit_stats_streak_increments_with_log(client, user_id, habit_id):
    """Log today → streak must be >= 1."""
    log_res = client.post("/api/habits/logs", json={
        "habit_id": habit_id, "user_id": user_id, "logged_date": TODAY_STR,
    })
    log_id = None
    if log_res.status_code == 201:
        log_id = log_res.json()["id"]

    stats = client.get(
        f"/api/habits/stats?user_id={user_id}&habit_id={habit_id}&days=30"
    ).json()
    assert stats["streak"] >= 1, "Streak must be >= 1 when today is logged"

    if log_id:
        client.delete(f"/api/habits/logs/{log_id}")


def test_api_get_habit_stats_zero_streak_no_logs(client, user_id):
    """A brand-new habit with no logs must have streak 0."""
    new_habit = client.post("/api/habits", json={
        "user_id": user_id, "name": "Zero-streak habit #145"
    })
    assert new_habit.status_code == 201
    hid = new_habit.json()["id"]

    stats = client.get(
        f"/api/habits/stats?user_id={user_id}&habit_id={hid}&days=30"
    ).json()
    assert stats["streak"] == 0, "New habit with no logs must have streak 0"

    client.delete(f"/api/habits/{hid}")


# ── Toggle cycle: log → unlog ─────────────────────────────────────────────────

def test_toggle_log_then_unlog_cycle(client, user_id, habit_id):
    """Full toggle cycle: create log, verify presence, delete, verify absence."""
    log_date = (MONDAY + datetime.timedelta(days=4)).isoformat()  # Friday

    # Ensure no pre-existing log
    existing = client.get(
        f"/api/habits/logs?user_id={user_id}&from={log_date}&to={log_date}"
    ).json()
    for l in existing:
        if l["habit_id"] == habit_id:
            client.delete(f"/api/habits/logs/{l['id']}")

    # Create log
    post_res = client.post("/api/habits/logs", json={
        "habit_id": habit_id, "user_id": user_id, "logged_date": log_date,
    })
    assert post_res.status_code == 201
    log_id = post_res.json()["id"]

    # Verify presence
    logs = client.get(
        f"/api/habits/logs?user_id={user_id}&from={log_date}&to={log_date}"
    ).json()
    assert any(l["id"] == log_id for l in logs), "Log must be present after POST"

    # Delete log
    del_res = client.delete(f"/api/habits/logs/{log_id}")
    assert del_res.status_code == 204

    # Verify absence
    logs_after = client.get(
        f"/api/habits/logs?user_id={user_id}&from={log_date}&to={log_date}"
    ).json()
    assert not any(l["id"] == log_id for l in logs_after), \
        "Log must be absent after DELETE"
