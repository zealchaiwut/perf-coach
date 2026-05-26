"""
Tests for issue #24: Training tracker — CRUD API for workouts + exercises
Server under test: http://127.0.0.1:9001
"""
import uuid

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
    assert alice is not None, "Alice not found in /api/users"
    return alice["id"]


def _create_workout(client, user_id, *, exercises=None, **kwargs):
    payload = {
        "user_id": user_id,
        "name": kwargs.get("name", "Test Workout"),
        "workout_date": kwargs.get("workout_date", "2026-05-01"),
        "workout_type": kwargs.get("workout_type", "Strength"),
        "remarks": kwargs.get("remarks"),
        "exercises": exercises or [{"name": "Squat", "sets": 3, "reps": 10}],
    }
    res = client.post("/api/workouts", json=payload)
    assert res.status_code == 201, f"Failed to create workout: {res.text}"
    return res.json()


def _delete_workout(client, workout_id):
    client.delete(f"/api/workouts/{workout_id}")


# ── GET /api/workouts ────────────────────────────────────────────────────────

def test_list_workouts_returns_200(client, alice_id):
    res = client.get("/api/workouts", params={"user_id": alice_id, "from": "2026-05-01", "to": "2026-05-31"})
    assert res.status_code == 200


def test_list_workouts_returns_array(client, alice_id):
    res = client.get("/api/workouts", params={"user_id": alice_id, "from": "2026-05-01", "to": "2026-05-31"})
    assert isinstance(res.json(), list)


def test_list_workouts_has_exercise_count(client, alice_id):
    w = _create_workout(client, alice_id, workout_date="2026-05-10",
                        exercises=[{"name": "Bench", "sets": 3}, {"name": "Row", "sets": 3}])
    res = client.get("/api/workouts", params={"user_id": alice_id, "from": "2026-05-01", "to": "2026-05-31"})
    items = res.json()
    match = next((x for x in items if x["id"] == w["id"]), None)
    assert match is not None
    assert match["exercise_count"] == 2
    _delete_workout(client, w["id"])


def test_list_workouts_no_exercises_nested(client, alice_id):
    w = _create_workout(client, alice_id, workout_date="2026-05-11")
    res = client.get("/api/workouts", params={"user_id": alice_id, "from": "2026-05-01", "to": "2026-05-31"})
    items = res.json()
    match = next((x for x in items if x["id"] == w["id"]), None)
    assert match is not None
    assert "exercises" not in match
    _delete_workout(client, w["id"])


def test_list_workouts_date_range_filters(client, alice_id):
    w_in = _create_workout(client, alice_id, workout_date="2026-04-15", name="April Workout")
    w_out = _create_workout(client, alice_id, workout_date="2026-03-01", name="March Workout")
    res = client.get("/api/workouts", params={"user_id": alice_id, "from": "2026-04-01", "to": "2026-04-30"})
    ids = [x["id"] for x in res.json()]
    assert w_in["id"] in ids
    assert w_out["id"] not in ids
    _delete_workout(client, w_in["id"])
    _delete_workout(client, w_out["id"])


def test_list_workouts_response_fields(client, alice_id):
    w = _create_workout(client, alice_id, workout_date="2026-05-12")
    res = client.get("/api/workouts", params={"user_id": alice_id, "from": "2026-05-01", "to": "2026-05-31"})
    match = next((x for x in res.json() if x["id"] == w["id"]), None)
    assert match is not None
    for field in ("id", "workout_date", "name", "workout_type", "remarks", "exercise_count", "created_at"):
        assert field in match, f"Missing field: {field}"
    _delete_workout(client, w["id"])


# ── GET /api/workouts/<id> ───────────────────────────────────────────────────

def test_get_workout_returns_exercises(client, alice_id):
    w = _create_workout(client, alice_id, workout_date="2026-05-13",
                        exercises=[{"name": "Deadlift", "sets": 5, "rpe": 8},
                                   {"name": "Romanian DL", "sets": 3}])
    res = client.get(f"/api/workouts/{w['id']}")
    assert res.status_code == 200
    body = res.json()
    assert "exercises" in body
    assert len(body["exercises"]) == 2
    _delete_workout(client, w["id"])


def test_get_workout_exercises_ordered_by_display_order(client, alice_id):
    w = _create_workout(client, alice_id, workout_date="2026-05-14",
                        exercises=[{"name": "A"}, {"name": "B"}, {"name": "C"}])
    res = client.get(f"/api/workouts/{w['id']}")
    exs = res.json()["exercises"]
    orders = [e["display_order"] for e in exs]
    assert orders == sorted(orders)
    _delete_workout(client, w["id"])


