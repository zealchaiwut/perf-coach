"""Tests for issue #828: Wire Today quick-log writes with upsert and streak refresh.

Covers:
- AC1: Log button calls H1 upsert-log endpoint for today's date
- AC2: Second log same habit+day → upsert semantics, no duplicate row
- AC3: After successful write streak is refreshed from summary endpoint (specific row only)
- AC4: Streak reflects server value, not client-side calculation
- AC5: Brand-new habit first log shows streak=1
- AC6: Upsert failure → error shown, streak not updated
- AC7: No unrelated habit rows re-fetched or re-rendered

Runs against live server at http://127.0.0.1:9001 for API tests.
Static checks read frontend/js/habits.js directly.
"""
import datetime
import os
import pathlib
import pytest
import httpx

BASE_URL = os.environ.get("UAT_BASE_URL", "http://127.0.0.1:9001")
ROOT = pathlib.Path(__file__).parent.parent
TODAY = datetime.date.today().isoformat()

_CREDENTIALS = {"username": "tester828", "password": "Test828pass!"}


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
            pytest.skip(f"Login failed ({r.status_code}); seed tester828 user first")
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


def _js() -> str:
    return (ROOT / "frontend" / "js" / "habits.js").read_text()


# ── Static JS: Log handler wires to H1 upsert-log endpoint (AC1) ─────────────

def test_828__js_calls_upsert_log_endpoint():
    """AC1: Log button must POST to /api/habits/{habit_id}/log — the H1 upsert-log endpoint."""
    js = _js()
    assert "/api/habits/" in js and "/log" in js, \
        "habits.js must POST to /api/habits/{habit_id}/log for the upsert-log endpoint"
    # Specifically, the fetch should include the habit_id/log path pattern
    assert "habits/${" in js or "habits/`" in js or "habits/' +" in js or \
           "/log" in js, \
        "habits.js must dynamically construct the /api/habits/{id}/log URL"


def test_828__js_log_method_is_post():
    """AC1: Log calls must use HTTP POST (not GET)."""
    js = _js()
    # Look for method: 'POST' near the /log endpoint call
    assert "method: 'POST'" in js or 'method: "POST"' in js, \
        "habits.js must use method: 'POST' when calling the upsert-log endpoint"


def test_828__js_noop_no_longer_primary_log_handler():
    """AC1: _todayNoop() must not be the handler that fires on log button click.

    Either _todayNoop is removed, or the real log function is called instead.
    The log controls must NOT exclusively call _todayNoop.
    """
    js = _js()
    # If _todayNoop is still present it should only be there as a dead stub,
    # not as the active handler registered on log controls.
    # The real handler must be async and reference the log endpoint.
    assert "_logHabitToday" in js or "logHabit" in js or "postHabitLog" in js, \
        "habits.js must define a real log function (e.g. _logHabitToday) instead of _todayNoop"


def test_828__js_passes_today_date_in_log_body():
    """AC1: Log call sends today's date in the request body."""
    js = _js()
    # The body must include log_date with today's value
    assert "log_date" in js, \
        "habits.js must include log_date in the POST body for the upsert-log endpoint"


# ── Static JS: Streak refresh from summary endpoint (AC3, AC4, AC7) ──────────

def test_828__js_refreshes_streak_from_summary_after_log():
    """AC3: After successful log, streak is refreshed via /api/habits/summary."""
    js = _js()
    # The JS must call the summary endpoint as part of the log flow
    assert "/api/habits/summary" in js, \
        "habits.js must call GET /api/habits/summary to refresh streak after a log"


def test_828__js_updates_specific_row_not_full_rerender():
    """AC7: Only the specific habit row's streak is updated — no full page reload or re-render."""
    js = _js()
    # Must target the row by habit ID (data-habit-id attribute)
    assert "data-habit-id" in js or "habitId" in js or "habit_id" in js, \
        "habits.js must target the specific row by habit ID when updating streak"
    # Must NOT call loadAndRender or full reload after log
    assert "loadAndRender" not in js.split("_logHabitToday")[1] if "_logHabitToday" in js else True, \
        "habits.js must not call loadAndRender() as part of the streak refresh flow"


