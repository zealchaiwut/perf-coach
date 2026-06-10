"""Tests for issue #392: Build habits management page with CRUD and reorder.

Runs against the feature/392 server at http://127.0.0.1:9002.
Risk: MEDIUM — new UI page + archive/reorder API additions.
→ 1-2 tests per HTTP-testable criterion; visual/browser ACs marked manual.

Prerequisites: tester392 user must exist in UAT DB with password "Test392pass!".
Created by the tester workflow via inline Python script.
"""
import os
import pytest
import httpx

BASE_URL = os.environ.get("UAT_BASE_URL", "http://127.0.0.1:9002")

_CREDENTIALS = {"username": "tester392", "password": "Test392pass!"}


def _extract_cookie(response: httpx.Response, name: str) -> str | None:
    """Extract a cookie value from Set-Cookie headers (ignoring Secure attribute)."""
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
        assert r.status_code == 200, f"Login failed: {r.status_code} {r.text}"
        # csrf-token has Secure flag; httpx won't send it over plain HTTP.
        # Extract from Set-Cookie header and inject without Secure so tests work.
        csrf_val = _extract_cookie(r, "csrf-token")
        if csrf_val:
            c.cookies.set("csrf-token", csrf_val, domain="127.0.0.1")
        # Clean up any leftover habits from previous runs
        all_habits = c.get("/api/habits?include_archived=true")
        if all_habits.status_code == 200 and csrf_val:
            for h in all_habits.json():
                c.request("DELETE", f"/api/habits/{h['id']}", headers={"X-CSRF-Token": csrf_val})
        yield c


def _csrf(client: httpx.Client) -> str:
    r = client.get("/api/csrf-token")
    assert r.status_code == 200, f"CSRF fetch failed: {r.status_code}"
    token = r.json()["csrf_token"]
    # Sync the new token into the cookie jar (it may have rotated)
    client.cookies.set("csrf-token", token, domain="127.0.0.1")
    return token


# ── AC: Route & page structure ─────────────────────────────────────────────

def test_habits_management_page__route_returns_200(client):
    # AC: Route /habits exists and renders habits.html
    r = client.get("/habits")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")


def test_habits_management_page__page_header_weekly_tracking(client):
    # AC: Page header reads "Habits — Weekly tracking"
    r = client.get("/habits")
    assert r.status_code == 200
    assert "Habits" in r.text
    assert "Weekly tracking" in r.text


def test_habits_management_page__new_habit_button_present(client):
    # AC: "+ New habit" button appears
    r = client.get("/habits")
    assert r.status_code == 200
    assert "New habit" in r.text


# ── AC: Habit CRUD ─────────────────────────────────────────────────────────

def test_habits_management_page__post_habit_full_fields(client):
    # AC: Save calls POST /api/habits (new); habit row displays icon, name,
    #     tracking_type, weekly target with unit, auto_fill_source
    csrf = _csrf(client)
    payload = {
        "name": "Zone 2 cardio",
        "tracking_type": "weekly_minutes",
        "weekly_target": 210,
        "unit": "min",
        "auto_fill_source": "workout.zone2_minutes",
        "icon": "ti-run",
        "color": "#3b82f6",
        "description": "Low-intensity aerobic training in Zone 2 heart rate",
    }
    r = client.post("/api/habits", json=payload, headers={"X-CSRF-Token": csrf})
    assert r.status_code == 201
    h = r.json()
    assert h["name"] == "Zone 2 cardio"
    assert h["tracking_type"] == "weekly_minutes"
    assert h["weekly_target"] == 210.0
    assert h["unit"] == "min"
    assert h["auto_fill_source"] == "workout.zone2_minutes"
    assert h["icon"] == "ti-run"
    assert h["color"] == "#3b82f6"
    assert h["is_archived"] is False
    assert "id" in h


def test_habits_management_page__get_habits_list_active_only(client):
    # AC: GET /api/habits returns active habits only
    r = client.get("/api/habits")
    assert r.status_code == 200
    habits = r.json()
    assert isinstance(habits, list)
    assert len(habits) >= 1
    # Confirm all returned habits are not archived
    for h in habits:
        assert h["is_archived"] is False


