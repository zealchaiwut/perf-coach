"""Tests for issue #431: Enforce backfill window and add increment-log mode (runs against UAT)"""
import os
import time

import httpx
import pytest

BASE_URL = os.environ.get("UAT_BASE_URL") or "http://localhost:" + os.environ.get("UAT_PORT", "")
if not BASE_URL.startswith("http"):
    raise RuntimeError(
        "UAT_BASE_URL / UAT_PORT not set. Run the tester skill's Step 0 to resolve UAT before pytest."
    )

_CREDENTIALS = {"username": "tester392", "password": "Test392pass!"}
_RUN_ID = str(int(time.time()))[-6:]

# Date context: today = 2026-06-11 (Thu), current week Monday = 2026-06-08
_TODAY = "2026-06-11"        # Thursday (Bangkok) — in window
_IN_WINDOW = "2026-06-10"    # Wednesday — in window (not today)
_FUTURE = "2026-06-12"       # Friday — tomorrow, future
_LAST_WEEK = "2026-06-07"    # Last Sunday — before current Monday, locked


def _extract_cookie(response: httpx.Response, name: str):
    for header in response.headers.get_list("set-cookie"):
        parts = [p.strip() for p in header.split(";")]
        if parts and "=" in parts[0]:
            k, v = parts[0].split("=", 1)
            if k.strip() == name:
                return v.strip()
    return None


def _cookie_domain() -> str:
    from urllib.parse import urlparse
    host = urlparse(BASE_URL).hostname or "localhost"
    return "localhost.local" if host == "localhost" else host


def _csrf(client: httpx.Client) -> str:
    r = client.get("/api/csrf-token")
    assert r.status_code == 200, f"CSRF fetch failed: {r.status_code}"
    token = r.json()["csrf_token"]
    client.cookies.set("csrf-token", token, domain=_cookie_domain())
    return token


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE_URL, timeout=15.0) as c:
        r = c.post("/api/auth/login", json=_CREDENTIALS)
        assert r.status_code == 200, f"Login failed: {r.text}"
        csrf_val = _extract_cookie(r, "csrf-token")
        if csrf_val:
            c.cookies.set("csrf-token", csrf_val, domain=_cookie_domain())
        yield c