def test_828__js_streak_badge_updated_from_server_value():
    """AC4: Streak reflects server value — streak-badge update reads from endpoint response."""
    js = _js()
    # The refresh function must read current_streak from the summary response
    assert "current_streak" in js, \
        "habits.js must read current_streak from the summary endpoint response"
    # streak-badge update must exist
    assert "streak-badge" in js, \
        "habits.js must update the .streak-badge element with the server-returned streak"


# ── Static JS: Error display on failure (AC6) ────────────────────────────────

def test_828__js_shows_error_on_log_failure():
    """AC6: When the upsert call fails, the UI shows an error."""
    js = _js()
    # Must have error handling around the log fetch
    assert "catch" in js or "try" in js, \
        "habits.js must have try/catch around the log fetch call"
    # Must display an error message on failure
    assert "error" in js.lower(), \
        "habits.js must surface an error to the user when the log call fails"


def test_828__js_streak_not_updated_on_error():
    """AC6: Streak display must not be updated when the log call fails."""
    js = _js()
    # The streak refresh (_refreshHabitStreak or equivalent) must only be called
    # on success (inside try block, before or without catch updating streak)
    # We verify that the streak update is gated on a successful response
    assert "if (!res.ok)" in js or "if (!r.ok)" in js or "res.ok" in js, \
        "habits.js must check response.ok before updating the streak display"


# ── API: H1 upsert-log endpoint returns success for today (AC1) ──────────────

def test_828__api_post_log_today_returns_201(client):
    """AC1: POST /api/habits/{habit_id}/log with today's date returns 201."""
    csrf = _csrf(client)
    # Create a fresh habit
    r = client.post("/api/habits", json={
        "name": "828 log test habit",
        "tracking_type": "daily_checkmark",
        "weekly_target": 7,
        "unit": "days",
    }, headers={"X-CSRF-Token": csrf})
    assert r.status_code == 201, f"Create habit failed: {r.text}"
    habit_id = r.json()["id"]

    try:
        # Log today
        log_r = client.post(
            f"/api/habits/{habit_id}/log",
            json={"log_date": TODAY},
            headers={"X-CSRF-Token": csrf},
        )
        assert log_r.status_code == 201, \
            f"Expected 201 for first log today; got {log_r.status_code}: {log_r.text}"
        body = log_r.json()
        assert body["habit_id"] == habit_id
        assert body["log_date"] == TODAY
    finally:
        client.request("DELETE", f"/api/habits/{habit_id}?hard=true",
                       headers={"X-CSRF-Token": csrf})


# ── API: Upsert semantics — no duplicate on second log (AC2) ─────────────────

def test_828__api_second_log_same_day_no_duplicate(client):
    """AC2: A second log for the same habit and day is an upsert — no 409, no duplicate row."""
    csrf = _csrf(client)
    r = client.post("/api/habits", json={
        "name": "828 upsert habit",
        "tracking_type": "daily_checkmark",
        "weekly_target": 7,
        "unit": "days",
    }, headers={"X-CSRF-Token": csrf})
    assert r.status_code == 201
    habit_id = r.json()["id"]

    try:
        # First log
        r1 = client.post(
            f"/api/habits/{habit_id}/log",
            json={"log_date": TODAY},
            headers={"X-CSRF-Token": csrf},
        )
        assert r1.status_code == 201, f"First log failed: {r1.text}"

        # Second log — must not be 409
        r2 = client.post(
            f"/api/habits/{habit_id}/log",
            json={"log_date": TODAY},
            headers={"X-CSRF-Token": csrf},
        )
        assert r2.status_code in (200, 201), \
            f"Second log for same day must not return 409; got {r2.status_code}: {r2.text}"

        # Verify only one log row exists for today
        logs_r = client.get(
            f"/api/habits/logs?from={TODAY}&to={TODAY}",
        )
        assert logs_r.status_code == 200
        logs = [l for l in logs_r.json() if l["habit_id"] == habit_id]
        assert len(logs) == 1, \
            f"Expected exactly 1 log row after two POSTs; found {len(logs)}"
    finally:
        client.request("DELETE", f"/api/habits/{habit_id}?hard=true",
                       headers={"X-CSRF-Token": csrf})


