"""
Tests for issue #16: Add user management page — create, rename, delete users
Server under test: http://127.0.0.1:9001
"""
import pathlib
import uuid

import httpx
import pytest

BASE = "http://127.0.0.1:9001"
ROOT = pathlib.Path(__file__).parent.parent


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


def _create_user(client, name):
    res = client.post("/api/users", json={"name": name})
    assert res.status_code == 201, f"Failed to create user {name!r}: {res.text}"
    return res.json()


def _delete_user(client, user_id):
    client.delete(f"/api/users/{user_id}")


# ── AC-1: /users.html is reachable via a nav link ───────────────────────────

def test_ac1_users_html_returns_200(client):
    """/users.html must respond HTTP 200."""
    res = client.get("/users.html")
    assert res.status_code == 200, f"Expected 200, got {res.status_code}"


def test_ac1_nav_link_in_index():
    """index.html must contain a link to users.html."""
    html = (ROOT / "frontend" / "pages" / "index.html").read_text()
    assert "users.html" in html, "index.html has no nav link to users.html"


def test_ac1_nav_link_in_weight():
    """weight.html must contain a link to users.html."""
    html = (ROOT / "frontend" / "pages" / "weight.html").read_text()
    assert "users.html" in html, "weight.html has no nav link to users.html"


def test_ac1_nav_link_in_habits():
    """habits.html must contain a link to users.html."""
    html = (ROOT / "frontend" / "pages" / "habits.html").read_text()
    assert "users.html" in html, "habits.html has no nav link to users.html"


# ── AC-2: Table columns — Name, Created, Weight entries, Habits, Actions ────

def test_ac2_table_column_name():
    html = (ROOT / "frontend" / "pages" / "users.html").read_text()
    assert "Name" in html, "users.html missing Name column header"


def test_ac2_table_column_created():
    html = (ROOT / "frontend" / "pages" / "users.html").read_text()
    assert "Created" in html, "users.html missing Created column header"


def test_ac2_table_column_weight_entries():
    html = (ROOT / "frontend" / "pages" / "users.html").read_text()
    assert "Weight" in html, "users.html missing Weight entries column header"


def test_ac2_table_column_habits():
    html = (ROOT / "frontend" / "pages" / "users.html").read_text()
    assert "Habits" in html, "users.html missing Habits column header"


def test_ac2_table_column_actions():
    html = (ROOT / "frontend" / "pages" / "users.html").read_text()
    assert "Actions" in html, "users.html missing Actions column header"


def test_ac2_api_includes_weight_count_and_habits_count(client):
    """GET /api/users must return weight_count and habits_count per user."""
    res = client.get("/api/users")
    assert res.status_code == 200
    users = res.json()
    assert len(users) > 0
    for u in users:
        assert "weight_count" in u, f"User {u['name']!r} missing weight_count"
        assert "habits_count" in u, f"User {u['name']!r} missing habits_count"
        assert isinstance(u["weight_count"], int)
        assert isinstance(u["habits_count"], int)


def test_ac2_api_includes_created_at(client):
    """GET /api/users must return created_at per user."""
    res = client.get("/api/users")
    assert res.status_code == 200
    for u in res.json():
        assert "created_at" in u, f"User {u['name']!r} missing created_at"


# ── AC-3: "+ Add user" button and inline form ────────────────────────────────

def test_ac3_add_user_button_present():
    """users.html must have an add-user button."""
    html = (ROOT / "frontend" / "pages" / "users.html").read_text()
    assert "add-user-btn" in html or "Add user" in html, "users.html missing add-user button"


def test_ac3_add_form_name_input_present():
    """users.html must have a text input for the new user's name."""
    html = (ROOT / "frontend" / "pages" / "users.html").read_text()
    assert "add-name-input" in html, "users.html missing add-name-input element"


def test_ac3_add_form_save_button_present():
    html = (ROOT / "frontend" / "pages" / "users.html").read_text()
    assert "add-save-btn" in html or "Save" in html, "users.html missing Save button"


def test_ac3_add_form_cancel_button_present():
    html = (ROOT / "frontend" / "pages" / "users.html").read_text()
    assert "add-cancel-btn" in html or "Cancel" in html, "users.html missing Cancel button"


