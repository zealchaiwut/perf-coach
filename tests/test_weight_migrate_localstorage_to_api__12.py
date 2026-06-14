"""
Tests for issue #12: Weight — migrate form and chart from localStorage to /api/weight-entries (per-user)
One test per Acceptance Criterion (AC-1 through AC-12).
Server under test: http://127.0.0.1:9001

Note: original tests used the now-removed legacy weight endpoint; updated to
/api/weight-entries (issue #489) which supersedes it. Logical intent preserved.
"""
import datetime
import httpx
import pytest

BASE = "http://127.0.0.1:9001"
TODAY = datetime.date.today().isoformat()

WE = "/api/weight-entries"


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
    """Delete all weight entries for a user (covers full 2026 year for test isolation)."""
    res = client.get(f"{WE}?user_id={user_id}&from=2026-01-01&to=2026-12-31")
    if res.status_code == 200:
        for entry in res.json()["entries"]:
            client.delete(f"{WE}/{entry['id']}")


# ── AC-1: POST /api/weight-entries returns 201 with correct shape ─────────────

def test_ac1_post_weight_returns_201(client, alice_id):
    """AC-1: POST /api/weight-entries returns 201 with id, weight_kg, entry_date, created_at."""
    _clean_user_entries(client, alice_id)
    test_date = "2026-01-01"
    res = client.post(
        WE,
        json={"user_id": alice_id, "weight_kg": 72.5, "entry_date": test_date},
    )
    assert res.status_code == 201, f"Expected 201, got {res.status_code}: {res.text}"
    body = res.json()
    assert "id" in body
    assert body["weight_kg"] == 72.5
    assert body["entry_date"] == test_date
    assert "created_at" in body


# ── AC-2: POST duplicate date returns 409 ─────────────────────────────────────

def test_ac2_duplicate_date_returns_409(client, alice_id):
    """AC-2: POST same entry_date for same user returns 409."""
    _clean_user_entries(client, alice_id)
    payload = {"user_id": alice_id, "weight_kg": 72.5, "entry_date": "2026-01-02"}
    res1 = client.post(WE, json=payload)
    assert res1.status_code == 201

    res2 = client.post(WE, json=payload)
    assert res2.status_code == 409, f"Expected 409, got {res2.status_code}: {res2.text}"
    assert "error_code" in res2.json()


# ── AC-3: GET /api/weight-entries returns sorted array ────────────────────────

def test_ac3_get_weight_sorted_descending(client, alice_id):
    """AC-3: GET /api/weight-entries returns array sorted by entry_date descending."""
    _clean_user_entries(client, alice_id)
    dates = ["2026-03-01", "2026-01-01", "2026-02-01"]
    weights = [70.0, 72.0, 71.0]
    for d, w in zip(dates, weights):
        r = client.post(WE, json={"user_id": alice_id, "weight_kg": w, "entry_date": d})
        assert r.status_code == 201

    res = client.get(f"{WE}?user_id={alice_id}&from=2026-01-01&to=2026-12-31")
    assert res.status_code == 200
    entries = res.json()["entries"]
    assert len(entries) == 3
    returned_dates = [e["entry_date"] for e in entries]
    assert returned_dates == sorted(returned_dates, reverse=True), "Entries not sorted descending"


def test_ac3_get_weight_empty_for_new_user(client, bob_id):
    """AC-3: GET /api/weight-entries returns empty entries when user has no entries."""
    _clean_user_entries(client, bob_id)
    res = client.get(f"{WE}?user_id={bob_id}&from=2026-01-01&to=2026-12-31")
    assert res.status_code == 200
    assert res.json()["entries"] == []


# ── AC-4: DELETE /api/weight-entries/<id> ─────────────────────────────────────

def test_ac4_delete_entry_returns_204(client, alice_id):
    """AC-4: DELETE /api/weight-entries/<entry_id> returns 204 on success."""
    _clean_user_entries(client, alice_id)
    post_res = client.post(
        WE,
        json={"user_id": alice_id, "weight_kg": 73.0, "entry_date": "2026-04-01"},
    )
    assert post_res.status_code == 201
    entry_id = post_res.json()["id"]

    del_res = client.delete(f"{WE}/{entry_id}")
    assert del_res.status_code == 204, f"Expected 204, got {del_res.status_code}"

    get_res = client.get(f"{WE}?user_id={alice_id}&from=2026-01-01&to=2026-12-31")
    ids = [e["id"] for e in get_res.json()["entries"]]
    assert entry_id not in ids