def _make_weekly_habit(client: httpx.Client) -> str:
    name = f"Wk431_{_RUN_ID}_{int(time.time() * 1000) % 100000}"
    r = client.post(
        "/api/habits",
        json={"name": name, "tracking_type": "weekly_count", "weekly_target": 5},
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert r.status_code == 201, f"Habit create failed: {r.text}"
    return r.json()["id"]


def _make_checkmark_habit(client: httpx.Client) -> str:
    name = f"Chk431_{_RUN_ID}_{int(time.time() * 1000) % 100000}"
    r = client.post(
        "/api/habits",
        json={"name": name, "tracking_type": "daily_checkmark"},
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert r.status_code == 201, f"Habit create failed: {r.text}"
    return r.json()["id"]


def _delete_habit(client: httpx.Client, hid: str) -> None:
    client.request("DELETE", f"/api/habits/{hid}", headers={"X-CSRF-Token": _csrf(client)})


# ─── Acceptance Criteria ──────────────────────────────────────────────────────

def test_backfill_window_increment_log_mode__in_window_date_200(client):
    # AC-a: backfill within current week → 201
    hid = _make_weekly_habit(client)
    try:
        r = client.post(
            f"/api/habits/{hid}/log",
            json={"log_date": _IN_WINDOW, "value": 20.0},
            headers={"X-CSRF-Token": _csrf(client)},
        )
        assert r.status_code == 201, f"Expected 201 for in-window date, got {r.status_code}: {r.text}"
    finally:
        _delete_habit(client, hid)


def test_backfill_window_increment_log_mode__future_date_422(client):
    # AC-b: future date → 422 future_date
    hid = _make_weekly_habit(client)
    try:
        r = client.post(
            f"/api/habits/{hid}/log",
            json={"log_date": _FUTURE, "value": 1.0},
            headers={"X-CSRF-Token": _csrf(client)},
        )
        assert r.status_code == 422, f"Expected 422 for future date, got {r.status_code}: {r.text}"
        assert r.json()["detail"]["error_code"] == "future_date"
    finally:
        _delete_habit(client, hid)


def test_backfill_window_increment_log_mode__past_week_locked_422(client):
    # AC-c: last-week date → 422 past_week_locked
    hid = _make_weekly_habit(client)
    try:
        r = client.post(
            f"/api/habits/{hid}/log",
            json={"log_date": _LAST_WEEK, "value": 1.0},
            headers={"X-CSRF-Token": _csrf(client)},
        )
        assert r.status_code == 422, f"Expected 422 for past-week date, got {r.status_code}: {r.text}"
        detail = r.json()["detail"]
        assert detail["error_code"] == "past_week_locked"
        assert "read-only" in detail.get("message", "").lower()
    finally:
        _delete_habit(client, hid)


def test_backfill_window_increment_log_mode__add_mode_accumulates(client):
    # AC-d: add mode: log 20, then +15 same day → row value = 35
    hid = _make_weekly_habit(client)
    try:
        r1 = client.post(
            f"/api/habits/{hid}/log",
            json={"log_date": _TODAY, "value": 20.0},
            headers={"X-CSRF-Token": _csrf(client)},
        )
        assert r1.status_code == 201, r1.text
        r2 = client.post(
            f"/api/habits/{hid}/log",
            json={"log_date": _TODAY, "value": 15.0, "mode": "add"},
            headers={"X-CSRF-Token": _csrf(client)},
        )
        assert r2.status_code == 201, r2.text
        assert r2.json()["value"] == 35.0, f"Expected 35.0 after add mode, got {r2.json().get('value')}"
    finally:
        _delete_habit(client, hid)


def test_backfill_window_increment_log_mode__set_mode_replaces(client):
    # AC-e: set mode: log 20, then set 15 same day → row value = 15
    hid = _make_weekly_habit(client)
    try:
        r1 = client.post(
            f"/api/habits/{hid}/log",
            json={"log_date": _TODAY, "value": 20.0},
            headers={"X-CSRF-Token": _csrf(client)},
        )
        assert r1.status_code == 201, r1.text
        r2 = client.post(
            f"/api/habits/{hid}/log",
            json={"log_date": _TODAY, "value": 15.0, "mode": "set"},
            headers={"X-CSRF-Token": _csrf(client)},
        )
        assert r2.status_code == 201, r2.text
        assert r2.json()["value"] == 15.0, f"Expected 15.0 after set mode, got {r2.json().get('value')}"
    finally:
        _delete_habit(client, hid)


def test_backfill_window_increment_log_mode__checkmark_ignores_mode(client):
    # AC-f: daily_checkmark ignores mode/value, always writes value = 1
    hid = _make_checkmark_habit(client)
    try:
        r = client.post(
            f"/api/habits/{hid}/log",
            json={"log_date": _TODAY, "value": 5.0, "mode": "add"},
            headers={"X-CSRF-Token": _csrf(client)},
        )
        assert r.status_code == 201, r.text
        assert r.json()["value"] == 1.0, f"Expected checkmark value=1, got {r.json().get('value')}"
    finally:
        _delete_habit(client, hid)


def test_backfill_window_increment_log_mode__week_current_value(client):
    # AC-g: response includes correct week_current_value
    hid = _make_weekly_habit(client)
    try:
        r1 = client.post(
            f"/api/habits/{hid}/log",
            json={"log_date": _IN_WINDOW, "value": 10.0},
            headers={"X-CSRF-Token": _csrf(client)},
        )
        assert r1.status_code == 201, r1.text
        assert "week_current_value" in r1.json(), "week_current_value missing from response"
        r2 = client.post(
            f"/api/habits/{hid}/log",
            json={"log_date": _TODAY, "value": 5.0},
            headers={"X-CSRF-Token": _csrf(client)},
        )
        assert r2.status_code == 201, r2.text
        body = r2.json()
        assert "week_current_value" in body, "week_current_value missing on second log response"
        assert body["week_current_value"] == 15.0, (
            f"Expected week_current_value=15.0 (10+5), got {body.get('week_current_value')}"
        )
    finally:
        _delete_habit(client, hid)


def test_backfill_window_increment_log_mode__delete_future_422(client):
    # DELETE enforces same window: future date → 422 future_date
    hid = _make_weekly_habit(client)
    try:
        r = client.request(
            "DELETE",
            f"/api/habits/{hid}/log",
            params={"date": _FUTURE},
            headers={"X-CSRF-Token": _csrf(client)},
        )
        assert r.status_code == 422, f"Expected 422 for DELETE on future date, got {r.status_code}: {r.text}"
        assert r.json()["detail"]["error_code"] == "future_date"
    finally:
        _delete_habit(client, hid)


def test_backfill_window_increment_log_mode__delete_past_week_422(client):
    # DELETE enforces same window: past-week date → 422 past_week_locked
    hid = _make_weekly_habit(client)
    try:
        r = client.request(
            "DELETE",
            f"/api/habits/{hid}/log",
            params={"date": _LAST_WEEK},
            headers={"X-CSRF-Token": _csrf(client)},
        )
        assert r.status_code == 422, f"Expected 422 for DELETE on past-week date, got {r.status_code}: {r.text}"
        assert r.json()["detail"]["error_code"] == "past_week_locked"
    finally:
        _delete_habit(client, hid)


def test_backfill_window_increment_log_mode__guard_value_out_of_range(client):
    # AC-8: resulting value after add > 10000 → 422 value_out_of_range
    hid = _make_weekly_habit(client)
    try:
        r1 = client.post(
            f"/api/habits/{hid}/log",
            json={"log_date": _TODAY, "value": 9000.0},
            headers={"X-CSRF-Token": _csrf(client)},
        )
        assert r1.status_code == 201, r1.text
        r2 = client.post(
            f"/api/habits/{hid}/log",
            json={"log_date": _TODAY, "value": 2000.0, "mode": "add"},
            headers={"X-CSRF-Token": _csrf(client)},
        )
        assert r2.status_code == 422, f"Expected 422 for value > 10000, got {r2.status_code}: {r2.text}"
        assert r2.json()["detail"]["error_code"] == "value_out_of_range"
    finally:
        _delete_habit(client, hid)