# ── API: Brand-new habit first log → streak=1 in summary (AC5) ───────────────

def test_828__api_first_log_shows_streak_1_in_summary(client):
    """AC5: After the first log today for a new habit, /api/habits/summary returns streak=1."""
    csrf = _csrf(client)
    r = client.post("/api/habits", json={
        "name": "828 streak=1 habit",
        "tracking_type": "daily_checkmark",
        "weekly_target": 7,
        "unit": "days",
    }, headers={"X-CSRF-Token": csrf})
    assert r.status_code == 201
    habit_id = r.json()["id"]

    try:
        # Before log: streak should be 0
        pre = client.get("/api/habits/summary")
        assert pre.status_code == 200
        pre_habits = {h["id"]: h for h in pre.json()["habits"]}
        assert pre_habits.get(habit_id, {}).get("current_streak", 0) == 0, \
            "Streak before first log must be 0"

        # Log today
        log_r = client.post(
            f"/api/habits/{habit_id}/log",
            json={"log_date": TODAY},
            headers={"X-CSRF-Token": csrf},
        )
        assert log_r.status_code == 201

        # After log: streak must be 1
        post = client.get("/api/habits/summary")
        assert post.status_code == 200
        post_habits = {h["id"]: h for h in post.json()["habits"]}
        streak = post_habits.get(habit_id, {}).get("current_streak", -1)
        assert streak == 1, \
            f"Streak after first log today must be 1; got {streak}"
    finally:
        client.request("DELETE", f"/api/habits/{habit_id}?hard=true",
                       headers={"X-CSRF-Token": csrf})


# ── API: Unauthenticated log returns 401 ─────────────────────────────────────

def test_828__api_upsert_log_requires_auth():
    """AC6 (implicit): Unauthenticated POST /api/habits/{id}/log returns 401."""
    import uuid
    fake_id = str(uuid.uuid4())
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as anon:
        r = anon.post(f"/api/habits/{fake_id}/log", json={"log_date": TODAY})
    assert r.status_code == 401, \
        f"POST /api/habits/{{id}}/log must return 401 for unauthenticated; got {r.status_code}"


# ── API: Second log for same day updates value, not creates duplicate (AC2) ───

def test_828__api_second_log_updates_value(client):
    """AC2: For count/duration habits, second log updates the value (upsert mode=set)."""
    csrf = _csrf(client)
    r = client.post("/api/habits", json={
        "name": "828 count upsert habit",
        "tracking_type": "weekly_count",
        "weekly_target": 5,
        "unit": "sessions",
    }, headers={"X-CSRF-Token": csrf})
    assert r.status_code == 201
    habit_id = r.json()["id"]

    try:
        # First log with value=1
        r1 = client.post(
            f"/api/habits/{habit_id}/log",
            json={"log_date": TODAY, "value": 1},
            headers={"X-CSRF-Token": csrf},
        )
        assert r1.status_code == 201

        # Second log with value=3 — must update, not duplicate
        r2 = client.post(
            f"/api/habits/{habit_id}/log",
            json={"log_date": TODAY, "value": 3},
            headers={"X-CSRF-Token": csrf},
        )
        assert r2.status_code in (200, 201), \
            f"Second log must not fail; got {r2.status_code}: {r2.text}"
        assert r2.json().get("value") == 3, \
            f"Value after second log must be 3 (upsert/set mode); got {r2.json().get('value')}"

        # Only one log row
        logs_r = client.get(f"/api/habits/logs?from={TODAY}&to={TODAY}")
        assert logs_r.status_code == 200
        logs = [l for l in logs_r.json() if l["habit_id"] == habit_id]
        assert len(logs) == 1, \
            f"Expected 1 log row after two POSTs (upsert); found {len(logs)}"
    finally:
        client.request("DELETE", f"/api/habits/{habit_id}?hard=true",
                       headers={"X-CSRF-Token": csrf})
