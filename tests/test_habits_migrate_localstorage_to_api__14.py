"""
Tests for issue #14: Habits — migrate tracker from localStorage to /api/habits (per-user, Neon)
One test per Acceptance Criterion (AC-1 through AC-12).
Server under test: http://127.0.0.1:9001
"""
import datetime
import pathlib

import httpx
import pytest
from tests._admin_helpers import admin_cookies as _admin_cookies

BASE = "http://127.0.0.1:9001"
TODAY = datetime.date.today().isoformat()
YESTERDAY = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()


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


def _delete_habit(client, habit_id):
    client.delete(f"/api/habits/{habit_id}")


def _delete_log(client, log_id):
    client.delete(f"/api/habits/logs/{log_id}")


# ── AC-1: habits table has required schema (GET returns correct shape) ────────

def test_ac1_habits_table_exists_and_returns_correct_shape(client, alice_id):
    """AC-1: GET /api/habits returns a list with id, name, display_order, created_at fields."""
    res = client.get(f"/api/habits?user_id={alice_id}")
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
    habits = res.json()
    assert isinstance(habits, list)
    if habits:
        h = habits[0]
        assert "id" in h
        assert "name" in h
        assert "display_order" in h
        assert "created_at" in h


# ── AC-2: habit_logs table has required schema (POST/GET returns correct shape) ─

def test_ac2_habit_logs_table_exists_and_returns_correct_shape(client, alice_id):
    """AC-2: GET /api/habits/logs returns list with id, habit_id, user_id, logged_date."""
    res = client.get(f"/api/habits/logs?user_id={alice_id}&from={TODAY}&to={TODAY}")
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
    logs = res.json()
    assert isinstance(logs, list)
    # Post a habit and log to confirm shape
    habit_res = client.post("/api/habits", json={"user_id": alice_id, "name": "AC2 Test Habit"})
    assert habit_res.status_code == 201
    habit_id = habit_res.json()["id"]
    log_res = client.post(
        "/api/habits/logs",
        json={"habit_id": habit_id, "user_id": alice_id, "logged_date": YESTERDAY},
    )
    assert log_res.status_code == 201
    log = log_res.json()
    assert "id" in log
    assert "habit_id" in log
    assert "user_id" in log
    assert "logged_date" in log
    # Cleanup
    _delete_log(client, log["id"])
    _delete_habit(client, habit_id)


# ── AC-3: UNIQUE constraint on (habit_id, logged_date) ───────────────────────

def test_ac3_unique_constraint_habit_id_logged_date(client, alice_id):
    """AC-3: POST /api/habits/logs returns 409 when same habit+date already logged."""
    habit_res = client.post("/api/habits", json={"user_id": alice_id, "name": "AC3 Unique Test"})
    assert habit_res.status_code == 201
    habit_id = habit_res.json()["id"]
    payload = {"habit_id": habit_id, "user_id": alice_id, "logged_date": YESTERDAY}

    res1 = client.post("/api/habits/logs", json=payload)
    assert res1.status_code == 201, f"First log failed: {res1.text}"
    log_id = res1.json()["id"]

    res2 = client.post("/api/habits/logs", json=payload)
    assert res2.status_code == 409, f"Expected 409 on duplicate, got {res2.status_code}: {res2.text}"
    assert "error" in res2.json()

    # Cleanup
    _delete_log(client, log_id)
    _delete_habit(client, habit_id)


# ── AC-4: Seed has 3 habits per user ─────────────────────────────────────────

def test_ac4_seed_habits_present_for_alice(client, alice_id):
    """AC-4: Alice has seeded habits including Meditate, Exercise, Read 30 min."""
    res = client.get(f"/api/habits?user_id={alice_id}")
    assert res.status_code == 200
    names = {h["name"] for h in res.json()}
    for expected in ("Meditate", "Exercise", "Read 30 min"):
        assert expected in names, f"Seed habit '{expected}' missing for Alice; got: {names}"


def test_ac4_seed_habits_present_for_bob(client, bob_id):
    """AC-4: Bob also has seeded habits (Meditate, Exercise, Read 30 min)."""
    res = client.get(f"/api/habits?user_id={bob_id}")
    assert res.status_code == 200
    names = {h["name"] for h in res.json()}
    for expected in ("Meditate", "Exercise", "Read 30 min"):
        assert expected in names, f"Seed habit '{expected}' missing for Bob; got: {names}"


# ── AC-5: GET /api/habits filters active habits per user ─────────────────────