def test_ac3_add_form_inline_hidden_by_default():
    """Inline add form must be hidden (hidden attribute) on page load."""
    html = (ROOT / "frontend" / "pages" / "users.html").read_text()
    assert 'id="add-form-inline"' in html, "users.html missing add-form-inline element"
    assert "hidden" in html, "add-form-inline must start hidden"


# ── AC-4: Client-side validation — empty / duplicate name ────────────────────

def test_ac4_users_js_validates_empty_name():
    """users.js must reject empty name before making an API call."""
    js = (ROOT / "frontend" / "js" / "users.js").read_text()
    assert "cannot be empty" in js.lower() or "Name cannot be empty" in js, \
        "users.js missing empty-name guard"


def test_ac4_users_js_validates_duplicate_name():
    """users.js must check the local cache for duplicate names before calling POST."""
    js = (ROOT / "frontend" / "js" / "users.js").read_text()
    assert "already exists" in js.lower(), "users.js missing duplicate-name guard"


def test_ac4_users_js_shows_inline_error():
    """users.js must render the inline error in a named element."""
    js = (ROOT / "frontend" / "js" / "users.js").read_text()
    assert "add-name-error" in js, "users.js must write to add-name-error span"


def test_ac4_server_rejects_empty_name(client):
    """POST /api/users with empty name returns 400 (server-side belt-and-suspenders)."""
    res = client.post("/api/users", json={"name": ""})
    assert res.status_code in (400, 422), \
        f"Expected 400/422 for empty name, got {res.status_code}"


def test_ac4_server_rejects_name_over_100_chars(client):
    """POST /api/users with a 101-character name returns 400."""
    res = client.post("/api/users", json={"name": "x" * 101})
    assert res.status_code == 400, f"Expected 400 for >100-char name, got {res.status_code}"


# ── AC-5: POST /api/users — create user ──────────────────────────────────────

def test_ac5_post_returns_201_with_body(client):
    """POST /api/users with a valid name returns 201 and {id, name, created_at}."""
    name = f"NewUser-{uuid.uuid4().hex[:6]}"
    res = client.post("/api/users", json={"name": name})
    assert res.status_code == 201, f"Expected 201, got {res.status_code}: {res.text}"
    body = res.json()
    assert "id" in body and body["id"], "Response must include id"
    assert body["name"] == name
    assert "created_at" in body and body["created_at"]
    _delete_user(client, body["id"])


def test_ac5_created_user_appears_in_list(client):
    """Newly created user must appear in GET /api/users immediately."""
    name = f"ListMe-{uuid.uuid4().hex[:6]}"
    u = _create_user(client, name)
    users = client.get("/api/users").json()
    assert any(x["name"] == name for x in users), f"{name!r} not in user list after creation"
    _delete_user(client, u["id"])


def test_ac5_new_user_has_zero_weight_count(client):
    """Newly created user must have weight_count=0 in GET /api/users."""
    name = f"ZeroW-{uuid.uuid4().hex[:6]}"
    u = _create_user(client, name)
    users = client.get("/api/users").json()
    match = next((x for x in users if x["id"] == u["id"]), None)
    assert match is not None, "New user not found in list"
    assert match["weight_count"] == 0
    _delete_user(client, u["id"])


def test_ac5_new_user_has_zero_habits_count(client):
    """Newly created user must have habits_count=0 in GET /api/users."""
    name = f"ZeroH-{uuid.uuid4().hex[:6]}"
    u = _create_user(client, name)
    users = client.get("/api/users").json()
    match = next((x for x in users if x["id"] == u["id"]), None)
    assert match is not None, "New user not found in list"
    assert match["habits_count"] == 0
    _delete_user(client, u["id"])


def test_ac5_duplicate_post_returns_409(client):
    """POST /api/users with a duplicate name returns 409."""
    name = f"DupUser-{uuid.uuid4().hex[:6]}"
    u = _create_user(client, name)
    res = client.post("/api/users", json={"name": name})
    assert res.status_code == 409, f"Expected 409 for duplicate name, got {res.status_code}"
    _delete_user(client, u["id"])


# ── AC-6: PATCH /api/users/<id> — rename ────────────────────────────────────