def test_habits_management_page__patch_habit_edit_name_and_color(client):
    # AC: Save calls PATCH /api/habits/{id} (edit); row updates in place
    csrf = _csrf(client)
    # Create a habit to edit
    r = client.post("/api/habits", json={
        "name": "Edit Me",
        "tracking_type": "weekly_count",
        "weekly_target": 3,
        "unit": "sessions",
    }, headers={"X-CSRF-Token": csrf})
    assert r.status_code == 201
    habit_id = r.json()["id"]

    # Edit name and color
    r = client.patch(f"/api/habits/{habit_id}",
                     json={"name": "Edited Name", "color": "#8b5cf6"},
                     headers={"X-CSRF-Token": csrf})
    assert r.status_code == 200
    h = r.json()
    assert h["name"] == "Edited Name"
    assert h["color"] == "#8b5cf6"

    # Clean up
    client.request("DELETE", f"/api/habits/{habit_id}", headers={"X-CSRF-Token": csrf})


# ── AC: Archive / Unarchive ────────────────────────────────────────────────

def test_habits_management_page__archive_habit_via_patch(client):
    # AC: Archive action → habit disappears from active list;
    #     "Archived habits" toggle reveals it
    csrf = _csrf(client)
    r = client.post("/api/habits", json={
        "name": "To Archive",
        "tracking_type": "weekly_count",
        "weekly_target": 2,
        "unit": "sessions",
    }, headers={"X-CSRF-Token": csrf})
    assert r.status_code == 201
    habit_id = r.json()["id"]

    # Archive it
    r = client.patch(f"/api/habits/{habit_id}",
                     json={"is_archived": True},
                     headers={"X-CSRF-Token": csrf})
    assert r.status_code == 200
    assert r.json()["is_archived"] is True

    # Excluded from active list
    active = client.get("/api/habits").json()
    active_ids = [h["id"] for h in active]
    assert habit_id not in active_ids

    # Present in archived list
    all_habits = client.get("/api/habits?include_archived=true").json()
    archived_ids = [h["id"] for h in all_habits if h["is_archived"]]
    assert habit_id in archived_ids

    # Clean up (unarchive first, then delete)
    client.patch(f"/api/habits/{habit_id}",
                 json={"is_archived": False},
                 headers={"X-CSRF-Token": csrf})
    client.request("DELETE", f"/api/habits/{habit_id}", headers={"X-CSRF-Token": csrf})


def test_habits_management_page__unarchive_restores_to_active(client):
    # AC: Unarchive action restores habit to active list
    csrf = _csrf(client)
    r = client.post("/api/habits", json={
        "name": "Unarchive Me",
        "tracking_type": "daily_checkmark",
        "weekly_target": 7,
        "unit": "days",
    }, headers={"X-CSRF-Token": csrf})
    assert r.status_code == 201
    habit_id = r.json()["id"]

    # Archive then unarchive
    client.patch(f"/api/habits/{habit_id}",
                 json={"is_archived": True},
                 headers={"X-CSRF-Token": csrf})
    r = client.patch(f"/api/habits/{habit_id}",
                     json={"is_archived": False},
                     headers={"X-CSRF-Token": csrf})
    assert r.status_code == 200
    assert r.json()["is_archived"] is False

    # Back in active list
    active_ids = [h["id"] for h in client.get("/api/habits").json()]
    assert habit_id in active_ids

    # Clean up
    client.request("DELETE", f"/api/habits/{habit_id}", headers={"X-CSRF-Token": csrf})


# ── AC: Drag-to-reorder ────────────────────────────────────────────────────