def test_ac5_get_habits_returns_active_habits_for_user(client, alice_id):
    """AC-5: GET /api/habits?user_id= returns active habits; archived ones excluded."""
    habit_res = client.post("/api/habits", json={"user_id": alice_id, "name": "AC5 Test Active"})
    assert habit_res.status_code == 201
    habit_id = habit_res.json()["id"]

    res = client.get(f"/api/habits?user_id={alice_id}")
    assert res.status_code == 200
    ids = {h["id"] for h in res.json()}
    assert habit_id in ids, "Newly created habit not in GET /api/habits"

    # Soft-delete it and verify it disappears
    del_res = client.delete(f"/api/habits/{habit_id}")
    assert del_res.status_code == 204

    res2 = client.get(f"/api/habits?user_id={alice_id}")
    ids2 = {h["id"] for h in res2.json()}
    assert habit_id not in ids2, "Archived habit still visible in GET /api/habits"


def test_ac5_invalid_user_id_returns_400(client):
    """AC-5: GET /api/habits with non-UUID user_id returns 400."""
    res = client.get("/api/habits?user_id=not-a-uuid")
    assert res.status_code == 400, f"Expected 400, got {res.status_code}"


# ── AC-6: POST /api/habits creates habit ─────────────────────────────────────

def test_ac6_post_habits_returns_201_with_correct_shape(client, alice_id):
    """AC-6: POST /api/habits returns 201 with id, name, display_order, created_at."""
    res = client.post("/api/habits", json={"user_id": alice_id, "name": "AC6 New Habit"})
    assert res.status_code == 201, f"Expected 201, got {res.status_code}: {res.text}"
    body = res.json()
    assert "id" in body
    assert body["name"] == "AC6 New Habit"
    assert "display_order" in body
    assert "created_at" in body
    _delete_habit(client, body["id"])


# ── AC-7: PATCH /api/habits/<habit_id> renames habit ────────────────────────

def test_ac7_patch_habit_renames(client, alice_id):
    """AC-7: PATCH /api/habits/<id> with name updates the habit name."""
    habit_res = client.post("/api/habits", json={"user_id": alice_id, "name": "AC7 Old Name"})
    assert habit_res.status_code == 201
    habit_id = habit_res.json()["id"]

    patch_res = client.patch(f"/api/habits/{habit_id}", json={"name": "AC7 New Name"})
    assert patch_res.status_code == 200, f"Expected 200, got {patch_res.status_code}: {patch_res.text}"
    assert patch_res.json()["name"] == "AC7 New Name"

    # Confirm GET reflects new name
    habits = client.get(f"/api/habits?user_id={alice_id}").json()
    updated = next((h for h in habits if h["id"] == habit_id), None)
    assert updated is not None
    assert updated["name"] == "AC7 New Name"
    _delete_habit(client, habit_id)


def test_ac7_patch_nonexistent_habit_returns_404(client):
    """AC-7: PATCH /api/habits/<nonexistent> returns 404."""
    res = client.patch("/api/habits/00000000-0000-0000-0000-000000000000", json={"name": "x"})
    assert res.status_code == 404, f"Expected 404, got {res.status_code}"


# ── AC-8: DELETE /api/habits/<habit_id> soft-deletes (sets archived_at) ─────

def test_ac8_delete_habit_soft_deletes(client, alice_id):
    """AC-8: DELETE /api/habits/<id> returns 204 and habit no longer appears in GET."""
    habit_res = client.post("/api/habits", json={"user_id": alice_id, "name": "AC8 Soft Delete"})
    assert habit_res.status_code == 201
    habit_id = habit_res.json()["id"]

    del_res = client.delete(f"/api/habits/{habit_id}")
    assert del_res.status_code == 204, f"Expected 204, got {del_res.status_code}"

    habits = client.get(f"/api/habits?user_id={alice_id}").json()
    assert all(h["id"] != habit_id for h in habits), "Soft-deleted habit still appears in GET"


def test_ac8_delete_nonexistent_habit_returns_404(client):
    """AC-8: DELETE /api/habits/<nonexistent> returns 404."""
    res = client.delete("/api/habits/00000000-0000-0000-0000-000000000000")
    assert res.status_code == 404, f"Expected 404, got {res.status_code}"


# ── AC-9: GET /api/habits/logs with date range ───────────────────────────────