def test_get_workout_404_on_missing(client):
    fake_id = str(uuid.uuid4())
    res = client.get(f"/api/workouts/{fake_id}")
    assert res.status_code == 404


# ── POST /api/workouts (happy path) ─────────────────────────────────────────

def test_create_workout_with_exercises_returns_201(client, alice_id):
    res = client.post("/api/workouts", json={
        "user_id": alice_id,
        "name": "Happy Path",
        "workout_date": "2026-05-02",
        "workout_type": "Strength",
        "exercises": [
            {"name": "Squat", "sets": 4, "reps": 6, "weight_kg": 100},
            {"name": "Press", "sets": 3, "reps": 8},
            {"name": "Row", "sets": 3, "reps": 10, "rpe": 7},
        ],
    })
    assert res.status_code == 201
    body = res.json()
    assert body["name"] == "Happy Path"
    assert len(body["exercises"]) == 3
    _delete_workout(client, body["id"])


def test_create_workout_display_order_by_position(client, alice_id):
    w = _create_workout(client, alice_id, workout_date="2026-05-03",
                        exercises=[{"name": "X"}, {"name": "Y"}, {"name": "Z"}])
    exs = w["exercises"]
    assert exs[0]["display_order"] == 0
    assert exs[1]["display_order"] == 1
    assert exs[2]["display_order"] == 2
    _delete_workout(client, w["id"])


def test_create_workout_empty_exercises_allowed(client, alice_id):
    res = client.post("/api/workouts", json={
        "user_id": alice_id,
        "name": "No exercises yet",
        "workout_date": "2026-05-04",
        "workout_type": "Cardio",
        "exercises": [],
    })
    assert res.status_code == 201
    _delete_workout(client, res.json()["id"])


def test_create_workout_returns_full_object(client, alice_id):
    res = client.post("/api/workouts", json={
        "user_id": alice_id,
        "name": "Full Return",
        "workout_date": "2026-05-05",
        "workout_type": "Mobility",
        "exercises": [{"name": "Stretch", "duration": "10:00"}],
    })
    body = res.json()
    for field in ("id", "user_id", "name", "workout_date", "workout_type", "remarks", "created_at", "exercises"):
        assert field in body, f"Missing field: {field}"
    _delete_workout(client, body["id"])


# ── POST /api/workouts — validation (422) ────────────────────────────────────

def test_create_workout_future_date_returns_422(client, alice_id):
    res = client.post("/api/workouts", json={
        "user_id": alice_id,
        "name": "Future Workout",
        "workout_date": "2030-01-01",
        "workout_type": "Strength",
        "exercises": [],
    })
    assert res.status_code == 422


def test_create_workout_invalid_rpe_returns_422(client, alice_id):
    res = client.post("/api/workouts", json={
        "user_id": alice_id,
        "name": "Bad RPE",
        "workout_date": "2026-05-06",
        "workout_type": "Strength",
        "exercises": [{"name": "Squat", "rpe": 11}],
    })
    assert res.status_code == 422


def test_create_workout_sets_zero_returns_422(client, alice_id):
    res = client.post("/api/workouts", json={
        "user_id": alice_id,
        "name": "Bad sets",
        "workout_date": "2026-05-07",
        "workout_type": "Strength",
        "exercises": [{"name": "Squat", "sets": 0}],
    })
    assert res.status_code == 422


def test_create_workout_missing_name_returns_422(client, alice_id):
    res = client.post("/api/workouts", json={
        "user_id": alice_id,
        "name": "",
        "workout_date": "2026-05-08",
        "workout_type": "Strength",
        "exercises": [],
    })
    assert res.status_code == 422


def test_create_workout_404_unknown_user(client):
    res = client.post("/api/workouts", json={
        "user_id": str(uuid.uuid4()),
        "name": "Ghost User",
        "workout_date": "2026-05-09",
        "workout_type": "Strength",
        "exercises": [],
    })
    assert res.status_code == 404


# ── PATCH /api/workouts/<id> (partial update) ───────────────────────────────

def test_patch_workout_name(client, alice_id):
    w = _create_workout(client, alice_id, workout_date="2026-05-15")
    res = client.patch(f"/api/workouts/{w['id']}", json={"name": "Renamed"})
    assert res.status_code == 200
    assert res.json()["name"] == "Renamed"
    _delete_workout(client, w["id"])


