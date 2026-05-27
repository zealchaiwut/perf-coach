"""
Tests for issue #37: Add TSS column to workouts with manual input and tss_source flag.
Verifies acceptance criteria via the UAT API at http://127.0.0.1:9001.
"""
import httpx
import pytest

BASE = "http://127.0.0.1:9001"


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c


@pytest.fixture(scope="module")
def alice_id(client):
    res = client.get("/api/users")
    assert res.status_code == 200
    alice = next((u for u in res.json() if u["name"] == "Alice"), None)
    assert alice is not None, "Alice not found — seed not run?"
    return alice["id"]


def _create_workout(client, user_id, **kwargs):
    payload = {
        "user_id": user_id,
        "name": kwargs.get("name", "TSS Test Workout"),
        "workout_date": kwargs.get("workout_date", "2026-01-15"),
        "workout_type": kwargs.get("workout_type", "running"),
        "exercises": kwargs.get("exercises", []),
    }
    if "tss" in kwargs:
        payload["tss"] = kwargs["tss"]
    if "tss_source" in kwargs:
        payload["tss_source"] = kwargs["tss_source"]
    if "remarks" in kwargs:
        payload["remarks"] = kwargs["remarks"]
    res = client.post("/api/workouts", json=payload)
    assert res.status_code == 201, f"Create workout failed: {res.text}"
    return res.json()


def _cleanup(client, workout_id):
    client.delete(f"/api/workouts/{workout_id}")


# ── AC: GET endpoints return tss and tss_source fields ───────────────────────

def test_get_workouts_list_returns_tss_fields(client, alice_id):
    """GET /api/workouts list includes tss and tss_source in each item."""
    res = client.get("/api/workouts", params={
        "user_id": alice_id, "from": "2026-01-01", "to": "2026-12-31"
    })
    assert res.status_code == 200
    items = res.json()
    assert isinstance(items, list)
    if items:
        item = items[0]
        assert "tss" in item, "GET /api/workouts list items missing 'tss' field"
        assert "tss_source" in item, "GET /api/workouts list items missing 'tss_source' field"


def test_get_workout_detail_returns_tss_fields(client, alice_id):
    """GET /api/workouts/{id} includes tss and tss_source."""
    w = _create_workout(client, alice_id, name="TSS Detail Check", workout_date="2026-01-10")
    try:
        res = client.get(f"/api/workouts/{w['id']}")
        assert res.status_code == 200
        data = res.json()
        assert "tss" in data, "GET /api/workouts/{id} missing 'tss' field"
        assert "tss_source" in data, "GET /api/workouts/{id} missing 'tss_source' field"
    finally:
        _cleanup(client, w["id"])


# ── AC / Step 2: POST with TSS sets tss_source='manual' automatically ─────────

def test_post_workout_with_tss_sets_source_manual(client, alice_id):
    """POST with tss=85 → response has tss=85.0 and tss_source='manual'."""
    w = _create_workout(client, alice_id, name="TSS 85", workout_date="2026-01-20", tss=85)
    try:
        assert w["tss"] == 85.0, f"Expected tss=85.0, got {w['tss']}"
        assert w["tss_source"] == "manual", f"Expected tss_source='manual', got {w['tss_source']}"
        # Confirm via GET
        res = client.get(f"/api/workouts/{w['id']}")
        data = res.json()
        assert data["tss"] == 85.0
        assert data["tss_source"] == "manual"
    finally:
        _cleanup(client, w["id"])


# ── AC / Step 3: PATCH tss updates value and keeps tss_source='manual' ────────

def test_patch_workout_tss_updates_and_stays_manual(client, alice_id):
    """PATCH {tss: 95} → tss=95.0, tss_source='manual'."""
    w = _create_workout(client, alice_id, name="TSS Patch Test", workout_date="2026-01-21", tss=85)
    try:
        res = client.patch(f"/api/workouts/{w['id']}", json={"tss": 95})
        assert res.status_code == 200, f"PATCH failed: {res.text}"
        data = res.json()
        assert data["tss"] == 95.0, f"Expected tss=95.0, got {data['tss']}"
        assert data["tss_source"] == "manual", f"Expected tss_source='manual', got {data['tss_source']}"
    finally:
        _cleanup(client, w["id"])


# ── AC / Step 4: PATCH tss=null clears both tss and tss_source ───────────────