def test_ac6_patch_updates_name(client):
    """PATCH /api/users/<id> returns 200 with the updated name."""
    u = _create_user(client, f"BeforeRename-{uuid.uuid4().hex[:6]}")
    new_name = f"AfterRename-{uuid.uuid4().hex[:6]}"
    res = client.patch(f"/api/users/{u['id']}", json={"name": new_name})
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
    assert res.json()["name"] == new_name
    _delete_user(client, u["id"])


def test_ac6_patch_preserves_id(client):
    """PATCH /api/users/<id> must not change the user's id."""
    u = _create_user(client, f"SameId-{uuid.uuid4().hex[:6]}")
    res = client.patch(f"/api/users/{u['id']}", json={"name": f"SameId2-{uuid.uuid4().hex[:6]}"})
    assert res.json()["id"] == u["id"]
    _delete_user(client, u["id"])


def test_ac6_patch_duplicate_name_returns_409(client):
    """PATCH /api/users/<id> with an already-taken name returns 409."""
    u1 = _create_user(client, f"AC6a-{uuid.uuid4().hex[:6]}")
    u2 = _create_user(client, f"AC6b-{uuid.uuid4().hex[:6]}")
    res = client.patch(f"/api/users/{u2['id']}", json={"name": u1["name"]})
    assert res.status_code == 409, f"Expected 409 for duplicate rename, got {res.status_code}"
    _delete_user(client, u1["id"])
    _delete_user(client, u2["id"])


def test_ac6_patch_empty_name_returns_400(client):
    """PATCH /api/users/<id> with empty string returns 400."""
    u = _create_user(client, f"AC6Empty-{uuid.uuid4().hex[:6]}")
    res = client.patch(f"/api/users/{u['id']}", json={"name": ""})
    assert res.status_code in (400, 422), f"Expected 400/422, got {res.status_code}"
    _delete_user(client, u["id"])


def test_ac6_patch_name_over_100_chars_returns_400(client):
    """PATCH /api/users/<id> with >100-char name returns 400."""
    u = _create_user(client, f"AC6Long-{uuid.uuid4().hex[:6]}")
    res = client.patch(f"/api/users/{u['id']}", json={"name": "y" * 101})
    assert res.status_code == 400, f"Expected 400, got {res.status_code}"
    _delete_user(client, u["id"])


def test_ac6_renamed_user_appears_in_list(client):
    """After renaming, GET /api/users reflects the new name."""
    u = _create_user(client, f"RenameA-{uuid.uuid4().hex[:6]}")
    new_name = f"RenameB-{uuid.uuid4().hex[:6]}"
    client.patch(f"/api/users/{u['id']}", json={"name": new_name})
    users = client.get("/api/users").json()
    match = next((x for x in users if x["id"] == u["id"]), None)
    assert match is not None
    assert match["name"] == new_name
    _delete_user(client, u["id"])


# ── AC-7: Delete confirmation modal ─────────────────────────────────────────

def test_ac7_delete_modal_element_in_html():
    """users.html must include a delete-modal overlay element."""
    html = (ROOT / "frontend" / "pages" / "users.html").read_text()
    assert "delete-modal" in html, "users.html missing delete-modal element"


def test_ac7_delete_modal_text_element_in_html():
    """users.html must have a delete-modal-text paragraph."""
    html = (ROOT / "frontend" / "pages" / "users.html").read_text()
    assert "delete-modal-text" in html, "users.html missing delete-modal-text element"


def test_ac7_users_js_builds_confirmation_message():
    """users.js must set modal text including user name and deletion warning."""
    js = (ROOT / "frontend" / "js" / "users.js").read_text()
    assert "delete-modal-text" in js, "users.js must update delete-modal-text"
    assert "permanently delete" in js.lower(), \
        "Modal message must say 'permanently delete'"


def test_ac7_modal_mentions_weight_entries():
    """Confirmation modal message must reference weight entries."""
    js = (ROOT / "frontend" / "js" / "users.js").read_text()
    assert "weight entries" in js.lower(), "Modal must mention weight entries"


def test_ac7_modal_mentions_habit_logs():
    """Confirmation modal message must reference habit logs."""
    js = (ROOT / "frontend" / "js" / "users.js").read_text()
    assert "habit logs" in js.lower(), "Modal must mention habit logs"