def test_patch_workout_only_updates_specified_fields(client, alice_id):
    w = _create_workout(client, alice_id, workout_date="2026-05-16",
                        exercises=[{"name": "Keep Me"}])
    res = client.patch(f"/api/workouts/{w['id']}", json={"name": "Updated Name Only"})
    body = res.json()
    assert body["name"] == "Updated Name Only"
    assert body["workout_type"] == w["workout_type"]
    assert len(body["exercises"]) == 1
    assert body["exercises"][0]["name"] == "Keep Me"
    _delete_workout(client, w["id"])


def test_patch_workout_does_not_touch_exercises(client, alice_id):
    w = _create_workout(client, alice_id, workout_date="2026-05-17",
                        exercises=[{"name": "Ex1"}, {"name": "Ex2"}])
    client.patch(f"/api/workouts/{w['id']}", json={"remarks": "Updated remarks"})
    res = client.get(f"/api/workouts/{w['id']}")
    assert len(res.json()["exercises"]) == 2
    _delete_workout(client, w["id"])


def test_patch_workout_future_date_returns_422(client, alice_id):
    w = _create_workout(client, alice_id, workout_date="2026-05-18")
    res = client.patch(f"/api/workouts/{w['id']}", json={"workout_date": "2030-06-01"})
    assert res.status_code == 422
    _delete_workout(client, w["id"])


def test_patch_workout_404_on_missing(client):
    res = client.patch(f"/api/workouts/{uuid.uuid4()}", json={"name": "Ghost"})
    assert res.status_code == 404


# ── DELETE /api/workouts/<id> cascade ───────────────────────────────────────

def test_delete_workout_returns_204(client, alice_id):
    w = _create_workout(client, alice_id, workout_date="2026-05-19")
    res = client.delete(f"/api/workouts/{w['id']}")
    assert res.status_code == 204


def test_delete_workout_cascade_exercises(client, alice_id):
    w = _create_workout(client, alice_id, workout_date="2026-05-20",
                        exercises=[{"name": "E1"}, {"name": "E2"}, {"name": "E3"}])
    client.delete(f"/api/workouts/{w['id']}")
    res = client.get(f"/api/workouts/{w['id']}")
    assert res.status_code == 404


def test_delete_workout_404_on_missing(client):
    res = client.delete(f"/api/workouts/{uuid.uuid4()}")
    assert res.status_code == 404


# ── POST /api/workouts/<id>/exercises ────────────────────────────────────────

def test_append_exercise_returns_201(client, alice_id):
    w = _create_workout(client, alice_id, workout_date="2026-05-21",
                        exercises=[{"name": "First"}])
    res = client.post(f"/api/workouts/{w['id']}/exercises",
                      json={"name": "Second", "sets": 3, "reps": 10})
    assert res.status_code == 201
    _delete_workout(client, w["id"])


def test_append_exercise_display_order_is_max_plus_one(client, alice_id):
    w = _create_workout(client, alice_id, workout_date="2026-05-22",
                        exercises=[{"name": "A"}, {"name": "B"}, {"name": "C"}])
    res = client.post(f"/api/workouts/{w['id']}/exercises", json={"name": "D"})
    assert res.json()["display_order"] == 3
    _delete_workout(client, w["id"])


def test_append_exercise_rpe_11_returns_422(client, alice_id):
    w = _create_workout(client, alice_id, workout_date="2026-05-23")
    res = client.post(f"/api/workouts/{w['id']}/exercises",
                      json={"name": "Bad RPE Ex", "rpe": 11})
    assert res.status_code == 422
    _delete_workout(client, w["id"])


def test_append_exercise_404_unknown_workout(client):
    res = client.post(f"/api/workouts/{uuid.uuid4()}/exercises",
                      json={"name": "Ghost"})
    assert res.status_code == 404


# ── PATCH /api/workouts/<workout_id>/exercises/<exercise_id> ─────────────────

def test_patch_exercise_updates_weight(client, alice_id):
    w = _create_workout(client, alice_id, workout_date="2026-05-24",
                        exercises=[{"name": "Bench Press", "sets": 3, "weight_kg": 60.0}])
    ex_id = w["exercises"][0]["id"]
    res = client.patch(f"/api/workouts/{w['id']}/exercises/{ex_id}",
                       json={"weight_kg": 25.0})
    assert res.status_code == 200
    assert res.json()["weight_kg"] == 25.0
    _delete_workout(client, w["id"])