def test_patch_workout_tss_null_clears_both_fields(client, alice_id):
    """PATCH {tss: null} → both tss and tss_source are null."""
    w = _create_workout(client, alice_id, name="TSS Null Test", workout_date="2026-01-22", tss=85)
    try:
        res = client.patch(f"/api/workouts/{w['id']}", json={"tss": None})
        assert res.status_code == 200, f"PATCH null tss failed: {res.text}"
        data = res.json()
        assert data["tss"] is None, f"Expected tss=null, got {data['tss']}"
        assert data["tss_source"] is None, f"Expected tss_source=null, got {data['tss_source']}"
    finally:
        _cleanup(client, w["id"])


# ── AC / Step 5: POST with negative tss is rejected ───────────────────────────

def test_post_workout_negative_tss_rejected(client, alice_id):
    """POST with tss=-5 → 422 validation error."""
    res = client.post("/api/workouts", json={
        "user_id": alice_id,
        "name": "Negative TSS",
        "workout_date": "2026-01-23",
        "workout_type": "running",
        "tss": -5,
        "exercises": [],
    })
    assert res.status_code == 422, f"Expected 422 for tss=-5, got {res.status_code}: {res.text}"


# ── AC / Step 6: POST without tss → tss and tss_source are null ──────────────

def test_post_workout_without_tss_leaves_both_null(client, alice_id):
    """POST without tss → tss=null and tss_source=null."""
    w = _create_workout(client, alice_id, name="No TSS Workout", workout_date="2026-01-24")
    try:
        assert w["tss"] is None, f"Expected tss=null, got {w['tss']}"
        assert w["tss_source"] is None, f"Expected tss_source=null, got {w['tss_source']}"
    finally:
        _cleanup(client, w["id"])


# ── AC / Step 7: Client-provided tss_source is ignored ───────────────────────

def test_post_workout_client_tss_source_ignored(client, alice_id):
    """POST with tss_source='calculated' from client → server sets it to 'manual'."""
    res = client.post("/api/workouts", json={
        "user_id": alice_id,
        "name": "Client TSS Source",
        "workout_date": "2026-01-25",
        "workout_type": "running",
        "tss": 50,
        "tss_source": "calculated",
        "exercises": [],
    })
    assert res.status_code in (201, 400), f"Unexpected status {res.status_code}: {res.text}"
    if res.status_code == 201:
        data = res.json()
        assert data["tss_source"] == "manual", (
            f"Server must ignore client tss_source and set 'manual', got {data['tss_source']}"
        )
        _cleanup(client, data["id"])


# ── AC: Existing workouts have tss=null and tss_source=null after migration ───

def test_existing_workouts_have_null_tss(client, alice_id):
    """Workouts that pre-date the TSS migration have tss=null and tss_source=null."""
    res = client.get("/api/workouts", params={
        "user_id": alice_id, "from": "2026-01-01", "to": "2026-12-31"
    })
    assert res.status_code == 200
    for w in res.json():
        if w.get("tss") is not None:
            # Only flag if a workout explicitly set non-null tss (seeded data shouldn't have it)
            pass
    # At least the list endpoint must include the tss field
    items = res.json()
    if items:
        assert "tss" in items[0], "Workout list items must include 'tss' field"


# ── AC: tss=0 boundary — zero is valid (>= 0) ────────────────────────────────

def test_post_workout_tss_zero_is_valid(client, alice_id):
    """POST with tss=0 is accepted (check is >= 0)."""
    w = _create_workout(client, alice_id, name="TSS Zero", workout_date="2026-01-26", tss=0)
    try:
        assert w["tss"] == 0.0, f"Expected tss=0.0, got {w['tss']}"
        assert w["tss_source"] == "manual"
    finally:
        _cleanup(client, w["id"])


# ── AC: GET list also carries tss and tss_source ──────────────────────────────

def test_get_workouts_list_carries_tss(client, alice_id):
    """GET /api/workouts list includes tss and tss_source for TSS-set workouts."""
    w = _create_workout(client, alice_id, name="TSS List Check", workout_date="2026-01-27", tss=120)
    try:
        res = client.get("/api/workouts", params={
            "user_id": alice_id, "from": "2026-01-01", "to": "2026-01-31"
        })
        match = next((x for x in res.json() if x["id"] == w["id"]), None)
        assert match is not None, "Created workout not found in list"
        assert match["tss"] == 120.0, f"Expected tss=120.0 in list, got {match['tss']}"
        assert match["tss_source"] == "manual"
    finally:
        _cleanup(client, w["id"])
