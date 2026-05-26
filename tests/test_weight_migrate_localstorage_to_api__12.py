"""
Tests for issue #12: Weight — migrate form and chart from localStorage to /api/weight (per-user)
One test per Acceptance Criterion (AC-1 through AC-12).
Server under test: http://127.0.0.1:9001
"""
import datetime
import httpx
import pytest

BASE = "http://127.0.0.1:9001"
TODAY = datetime.date.today().isoformat()


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c


@pytest.fixture(scope="module")
def alice_id(client):
    res = client.get("/api/users")
    assert res.status_code == 200
    users = res.json()
    alice = next((u for u in users if u["name"] == "Alice"), None)
    assert alice is not None, "Alice not found in /api/users"
    return alice["id"]


@pytest.fixture(scope="module")
def bob_id(client):
    res = client.get("/api/users")
    assert res.status_code == 200
    users = res.json()
    bob = next((u for u in users if u["name"] == "Bob"), None)
    assert bob is not None, "Bob not found in /api/users"
    return bob["id"]


def _clean_user_entries(client, user_id):
    """Delete all weight entries for a user to ensure test isolation."""
    res = client.get(f"/api/weight?user_id={user_id}")
    if res.status_code == 200:
        for entry in res.json():
            client.delete(f"/api/weight/{entry['id']}")


# ── AC-1: POST /api/weight returns 201 with correct shape ────────────────────

def test_ac1_post_weight_returns_201(client, alice_id):
    """AC-1: POST /api/weight?user_id=<uuid> returns 201 with id, weight_kg, recorded_date, created_at."""
    _clean_user_entries(client, alice_id)
    test_date = "2026-01-01"
    res = client.post(
        f"/api/weight?user_id={alice_id}",
        json={"weight_kg": 72.5, "recorded_date": test_date},
    )
    assert res.status_code == 201, f"Expected 201, got {res.status_code}: {res.text}"
    body = res.json()
    assert "id" in body
    assert body["weight_kg"] == 72.5
    assert body["recorded_date"] == test_date
    assert "created_at" in body


# ── AC-2: POST duplicate date returns 409 ────────────────────────────────────

def test_ac2_duplicate_date_returns_409(client, alice_id):
    """AC-2: POST same recorded_date for same user returns 409 with error message."""
    _clean_user_entries(client, alice_id)
    payload = {"weight_kg": 72.5, "recorded_date": "2026-01-02"}
    res1 = client.post(f"/api/weight?user_id={alice_id}", json=payload)
    assert res1.status_code == 201

    res2 = client.post(f"/api/weight?user_id={alice_id}", json=payload)
    assert res2.status_code == 409, f"Expected 409, got {res2.status_code}: {res2.text}"
    assert "error" in res2.json()


# ── AC-3: GET /api/weight returns sorted array ────────────────────────────────

def test_ac3_get_weight_sorted_ascending(client, alice_id):
    """AC-3: GET /api/weight?user_id=<uuid> returns array sorted by recorded_date ascending."""
    _clean_user_entries(client, alice_id)
    dates = ["2026-03-01", "2026-01-01", "2026-02-01"]
    weights = [70.0, 72.0, 71.0]
    for d, w in zip(dates, weights):
        r = client.post(f"/api/weight?user_id={alice_id}", json={"weight_kg": w, "recorded_date": d})
        assert r.status_code == 201

    res = client.get(f"/api/weight?user_id={alice_id}")
    assert res.status_code == 200
    entries = res.json()
    assert len(entries) == 3
    returned_dates = [e["recorded_date"] for e in entries]
    assert returned_dates == sorted(returned_dates), "Entries not sorted ascending"


def test_ac3_get_weight_empty_for_new_user(client, bob_id):
    """AC-3: GET /api/weight returns [] when user has no entries."""
    _clean_user_entries(client, bob_id)
    res = client.get(f"/api/weight?user_id={bob_id}")
    assert res.status_code == 200
    assert res.json() == []


# ── AC-4: DELETE /api/weight/<id> ─────────────────────────────────────────────

def test_ac4_delete_entry_returns_204(client, alice_id):
    """AC-4: DELETE /api/weight/<entry_id> returns 204 on success."""
    _clean_user_entries(client, alice_id)
    post_res = client.post(
        f"/api/weight?user_id={alice_id}",
        json={"weight_kg": 73.0, "recorded_date": "2026-04-01"},
    )
    assert post_res.status_code == 201
    entry_id = post_res.json()["id"]

    del_res = client.delete(f"/api/weight/{entry_id}")
    assert del_res.status_code == 204, f"Expected 204, got {del_res.status_code}"

    # Confirm gone
    get_res = client.get(f"/api/weight?user_id={alice_id}")
    ids = [e["id"] for e in get_res.json()]
    assert entry_id not in ids