def test_patch_exercise_invalid_rpe_returns_422(client, alice_id):
    w = _create_workout(client, alice_id, workout_date="2026-05-25",
                        exercises=[{"name": "Squat"}])
    ex_id = w["exercises"][0]["id"]
    res = client.patch(f"/api/workouts/{w['id']}/exercises/{ex_id}", json={"rpe": 0})
    assert res.status_code == 422
    _delete_workout(client, w["id"])


def test_patch_exercise_404_wrong_workout(client, alice_id):
    w1 = _create_workout(client, alice_id, workout_date="2026-04-01", exercises=[{"name": "Ex"}])
    w2 = _create_workout(client, alice_id, workout_date="2026-04-02")
    ex_id = w1["exercises"][0]["id"]
    res = client.patch(f"/api/workouts/{w2['id']}/exercises/{ex_id}", json={"name": "Hacked"})
    assert res.status_code == 404
    _delete_workout(client, w1["id"])
    _delete_workout(client, w2["id"])


# ── DELETE /api/workouts/<workout_id>/exercises/<exercise_id> ────────────────

def test_delete_exercise_returns_204(client, alice_id):
    w = _create_workout(client, alice_id, workout_date="2026-04-03",
                        exercises=[{"name": "Remove Me"}, {"name": "Keep Me"}])
    ex_id = w["exercises"][0]["id"]
    res = client.delete(f"/api/workouts/{w['id']}/exercises/{ex_id}")
    assert res.status_code == 204
    _delete_workout(client, w["id"])


def test_delete_exercise_remaining_keep_display_order(client, alice_id):
    w = _create_workout(client, alice_id, workout_date="2026-04-04",
                        exercises=[{"name": "A"}, {"name": "B"}, {"name": "C"}])
    ex_b_id = w["exercises"][1]["id"]
    client.delete(f"/api/workouts/{w['id']}/exercises/{ex_b_id}")
    res = client.get(f"/api/workouts/{w['id']}")
    remaining = res.json()["exercises"]
    assert len(remaining) == 2
    names = [e["name"] for e in remaining]
    assert "B" not in names
    assert "A" in names and "C" in names
    _delete_workout(client, w["id"])


def test_delete_exercise_404_unknown(client, alice_id):
    w = _create_workout(client, alice_id, workout_date="2026-04-05")
    res = client.delete(f"/api/workouts/{w['id']}/exercises/{uuid.uuid4()}")
    assert res.status_code == 404
    _delete_workout(client, w["id"])


# ── POST /api/workouts/<id>/exercises/reorder ────────────────────────────────

def test_reorder_exercises(client, alice_id):
    w = _create_workout(client, alice_id, workout_date="2026-04-06",
                        exercises=[{"name": "First"}, {"name": "Second"}, {"name": "Third"}])
    ids = [e["id"] for e in w["exercises"]]
    reversed_ids = list(reversed(ids))
    res = client.post(f"/api/workouts/{w['id']}/exercises/reorder",
                      json={"ordered_ids": reversed_ids})
    assert res.status_code == 200
    exs = res.json()["exercises"]
    assert exs[0]["id"] == reversed_ids[0]
    assert exs[1]["id"] == reversed_ids[1]
    assert exs[2]["id"] == reversed_ids[2]
    _delete_workout(client, w["id"])


def test_reorder_subsequent_get_reflects_new_order(client, alice_id):
    w = _create_workout(client, alice_id, workout_date="2026-04-07",
                        exercises=[{"name": "Alpha"}, {"name": "Beta"}, {"name": "Gamma"}])
    ids = [e["id"] for e in w["exercises"]]
    new_order = [ids[2], ids[0], ids[1]]
    client.post(f"/api/workouts/{w['id']}/exercises/reorder",
                json={"ordered_ids": new_order})
    res = client.get(f"/api/workouts/{w['id']}")
    exs = res.json()["exercises"]
    assert exs[0]["name"] == "Gamma"
    assert exs[1]["name"] == "Alpha"
    assert exs[2]["name"] == "Beta"
    _delete_workout(client, w["id"])


def test_reorder_404_unknown_exercise_id(client, alice_id):
    w = _create_workout(client, alice_id, workout_date="2026-04-08",
                        exercises=[{"name": "Only"}])
    res = client.post(f"/api/workouts/{w['id']}/exercises/reorder",
                      json={"ordered_ids": [str(uuid.uuid4())]})
    assert res.status_code == 404
    _delete_workout(client, w["id"])