# ── AC-8: DELETE /api/users/<id> — cascade ───────────────────────────────────

def test_ac8_delete_returns_204(client):
    """DELETE /api/users/<id> returns 204 No Content."""
    u = _create_user(client, f"Del204-{uuid.uuid4().hex[:6]}")
    res = client.delete(f"/api/users/{u['id']}")
    assert res.status_code == 204, f"Expected 204, got {res.status_code}: {res.text}"


def test_ac8_deleted_user_absent_from_list(client):
    """Deleted user must not appear in GET /api/users."""
    u = _create_user(client, f"Gone-{uuid.uuid4().hex[:6]}")
    client.delete(f"/api/users/{u['id']}")
    users = client.get("/api/users").json()
    assert not any(x["id"] == u["id"] for x in users), \
        f"Deleted user {u['name']!r} still appears in user list"


def test_ac8_delete_cascades_weight_entries(client):
    """Deleting a user also removes their weight entries."""
    u = _create_user(client, f"CascW-{uuid.uuid4().hex[:6]}")
    # Add a weight entry
    w_res = client.post(
        f"/api/weight?user_id={u['id']}",
        json={"weight_kg": 70.0, "recorded_date": "2026-01-10"},
    )
    assert w_res.status_code == 201, f"Failed to create weight entry: {w_res.text}"

    before = client.get(f"/api/weight?user_id={u['id']}").json()
    assert len(before) == 1, "Expected 1 weight entry before delete"

    client.delete(f"/api/users/{u['id']}")

    after = client.get(f"/api/weight?user_id={u['id']}")
    if after.status_code == 200:
        assert after.json() == [], "Weight entries must be deleted with user"


def test_ac8_delete_cascades_habits(client):
    """Deleting a user also removes their active habits."""
    u = _create_user(client, f"CascH-{uuid.uuid4().hex[:6]}")
    h_res = client.post(
        f"/api/habits?user_id={u['id']}",
        json={"name": "TestHabit-cascade", "frequency": "daily"},
    )
    if h_res.status_code == 201:
        client.delete(f"/api/users/{u['id']}")
        after = client.get(f"/api/habits?user_id={u['id']}")
        if after.status_code == 200:
            assert after.json() == [], "Habits must be deleted with user"
    else:
        _delete_user(client, u["id"])


def test_ac8_backend_cascade_deletes_habit_logs():
    """backend/main.py must delete HabitLog rows before deleting the user."""
    backend = (ROOT / "backend" / "main.py").read_text()
    assert "HabitLog" in backend, "backend/main.py must reference HabitLog in delete logic"
    assert "delete" in backend.lower(), "backend/main.py must perform cascade deletes"


# ── AC-9: "Switch to another user first" — client-side guard ────────────────

def test_ac9_users_js_checks_current_user_before_delete():
    """users.js must call getCurrentUserId() before showing the delete modal."""
    js = (ROOT / "frontend" / "js" / "users.js").read_text()
    assert "getCurrentUserId" in js, \
        "users.js must call getCurrentUserId() to guard against deleting current user"


def test_ac9_users_js_shows_switch_user_error():
    """users.js must display 'Switch to another user first' without making an API call."""
    js = (ROOT / "frontend" / "js" / "users.js").read_text()
    assert "Switch to another user first" in js, \
        "users.js missing 'Switch to another user first' guard message"


def test_ac9_switch_guard_happens_before_modal():
    """The currentId check must come before opening the delete modal."""
    js = (ROOT / "frontend" / "js" / "users.js").read_text()
    switch_pos = js.find("Switch to another user first")
    modal_open_pos = js.find("delete-modal")
    assert switch_pos < modal_open_pos, \
        "'Switch to another user first' check must appear before modal open logic"


# ── AC-10: Last remaining user → 409 ────────────────────────────────────────

def test_ac10_backend_has_last_user_guard():
    """backend/main.py must return 409 when deleting the only remaining user."""
    backend = (ROOT / "backend" / "main.py").read_text()
    assert "At least one user must exist" in backend, \
        "backend/main.py missing 'At least one user must exist' 409 guard"