def test_ac9_get_habit_logs_filters_by_date_range(client, alice_id):
    """AC-9: GET /api/habits/logs?user_id=&from=&to= returns logs in range only."""
    habit_res = client.post("/api/habits", json={"user_id": alice_id, "name": "AC9 Log Range"})
    assert habit_res.status_code == 201
    habit_id = habit_res.json()["id"]

    log_res = client.post(
        "/api/habits/logs",
        json={"habit_id": habit_id, "user_id": alice_id, "logged_date": YESTERDAY},
    )
    assert log_res.status_code == 201
    log_id = log_res.json()["id"]

    # Query range that includes YESTERDAY
    res = client.get(f"/api/habits/logs?user_id={alice_id}&from={YESTERDAY}&to={YESTERDAY}")
    assert res.status_code == 200
    log_ids = {l["id"] for l in res.json()}
    assert log_id in log_ids, "Log not returned when date is within query range"

    # Query today only — should NOT include yesterday's log
    res2 = client.get(f"/api/habits/logs?user_id={alice_id}&from={TODAY}&to={TODAY}")
    assert res2.status_code == 200
    log_ids2 = {l["id"] for l in res2.json()}
    assert log_id not in log_ids2, "Yesterday's log should not appear in today-only range"

    # Cleanup
    _delete_log(client, log_id)
    _delete_habit(client, habit_id)


def test_ac9_invalid_date_format_returns_400(client, alice_id):
    """AC-9: GET /api/habits/logs with bad date format returns 400."""
    res = client.get(f"/api/habits/logs?user_id={alice_id}&from=bad-date&to=also-bad")
    assert res.status_code == 400, f"Expected 400, got {res.status_code}"


# ── AC-10: POST /api/habits/logs is idempotent (409 on duplicate) ─────────────

def test_ac10_post_habit_log_idempotent_via_unique_constraint(client, alice_id):
    """AC-10: POST /api/habits/logs returns 409 on duplicate (habit_id, logged_date)."""
    habit_res = client.post("/api/habits", json={"user_id": alice_id, "name": "AC10 Idempotent"})
    assert habit_res.status_code == 201
    habit_id = habit_res.json()["id"]

    payload = {"habit_id": habit_id, "user_id": alice_id, "logged_date": YESTERDAY}
    res1 = client.post("/api/habits/logs", json=payload)
    assert res1.status_code == 201
    log_id = res1.json()["id"]

    res2 = client.post("/api/habits/logs", json=payload)
    assert res2.status_code == 409, f"Expected 409 on duplicate, got {res2.status_code}: {res2.text}"

    _delete_log(client, log_id)
    _delete_habit(client, habit_id)


# ── AC-11: DELETE /api/habits/logs/<log_id> removes the log ──────────────────

def test_ac11_delete_habit_log_returns_204(client, alice_id):
    """AC-11: DELETE /api/habits/logs/<id> returns 204 and log no longer appears in GET."""
    habit_res = client.post("/api/habits", json={"user_id": alice_id, "name": "AC11 Delete Log"})
    assert habit_res.status_code == 201
    habit_id = habit_res.json()["id"]

    log_res = client.post(
        "/api/habits/logs",
        json={"habit_id": habit_id, "user_id": alice_id, "logged_date": YESTERDAY},
    )
    assert log_res.status_code == 201
    log_id = log_res.json()["id"]

    del_res = client.delete(f"/api/habits/logs/{log_id}")
    assert del_res.status_code == 204, f"Expected 204, got {del_res.status_code}"

    logs = client.get(f"/api/habits/logs?user_id={alice_id}&from={YESTERDAY}&to={YESTERDAY}").json()
    assert all(l["id"] != log_id for l in logs), "Deleted log still visible in GET"

    _delete_habit(client, habit_id)


def test_ac11_delete_nonexistent_log_returns_404(client):
    """AC-11: DELETE /api/habits/logs/<nonexistent> returns 404."""
    res = client.delete("/api/habits/logs/00000000-0000-0000-0000-000000000000")
    assert res.status_code == 404, f"Expected 404, got {res.status_code}"


# ── AC-12: habits.js uses API (no localStorage) — static analysis ─────────────

def test_ac12_habits_js_uses_api_not_localstorage():
    """AC-12: habits.js must not reference localStorage or STORAGE_KEY."""
    js_path = pathlib.Path(__file__).parent.parent / "frontend" / "js" / "habits.js"
    content = js_path.read_text()
    forbidden = ["localStorage", "STORAGE_KEY"]
    for token in forbidden:
        assert token not in content, f"Found forbidden token '{token}' in habits.js"
    assert "fetch(" in content, "habits.js must use fetch() to call the API"