def test_habits_management_page__reorder_updates_sort_order(client):
    # AC: Drag handle triggers POST /api/habits/{id}/reorder; order persists
    csrf = _csrf(client)
    # Create two habits
    r1 = client.post("/api/habits", json={
        "name": "Habit A",
        "tracking_type": "weekly_count",
        "weekly_target": 1,
        "unit": "times",
    }, headers={"X-CSRF-Token": csrf})
    assert r1.status_code == 201
    id_a = r1.json()["id"]
    old_order_a = r1.json()["sort_order"]

    # Reorder habit A to position 99
    r = client.post(f"/api/habits/{id_a}/reorder",
                    json={"sort_order": 99},
                    headers={"X-CSRF-Token": csrf})
    assert r.status_code == 200
    assert r.json()["sort_order"] == 99

    # Verify persisted
    all_habits = {h["id"]: h for h in client.get("/api/habits").json()}
    assert all_habits[id_a]["sort_order"] == 99

    # Clean up
    client.request("DELETE", f"/api/habits/{id_a}", headers={"X-CSRF-Token": csrf})


# ── AC: Delete ─────────────────────────────────────────────────────────────

def test_habits_management_page__delete_removes_habit(client):
    # AC: Delete removes habit from active list; does not reappear on reload.
    # Backend uses soft-delete (archives) by default; ?hard=true does a hard delete.
    # DELETE returns 200 {"ok": True}, not 204.
    csrf = _csrf(client)
    r = client.post("/api/habits", json={
        "name": "Delete Me",
        "tracking_type": "weekly_count",
        "weekly_target": 1,
        "unit": "times",
    }, headers={"X-CSRF-Token": csrf})
    assert r.status_code == 201
    habit_id = r.json()["id"]

    # Delete (soft-archives the habit)
    r = client.request("DELETE", f"/api/habits/{habit_id}", headers={"X-CSRF-Token": csrf})
    assert r.status_code == 200
    assert r.json().get("ok") is True

    # Confirm no longer in active list
    active_ids = [h["id"] for h in client.get("/api/habits").json()]
    assert habit_id not in active_ids


# ── AC: Starter habits pre-seed ────────────────────────────────────────────

def test_habits_management_page__starter_zone2_cardio_habit_shape(client):
    # AC: Clicking Zone 2 cardio creates habit via POST /api/habits with correct data
    csrf = _csrf(client)
    # Simulate clicking the Zone 2 cardio suggestion button
    r = client.post("/api/habits", json={
        "name": "Zone 2 cardio",
        "tracking_type": "weekly_minutes",
        "weekly_target": 210,
        "unit": "min",
        "auto_fill_source": "workout.zone2_minutes",
        "icon": "ti-run",
        "color": "#3b82f6",
        "description": "Low-intensity aerobic training in Zone 2 heart rate",
    }, headers={"X-CSRF-Token": csrf})
    assert r.status_code == 201
    h = r.json()
    assert h["tracking_type"] == "weekly_minutes"
    assert h["weekly_target"] == 210.0
    assert h["auto_fill_source"] == "workout.zone2_minutes"

    # After at least 1 habit exists, GET /api/habits returns non-empty list
    habits = client.get("/api/habits").json()
    assert len(habits) >= 1

    # Clean up
    client.request("DELETE", f"/api/habits/{h['id']}", headers={"X-CSRF-Token": csrf})


# ── AC: Visual/interactive — requires browser ──────────────────────────────

def test_habits_management_page__top_nav_consistent():
    pytest.skip("manual — visual nav consistency check")


def test_habits_management_page__mobile_responsive_600px():
    pytest.skip("manual — resize browser to 400px and verify layout reflows")


def test_habits_management_page__no_console_errors():
    pytest.skip("manual — open browser DevTools and confirm zero JS console errors")


def test_habits_management_page__habit_row_displays_drag_handle_and_autofill_pill():
    pytest.skip("manual — browser visual check: drag handle, autofill pill visible in habit row")


def test_habits_management_page__zero_habits_shows_four_suggestion_buttons():
    pytest.skip("manual — browser: new user with no habits sees 4 starter suggestion buttons")


def test_habits_management_page__suggestion_buttons_hidden_after_first_habit():
    pytest.skip("manual — browser: once 1 habit exists, suggestion buttons are no longer shown")


def test_habits_management_page__icon_and_color_picker_in_modal():
    pytest.skip("manual — browser: open New habit modal, verify icon grid and color palette render")
