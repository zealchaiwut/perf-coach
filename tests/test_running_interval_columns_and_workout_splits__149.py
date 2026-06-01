"""
Acceptance tests for issue #149: Add running interval columns and workout_splits table
Runs against UAT environment
"""
import os
import httpx
import pytest

BASE = os.environ.get("UAT_BASE_URL") or f"http://localhost:{os.environ.get('UAT_PORT', '9001')}"
if not BASE.startswith("http"):
    raise RuntimeError(
        "UAT_BASE_URL / UAT_PORT not set. Run the tester skill's Step 0 to resolve UAT before pytest."
    )


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


@pytest.fixture
def workout(client, alice_id):
    res = client.post("/api/workouts", json={
        "user_id": alice_id,
        "name": "Issue 149 Test",
        "workout_date": "2026-05-29",
        "workout_type": "run",
    })
    assert res.status_code == 201
    data = res.json()
    yield data
    client.delete(f"/api/workouts/{data['id']}")


# ── UAT Step 2: POST exercise with interval fields returns correct values ──────

def test_post_exercise_with_interval_fields(client, workout):
    res = client.post(f"/api/workouts/{workout['id']}/exercises", json={
        "name": "Rep 1",
        "distance_km": 0.8,
        "duration_seconds": 182,
        "avg_hr": 172,
    })
    assert res.status_code == 201
    body = res.json()
    assert body["distance_km"] == "0.800"
    assert body["duration_seconds"] == 182
    assert body["avg_hr"] == 172


# ── UAT Step 3: GET exercise round-trips interval fields ──────────────────────

def test_get_exercise_returns_interval_fields(client, workout):
    post_res = client.post(f"/api/workouts/{workout['id']}/exercises", json={
        "name": "Rep 1",
        "distance_km": 0.8,
        "duration_seconds": 182,
        "avg_hr": 172,
    })
    assert post_res.status_code == 201
    ex_id = post_res.json()["id"]

    get_res = client.get(f"/api/workouts/{workout['id']}")
    assert get_res.status_code == 200
    exercises = get_res.json()["exercises"]
    ex = next((e for e in exercises if e["id"] == ex_id), None)
    assert ex is not None
    assert ex["distance_km"] == "0.800"
    assert ex["duration_seconds"] == 182
    assert ex["avg_hr"] == 172


# ── UAT Step 4: Strength exercise without interval fields has null values ──────

def test_post_strength_exercise_without_interval_fields(client, workout):
    res = client.post(f"/api/workouts/{workout['id']}/exercises", json={
        "name": "Back Squat",
        "sets": 3,
        "reps": 5,
    })
    assert res.status_code == 201
    body = res.json()
    assert body["distance_km"] is None
    assert body["duration_seconds"] is None
    assert body["avg_hr"] is None


# ── UAT Step 5: avg_hr: 300 returns 422 ──────────────────────────────────────

def test_post_exercise_avg_hr_too_high_returns_422(client, workout):
    res = client.post(f"/api/workouts/{workout['id']}/exercises", json={
        "name": "Bad Rep",
        "avg_hr": 300,
    })
    assert res.status_code == 422
    assert "avg_hr" in res.text


def test_post_exercise_negative_distance_returns_422(client, workout):
    res = client.post(f"/api/workouts/{workout['id']}/exercises", json={
        "name": "Bad Rep",
        "distance_km": -1.0,
    })
    assert res.status_code == 422
    assert "distance_km" in res.text


def test_post_exercise_negative_duration_returns_422(client, workout):
    res = client.post(f"/api/workouts/{workout['id']}/exercises", json={
        "name": "Bad Rep",
        "duration_seconds": -5,
    })
    assert res.status_code == 422
    assert "duration_seconds" in res.text


def test_post_exercise_avg_hr_too_low_returns_422(client, workout):
    res = client.post(f"/api/workouts/{workout['id']}/exercises", json={
        "name": "Bad Rep",
        "avg_hr": 19,
    })
    assert res.status_code == 422
    assert "avg_hr" in res.text


# ── PATCH exercise persists interval fields ───────────────────────────────────