def test_ac4_delete_nonexistent_returns_404(client):
    """AC-4: DELETE /api/weight-entries/<nonexistent_id> returns 404."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    res = client.delete(f"{WE}/{fake_id}")
    assert res.status_code == 404, f"Expected 404, got {res.status_code}"


# ── AC-5: GET /api/users returns Alice, Bob, Carol ────────────────────────────

def test_ac5_users_endpoint_returns_seeded_users(client):
    """AC-5: GET /api/users returns at least Alice, Bob, Carol."""
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
        WE,
        json={"user_id": alice_id, "weight_kg": 75.0, "entry_date": post_date},
    )
    assert res.status_code == 201
    entries = client.get(
        f"{WE}?user_id={alice_id}&from=2026-01-01&to=2026-12-31"
    ).json()["entries"]
    assert any(e["entry_date"] == post_date and e["weight_kg"] == 75.0 for e in entries)


def test_ac7_duplicate_post_returns_409_with_error_code(client, alice_id):
    """AC-7: Duplicate date POST returns 409 with JSON error_code field."""
    _clean_user_entries(client, alice_id)
    payload = {"user_id": alice_id, "weight_kg": 70.0, "entry_date": "2026-06-01"}
    client.post(WE, json=payload)
    res = client.post(WE, json=payload)
    assert res.status_code == 409
    body = res.json()
    assert "error_code" in body, f"Expected 'error_code' in body, got: {body}"
    assert body["error_code"] == "duplicate"


# ── AC-8: GET per user isolates data ─────────────────────────────────────────

def test_ac8_entries_scoped_per_user(client, alice_id, bob_id):
    """AC-8: Each user's entries are independent."""
    _clean_user_entries(client, alice_id)
    _clean_user_entries(client, bob_id)

    alice_date = "2026-07-01"
    bob_date = "2026-07-02"
    client.post(WE, json={"user_id": alice_id, "weight_kg": 70.0, "entry_date": alice_date})
    client.post(WE, json={"user_id": bob_id, "weight_kg": 80.0, "entry_date": bob_date})

    alice_entries = client.get(
        f"{WE}?user_id={alice_id}&from=2026-01-01&to=2026-12-31"
    ).json()["entries"]
    bob_entries = client.get(
        f"{WE}?user_id={bob_id}&from=2026-01-01&to=2026-12-31"
    ).json()["entries"]

    alice_dates = {e["entry_date"] for e in alice_entries}
    bob_dates = {e["entry_date"] for e in bob_entries}

    assert alice_date in alice_dates
    assert bob_date not in alice_dates
    assert bob_date in bob_dates
    assert alice_date not in bob_dates


# ── AC-9: DELETE removes entry and GET reflects it ───────────────────────────

def test_ac9_delete_then_get_reflects_removal(client, alice_id):
    """AC-9: Deleting an entry causes it to disappear from GET /api/weight-entries."""
    _clean_user_entries(client, alice_id)
    post_res = client.post(
        WE,
        json={"user_id": alice_id, "weight_kg": 68.0, "entry_date": "2026-08-01"},
    )
    assert post_res.status_code == 201
    entry_id = post_res.json()["id"]

    client.delete(f"{WE}/{entry_id}")
    entries = client.get(
        f"{WE}?user_id={alice_id}&from=2026-01-01&to=2026-12-31"
    ).json()["entries"]
    assert all(e["id"] != entry_id for e in entries), "Deleted entry still visible"


# ── AC-10: No localStorage usage (static analysis) ───────────────────────────

def test_ac10_weight_js_no_localstorage():
    """AC-10: weight.js must not reference localStorage, STORAGE_KEY, loadEntries, or saveEntries."""
    import pathlib
    js_path = pathlib.Path(__file__).parent.parent / "frontend" / "js" / "weight.js"
    content = js_path.read_text()
    forbidden = ["localStorage", "STORAGE_KEY", "loadEntries", "saveEntries"]
    for token in forbidden:
        assert token not in content, f"Found forbidden token '{token}' in weight.js"


# ── AC-11: mock-data.js uses entry_date / weight_kg fields ───────────────────

def test_ac11_mock_data_uses_api_field_names():
    """AC-11: MOCK_WEIGHT_ENTRIES in mock-data.js uses entry_date and weight_kg (not the old field name)."""
    import pathlib
    old_field = "recorded" + "_date"
    mock_path = pathlib.Path(__file__).parent.parent / "frontend" / "js" / "mock-data.js"
    content = mock_path.read_text()
    assert "entry_date" in content, "mock-data.js must use 'entry_date' field"
    assert "weight_kg" in content, "mock-data.js must use 'weight_kg' field"
    assert old_field not in content, f"mock-data.js still uses old '{old_field}' field"
    assert "{ date:" not in content, "mock-data.js still uses old 'date' field"
    assert ", weight:" not in content, "mock-data.js still uses old 'weight' field"


# ── AC-12: Non-2xx responses return JSON with error info ─────────────────────

def test_ac12_invalid_user_id_returns_error(client):
    """AC-12: GET /api/weight-entries with invalid user_id returns a non-2xx error."""
    res = client.get(f"{WE}?user_id=not-a-uuid")
    assert res.status_code >= 400, f"Expected error status, got {res.status_code}"


def test_ac12_delete_invalid_id_returns_error(client):
    """AC-12: DELETE with invalid entry_id returns a non-2xx error response."""
    res = client.delete(f"{WE}/not-a-uuid")
    assert res.status_code >= 400, f"Expected error status, got {res.status_code}"