def test_ac4_delete_nonexistent_returns_404(client):
    """AC-4: DELETE /api/weight/<nonexistent_id> returns 404."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    res = client.delete(f"/api/weight/{fake_id}")
    assert res.status_code == 404, f"Expected 404, got {res.status_code}"


# ── AC-5: GET /api/users returns Alice, Bob, Carol ────────────────────────────

def test_ac5_users_endpoint_returns_seeded_users(client):
    """AC-5: GET /api/users returns at least Alice, Bob, Carol so weight.html can populate selector."""
    res = client.get("/api/users")
    assert res.status_code == 200
    names = {u["name"] for u in res.json()}
    assert {"Alice", "Bob", "Carol"}.issubset(names), f"Missing expected users, got: {names}"
    for u in res.json():
        assert "id" in u
        assert "name" in u


# ── AC-6 & AC-7: Form submit behaviour (HTTP-level) ──────────────────────────

def test_ac6_post_creates_entry_and_can_be_fetched(client, alice_id):
    """AC-6: Successful POST (201) means entry is fetchable via GET."""
    _clean_user_entries(client, alice_id)
    post_date = "2026-05-01"
    res = client.post(
        f"/api/weight?user_id={alice_id}",
        json={"weight_kg": 75.0, "recorded_date": post_date},
    )
    assert res.status_code == 201
    entries = client.get(f"/api/weight?user_id={alice_id}").json()
    assert any(e["recorded_date"] == post_date and e["weight_kg"] == 75.0 for e in entries)


def test_ac7_duplicate_post_returns_409_with_error_message(client, alice_id):
    """AC-7: Duplicate date POST returns 409 with JSON error key."""
    _clean_user_entries(client, alice_id)
    payload = {"weight_kg": 70.0, "recorded_date": "2026-06-01"}
    client.post(f"/api/weight?user_id={alice_id}", json=payload)
    res = client.post(f"/api/weight?user_id={alice_id}", json=payload)
    assert res.status_code == 409
    body = res.json()
    assert "error" in body
    assert "date" in body["error"].lower(), f"Unexpected error message: {body['error']}"


# ── AC-8: GET per user isolates data ─────────────────────────────────────────

def test_ac8_entries_scoped_per_user(client, alice_id, bob_id):
    """AC-8: Each user's entries are independent — Alice's entries not visible for Bob."""
    _clean_user_entries(client, alice_id)
    _clean_user_entries(client, bob_id)

    alice_date = "2026-07-01"
    bob_date = "2026-07-02"
    client.post(f"/api/weight?user_id={alice_id}", json={"weight_kg": 70.0, "recorded_date": alice_date})
    client.post(f"/api/weight?user_id={bob_id}", json={"weight_kg": 80.0, "recorded_date": bob_date})

    alice_entries = client.get(f"/api/weight?user_id={alice_id}").json()
    bob_entries = client.get(f"/api/weight?user_id={bob_id}").json()

    alice_dates = {e["recorded_date"] for e in alice_entries}
    bob_dates = {e["recorded_date"] for e in bob_entries}

    assert alice_date in alice_dates
    assert bob_date not in alice_dates
    assert bob_date in bob_dates
    assert alice_date not in bob_dates


# ── AC-9: DELETE removes entry and GET reflects it ───────────────────────────

def test_ac9_delete_then_get_reflects_removal(client, alice_id):
    """AC-9: Deleting an entry causes it to disappear from GET /api/weight."""
    _clean_user_entries(client, alice_id)
    post_res = client.post(
        f"/api/weight?user_id={alice_id}",
        json={"weight_kg": 68.0, "recorded_date": "2026-08-01"},
    )
    assert post_res.status_code == 201
    entry_id = post_res.json()["id"]

    client.delete(f"/api/weight/{entry_id}")
    entries = client.get(f"/api/weight?user_id={alice_id}").json()
    assert all(e["id"] != entry_id for e in entries), "Deleted entry still visible"


# ── AC-10: No localStorage usage (static analysis) ───────────────────────────

def test_ac10_weight_js_no_localstorage():
    """AC-10: weight.js must not reference localStorage, STORAGE_KEY, loadEntries, or saveEntries."""
    import pathlib
    js_path = pathlib.Path(__file__).parent.parent / "js" / "weight.js"
    content = js_path.read_text()
    forbidden = ["localStorage", "STORAGE_KEY", "loadEntries", "saveEntries"]
    for token in forbidden:
        assert token not in content, f"Found forbidden token '{token}' in weight.js"


# ── AC-11: mock-data.js uses recorded_date / weight_kg fields ─────────────────

def test_ac11_mock_data_uses_api_field_names():
    """AC-11: MOCK_WEIGHT_ENTRIES in mock-data.js uses recorded_date and weight_kg (not date/weight)."""
    import pathlib
    mock_path = pathlib.Path(__file__).parent.parent / "js" / "mock-data.js"
    content = mock_path.read_text()
    assert "recorded_date" in content, "mock-data.js must use 'recorded_date' field"
    assert "weight_kg" in content, "mock-data.js must use 'weight_kg' field"
    # Old field names should be gone
    assert "{ date:" not in content, "mock-data.js still uses old 'date' field"
    assert ", weight:" not in content, "mock-data.js still uses old 'weight' field"


# ── AC-12: Non-2xx responses return JSON with error info ─────────────────────

def test_ac12_invalid_user_id_returns_error(client):
    """AC-12: API calls with invalid user_id return a non-2xx error response (not silent)."""
    res = client.get("/api/weight?user_id=not-a-uuid")
    assert res.status_code >= 400, f"Expected error status, got {res.status_code}"


def test_ac12_delete_invalid_id_returns_error(client):
    """AC-12: DELETE with invalid entry_id returns a non-2xx error response."""
    res = client.delete("/api/weight/not-a-uuid")
    assert res.status_code >= 400, f"Expected error status, got {res.status_code}"