def test_patch_exercise_updates_interval_fields(client, workout):
    post_res = client.post(f"/api/workouts/{workout['id']}/exercises", json={
        "name": "Rep 1",
    })
    assert post_res.status_code == 201
    ex_id = post_res.json()["id"]

    patch_res = client.patch(f"/api/workouts/{workout['id']}/exercises/{ex_id}", json={
        "distance_km": 1.5,
        "duration_seconds": 300,
        "avg_hr": 160,
    })
    assert patch_res.status_code == 200
    body = patch_res.json()
    assert body["distance_km"] == "1.500"
    assert body["duration_seconds"] == 300
    assert body["avg_hr"] == 160


# ── UAT Step 6: POST splits returns 201 with all splits ──────────────────────

def test_post_splits_creates_splits(client, workout):
    splits = [
        {"split_index": i, "distance_km": 1.0, "duration_seconds": 300, "avg_hr": 165}
        for i in range(1, 7)
    ]
    res = client.post(f"/api/workouts/{workout['id']}/splits", json={"splits": splits})
    assert res.status_code == 201
    body = res.json()
    assert len(body) == 6


# ── UAT Step 7: GET splits returns ordered splits ────────────────────────────

def test_get_splits_returns_ordered(client, workout):
    splits = [
        {"split_index": i, "distance_km": 1.0, "duration_seconds": 300, "avg_hr": 165}
        for i in range(1, 7)
    ]
    client.post(f"/api/workouts/{workout['id']}/splits", json={"splits": splits})
    res = client.get(f"/api/workouts/{workout['id']}/splits")
    assert res.status_code == 200
    body = res.json()
    assert len(body) == 6
    assert [s["split_index"] for s in body] == list(range(1, 7))


# ── UAT Step 8: POST splits again replaces all previous splits ───────────────

def test_post_splits_replaces_all(client, workout):
    splits_6 = [
        {"split_index": i, "distance_km": 1.0, "duration_seconds": 300, "avg_hr": 165}
        for i in range(1, 7)
    ]
    client.post(f"/api/workouts/{workout['id']}/splits", json={"splits": splits_6})

    splits_3 = [
        {"split_index": i, "distance_km": 2.0, "duration_seconds": 600}
        for i in range(1, 4)
    ]
    res = client.post(f"/api/workouts/{workout['id']}/splits", json={"splits": splits_3})
    assert res.status_code == 201
    assert len(res.json()) == 3

    get_res = client.get(f"/api/workouts/{workout['id']}/splits")
    assert len(get_res.json()) == 3


# ── UAT Step 9: DELETE splits removes all splits ─────────────────────────────

def test_delete_splits_removes_all(client, workout):
    splits = [{"split_index": 1, "distance_km": 1.0, "duration_seconds": 300}]
    client.post(f"/api/workouts/{workout['id']}/splits", json={"splits": splits})

    del_res = client.delete(f"/api/workouts/{workout['id']}/splits")
    assert del_res.status_code == 204

    get_res = client.get(f"/api/workouts/{workout['id']}/splits")
    assert get_res.status_code == 200
    assert get_res.json() == []


# ── UAT Step 10: Deleting workout cascades to splits ─────────────────────────

def test_delete_workout_cascades_to_splits(client, alice_id):
    w_res = client.post("/api/workouts", json={
        "user_id": alice_id,
        "name": "Cascade Test",
        "workout_date": "2026-05-29",
        "workout_type": "run",
    })
    assert w_res.status_code == 201
    wid = w_res.json()["id"]

    splits = [{"split_index": 1, "distance_km": 1.0, "duration_seconds": 300}]
    client.post(f"/api/workouts/{wid}/splits", json={"splits": splits})

    del_res = client.delete(f"/api/workouts/{wid}")
    assert del_res.status_code == 204

    # Splits gone — workout is deleted so 404 expected
    get_res = client.get(f"/api/workouts/{wid}/splits")
    assert get_res.status_code == 404


# ── GET splits on empty workout returns empty array ───────────────────────────

def test_get_splits_empty(client, workout):
    res = client.get(f"/api/workouts/{workout['id']}/splits")
    assert res.status_code == 200
    assert res.json() == []