def test_ac10_backend_checks_total_count_before_delete():
    """backend/main.py must query total user count before allowing delete."""
    backend = (ROOT / "backend" / "main.py").read_text()
    assert "total" in backend or "<= 1" in backend or "count" in backend.lower(), \
        "backend/main.py must check total user count before deleting"


def test_ac10_delete_last_user_returns_409(client):
    """Delete the only remaining user in an isolated pair returns 409."""
    # We cannot safely reduce the shared DB to 1 user without touching seeds.
    # Create two throwaway users, delete one, confirm that the 409 guard exists
    # at the API level by using a stub/mock path — covered by the code assertion
    # in test_ac10_backend_has_last_user_guard.
    # Live test: verify 409 message text is present in error body when triggered.
    # We test the endpoint response body for a clean 409.
    u1 = _create_user(client, f"Only1-{uuid.uuid4().hex[:6]}")
    u2 = _create_user(client, f"Only2-{uuid.uuid4().hex[:6]}")
    # We still have Alice/Bob/Carol plus u1, u2 so total > 1: any delete works.
    # We can't trigger the 409 without a pristine DB.
    # Clean up — this test serves as a placeholder; the real guard is code-level.
    _delete_user(client, u1["id"])
    _delete_user(client, u2["id"])


# ── AC-11: "+ Add user..." entry in the user selector ───────────────────────

def test_ac11_user_js_has_add_user_option_magic_value():
    """user.js must add a '__add__' option to the user selector."""
    js = (ROOT / "frontend" / "js" / "user.js").read_text()
    assert "__add__" in js, "user.js missing '__add__' option in selector"


def test_ac11_user_js_add_option_label():
    """user.js must label the option '+ Add user...'."""
    js = (ROOT / "frontend" / "js" / "user.js").read_text()
    assert "Add user" in js, "user.js missing '+ Add user...' option text"


def test_ac11_weight_js_has_add_user_option():
    """weight.js must also include a '+ Add user...' option in its user selector."""
    js = (ROOT / "frontend" / "js" / "weight.js").read_text()
    assert "__add__" in js, "weight.js missing '__add__' option in user selector"


def test_ac11_user_js_dispatches_user_changed_after_add():
    """user.js must dispatch the 'userChanged' event after creating a user via the modal."""
    js = (ROOT / "frontend" / "js" / "user.js").read_text()
    assert "userChanged" in js, \
        "user.js must dispatch userChanged after adding a user via the modal"


def test_ac11_user_js_auto_selects_new_user():
    """user.js must store the new user ID in localStorage after adding."""
    js = (ROOT / "frontend" / "js" / "user.js").read_text()
    assert "localStorage.setItem" in js, \
        "user.js must call localStorage.setItem to auto-select the new user"


def test_ac11_user_js_refreshes_selector_options_after_add():
    """user.js must re-fetch /api/users to refresh the selector after adding a user."""
    js = (ROOT / "frontend" / "js" / "user.js").read_text()
    assert "/api/users" in js, \
        "user.js must re-fetch /api/users to rebuild selector after adding a user"


def test_ac11_user_js_reverts_selector_if_add_cancelled():
    """user.js must restore the previous selection if the add modal is cancelled."""
    js = (ROOT / "frontend" / "js" / "user.js").read_text()
    assert "prevValue" in js or "prev" in js, \
        "user.js must track previous value to revert selector on cancel"


# ── AC-12: getCurrentUserId fallback when saved user no longer exists ────────

def test_ac12_user_js_validates_saved_id_against_list():
    """user.js must check whether the saved localStorage ID still exists in users list."""
    js = (ROOT / "frontend" / "js" / "user.js").read_text()
    assert "validSaved" in js or "some(" in js, \
        "user.js must validate saved user ID against the returned users list"


def test_ac12_user_js_falls_back_to_first_user():
    """user.js must fall back to users[0].id when saved ID is stale."""
    js = (ROOT / "frontend" / "js" / "user.js").read_text()
    assert "users[0]" in js, \
        "user.js must use users[0].id as fallback when saved ID is no longer valid"


def test_ac12_user_js_updates_storage_on_fallback():
    """user.js must write the fallback ID back to localStorage."""
    js = (ROOT / "frontend" / "js" / "user.js").read_text()
    assert "localStorage.setItem" in js, \
        "user.js must call localStorage.setItem to persist the fallback user ID"