# ── AC-13: habits.html uses userReady event from user.js ─────────────────────

def test_ac13_habits_js_listens_for_user_ready_event():
    """AC-13: habits.js listens to userReady event dispatched by user.js."""
    js_path = pathlib.Path(__file__).parent.parent / "frontend" / "js" / "habits.js"
    content = js_path.read_text()
    assert "userReady" in content, "habits.js must listen for userReady event from user.js"


def test_ac13_user_js_dispatches_user_ready_event():
    """AC-13: user.js dispatches userReady event after loading the user."""
    js_path = pathlib.Path(__file__).parent.parent / "frontend" / "js" / "user.js"
    content = js_path.read_text()
    assert "userReady" in content, "user.js must dispatch the userReady event"


# ── AC-14: User switch refreshes habits ──────────────────────────────────────

def test_ac14_habits_js_listens_for_user_changed_event():
    """AC-14: habits.js listens to userChanged event to refresh on user switch."""
    js_path = pathlib.Path(__file__).parent.parent / "frontend" / "js" / "habits.js"
    content = js_path.read_text()
    assert "userChanged" in content, "habits.js must listen for userChanged event"


def test_ac14_user_js_dispatches_user_changed_event():
    """AC-14: user.js dispatches userChanged when user selector changes."""
    js_path = pathlib.Path(__file__).parent.parent / "frontend" / "js" / "user.js"
    content = js_path.read_text()
    assert "userChanged" in content, "user.js must dispatch userChanged on selector change"


# ── AC-15: localStorage fully removed from habits.js ─────────────────────────

def test_ac15_localStorage_fully_removed_from_habits_js():
    """AC-15: habits.js has no reference to localStorage or old localStorage helpers."""
    js_path = pathlib.Path(__file__).parent.parent / "frontend" / "js" / "habits.js"
    content = js_path.read_text()
    for token in ["localStorage", "STORAGE_KEY", "load()", "save("]:
        assert token not in content, f"Found old localStorage token '{token}' in habits.js"


# ── AC-16: Empty state shows "No habits yet. + Add habit" ────────────────────

def test_ac16_empty_state_message_in_habits_js():
    """AC-16: habits.js renders empty state with 'No habits yet.' text and '+ Add habit' button."""
    js_path = pathlib.Path(__file__).parent.parent / "frontend" / "js" / "habits.js"
    content = js_path.read_text()
    assert "No habits yet." in content, "Empty state text 'No habits yet.' missing from habits.js"
    assert "+ Add habit" in content, "Empty state link '+ Add habit' missing from habits.js"


# ── AC-17: Add habit modal → POST → list refresh ─────────────────────────────

def test_ac17_habits_html_has_add_modal():
    """AC-17: habits.html has the add-habit modal with a form."""
    html_path = pathlib.Path(__file__).parent.parent / "frontend" / "pages" / "habits.html"
    content = html_path.read_text()
    assert "habit-modal" in content, "habits.html missing #habit-modal element"
    assert "modal-form" in content, "habits.html missing modal form"
    assert "add-habit-btn" in content, "habits.html missing #add-habit-btn"


def test_ac17_post_habit_then_visible_in_get(client, alice_id):
    """AC-17: POST /api/habits creates a habit that immediately appears in GET list."""
    habit_name = "AC17 Modal Test Habit"
    post_res = client.post("/api/habits", json={"user_id": alice_id, "name": habit_name})
    assert post_res.status_code == 201
    habit_id = post_res.json()["id"]

    habits = client.get(f"/api/habits?user_id={alice_id}").json()
    assert any(h["id"] == habit_id and h["name"] == habit_name for h in habits), \
        "Newly created habit not found in GET list"

    _delete_habit(client, habit_id)


# ── Per-user isolation (cross-cutting) ───────────────────────────────────────

def test_habits_scoped_per_user(client, alice_id, bob_id):
    """Habits are per-user: Alice's habits not visible for Bob and vice versa."""
    alice_habit_res = client.post("/api/habits", json={"user_id": alice_id, "name": "Alice Only Habit"})
    assert alice_habit_res.status_code == 201
    alice_habit_id = alice_habit_res.json()["id"]

    bob_habits = client.get(f"/api/habits?user_id={bob_id}").json()
    bob_habit_ids = {h["id"] for h in bob_habits}
    assert alice_habit_id not in bob_habit_ids, "Alice's habit is visible for Bob"

    _delete_habit(client, alice_habit_id)
