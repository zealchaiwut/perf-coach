"""
Tests for issue #22: Training tracker — DB schema with workouts + workout_exercises
Verifies acceptance criteria via the UAT API at http://127.0.0.1:9001.
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
    assert alice is not None, "Alice not found — seed not run?"
    return alice["id"]


def _create_workout(client, user_id, **kwargs):
    payload = {
        "user_id": user_id,
        "name": kwargs.get("name", "Schema Test Workout"),
        "workout_date": kwargs.get("workout_date", "2026-01-15"),
        "workout_type": kwargs.get("workout_type", "strength"),
        "remarks": kwargs.get("remarks"),
        "exercises": kwargs.get("exercises", []),
    }
    res = client.post("/api/workouts", json=payload)
    assert res.status_code == 201, f"Create workout failed: {res.text}"
    return res.json()


def _cleanup(client, workout_id):
    client.delete(f"/api/workouts/{workout_id}")


# ── AC-1 / Step 1: workouts table exists ─────────────────────────────────────

def test_workouts_table_exists(client, alice_id):
    """GET /api/workouts returns 200 — confirms workouts table was created."""
    res = client.get("/api/workouts", params={
        "user_id": alice_id, "from": "2026-01-01", "to": "2026-12-31"
    })
    assert res.status_code == 200


def test_workouts_response_is_list(client, alice_id):
    res = client.get("/api/workouts", params={
        "user_id": alice_id, "from": "2026-01-01", "to": "2026-12-31"
    })
    assert isinstance(res.json(), list)


# ── AC-2: workouts table columns ──────────────────────────────────────────────

def test_workouts_all_required_columns_returned(client, alice_id):
    """Workout response includes all schema-defined columns."""
    w = _create_workout(client, alice_id,
                        name="Column Check", workout_date="2026-01-10",
                        workout_type="running", remarks="test remark")
    try:
        res = client.get("/api/workouts", params={
            "user_id": alice_id, "from": "2026-01-01", "to": "2026-01-31"
        })
        match = next((x for x in res.json() if x["id"] == w["id"]), None)
        assert match is not None
        for field in ("id", "user_id", "workout_date", "name", "workout_type",
                      "remarks", "created_at"):
            assert field in match, f"Missing field: {field}"
        assert match["workout_type"] == "running"
        assert match["remarks"] == "test remark"
    finally:
        _cleanup(client, w["id"])


def test_workout_user_fk_enforced(client):
    """Workout with unknown user_id returns 404 — FK to users.id works."""
    res = client.post("/api/workouts", json={
        "user_id": str(uuid.uuid4()),
        "name": "Ghost",
        "workout_date": "2026-01-10",
        "workout_type": "strength",
        "exercises": [],
    })
    assert res.status_code == 404


# ── AC-3: workout_exercises table columns ─────────────────────────────────────

def test_workout_exercises_table_exists_and_all_columns(client, alice_id):
    """Exercise response includes all schema columns."""
    w = _create_workout(client, alice_id,
                        workout_date="2026-01-11",
                        exercises=[{
                            "name": "Squat",
                            "sets": 4,
                            "reps": "10,8,6",
                            "weight": "BB 100kg",
                            "duration": None,
                            "rpe": 8,
                        }])
    try:
        res = client.get(f"/api/workouts/{w['id']}")
        assert res.status_code == 200
        exs = res.json().get("exercises", [])
        assert len(exs) == 1
        ex = exs[0]
        for field in ("id", "workout_id", "display_order", "name", "sets",
                      "reps", "weight", "rpe", "created_at"):
            assert field in ex, f"Missing exercise field: {field}"
        assert ex["sets"] == 4
        assert ex["reps"] == "10,8,6"
        assert ex["weight"] == "BB 100kg"
        assert ex["rpe"] == 8
    finally:
        _cleanup(client, w["id"])


def test_exercise_free_text_reps_accepted(client, alice_id):
    """Reps accepts free-text values like 'AMRAP'."""
    w = _create_workout(client, alice_id,
                        workout_date="2026-01-12",
                        exercises=[{"name": "Push-up", "reps": "AMRAP"}])
    try:
        res = client.get(f"/api/workouts/{w['id']}")
        ex = res.json()["exercises"][0]
        assert ex["reps"] == "AMRAP"
    finally:
        _cleanup(client, w["id"])


def test_exercise_free_text_weight_accepted(client, alice_id):
    """Weight accepts free-text values like 'DB 12kg' and 'BW'."""
    w = _create_workout(client, alice_id,
                        workout_date="2026-01-13",
                        exercises=[{"name": "Pull-up", "weight": "BW+10kg"}])
    try:
        res = client.get(f"/api/workouts/{w['id']}")
        ex = res.json()["exercises"][0]
        assert ex["weight"] == "BW+10kg"
    finally:
        _cleanup(client, w["id"])


def test_exercise_duration_free_text_accepted(client, alice_id):
    """Duration accepts free-text values like '5km in 28:00'."""
    w = _create_workout(client, alice_id,
                        workout_date="2026-01-14",
                        workout_type="running",
                        exercises=[{"name": "5k Run", "duration": "5km in 28:00"}])
    try:
        res = client.get(f"/api/workouts/{w['id']}")
        ex = res.json()["exercises"][0]
        assert ex.get("duration") == "5km in 28:00"
    finally:
        _cleanup(client, w["id"])


# ── AC-5 / Step 4: sets CHECK constraint ─────────────────────────────────────

def test_sets_zero_rejected(client, alice_id):
    """sets = 0 violates CHECK constraint — returns 422."""
    res = client.post("/api/workouts", json={
        "user_id": alice_id,
        "name": "Bad Sets",
        "workout_date": "2026-01-15",
        "workout_type": "strength",
        "exercises": [{"name": "Squat", "sets": 0}],
    })
    assert res.status_code == 422


def test_sets_negative_rejected(client, alice_id):
    """sets = -1 violates CHECK constraint — returns 422."""
    res = client.post("/api/workouts", json={
        "user_id": alice_id,
        "name": "Negative Sets",
        "workout_date": "2026-01-15",
        "workout_type": "strength",
        "exercises": [{"name": "Deadlift", "sets": -1}],
    })
    assert res.status_code == 422


def test_sets_null_allowed(client, alice_id):
    """sets = null (omitted) is allowed — nullable column."""
    w = _create_workout(client, alice_id,
                        workout_date="2026-01-16",
                        exercises=[{"name": "Run", "duration": "30 min"}])
    try:
        res = client.get(f"/api/workouts/{w['id']}")
        ex = res.json()["exercises"][0]
        assert ex["sets"] is None
    finally:
        _cleanup(client, w["id"])


def test_sets_positive_allowed(client, alice_id):
    """sets = 1 (minimum positive) is accepted."""
    w = _create_workout(client, alice_id,
                        workout_date="2026-01-17",
                        exercises=[{"name": "Squat", "sets": 1}])
    try:
        res = client.get(f"/api/workouts/{w['id']}")
        assert res.json()["exercises"][0]["sets"] == 1
    finally:
        _cleanup(client, w["id"])


# ── AC-5 / Step 5: rpe CHECK constraint ──────────────────────────────────────

def test_rpe_above_10_rejected(client, alice_id):
    """rpe = 11 violates CHECK constraint — returns 422."""
    res = client.post("/api/workouts", json={
        "user_id": alice_id,
        "name": "Bad RPE",
        "workout_date": "2026-01-18",
        "workout_type": "strength",
        "exercises": [{"name": "Squat", "rpe": 11}],
    })
    assert res.status_code == 422


def test_rpe_15_rejected(client, alice_id):
    """rpe = 15 violates CHECK constraint — returns 422 (from UAT test step 5)."""
    res = client.post("/api/workouts", json={
        "user_id": alice_id,
        "name": "Bad RPE 15",
        "workout_date": "2026-01-18",
        "workout_type": "strength",
        "exercises": [{"name": "Row", "rpe": 15}],
    })
    assert res.status_code == 422


def test_rpe_zero_rejected(client, alice_id):
    """rpe = 0 violates CHECK constraint (must be >= 1) — returns 422."""
    res = client.post("/api/workouts", json={
        "user_id": alice_id,
        "name": "RPE zero",
        "workout_date": "2026-01-18",
        "workout_type": "strength",
        "exercises": [{"name": "Press", "rpe": 0}],
    })
    assert res.status_code == 422


def test_rpe_boundary_values_accepted(client, alice_id):
    """rpe = 1 and rpe = 10 are both valid boundary values."""
    w = _create_workout(client, alice_id,
                        workout_date="2026-01-19",
                        exercises=[
                            {"name": "Easy jog", "rpe": 1},
                            {"name": "All-out sprint", "rpe": 10},
                        ])
    try:
        res = client.get(f"/api/workouts/{w['id']}")
        rpes = {e["name"]: e["rpe"] for e in res.json()["exercises"]}
        assert rpes["Easy jog"] == 1
        assert rpes["All-out sprint"] == 10
    finally:
        _cleanup(client, w["id"])


def test_rpe_null_allowed(client, alice_id):
    """rpe = null (omitted) is allowed — nullable column."""
    w = _create_workout(client, alice_id,
                        workout_date="2026-01-20",
                        exercises=[{"name": "Plank"}])
    try:
        res = client.get(f"/api/workouts/{w['id']}")
        ex = res.json()["exercises"][0]
        assert ex["rpe"] is None
    finally:
        _cleanup(client, w["id"])


# ── AC / Step 6: ON DELETE CASCADE workouts → workout_exercises ───────────────

def test_delete_workout_cascades_to_exercises(client, alice_id):
    """Deleting a workout removes all its exercises (ON DELETE CASCADE)."""
    w = _create_workout(client, alice_id,
                        workout_date="2026-01-21",
                        exercises=[
                            {"name": "E1"},
                            {"name": "E2"},
                            {"name": "E3"},
                        ])
    wid = w["id"]
    res_before = client.get(f"/api/workouts/{wid}")
    assert len(res_before.json()["exercises"]) == 3

    client.delete(f"/api/workouts/{wid}")
    res_after = client.get(f"/api/workouts/{wid}")
    assert res_after.status_code == 404


# ── AC: display_order tracks insert position ──────────────────────────────────

def test_exercises_display_order_is_sequential(client, alice_id):
    """Exercises inserted in order receive sequential display_order values."""
    w = _create_workout(client, alice_id,
                        workout_date="2026-01-22",
                        exercises=[{"name": "A"}, {"name": "B"}, {"name": "C"}])
    try:
        exs = w["exercises"]
        assert exs[0]["display_order"] == 0
        assert exs[1]["display_order"] == 1
        assert exs[2]["display_order"] == 2
    finally:
        _cleanup(client, w["id"])


# ── AC: workouts indexed by user_id + workout_date ────────────────────────────

def test_workouts_filtered_by_user_and_date_range(client, alice_id):
    """Date-range filter works correctly — exercises index on workout_date."""
    w_in  = _create_workout(client, alice_id, name="In Range",  workout_date="2026-02-15")
    w_out = _create_workout(client, alice_id, name="Out Range", workout_date="2026-03-01")
    try:
        res = client.get("/api/workouts", params={
            "user_id": alice_id, "from": "2026-02-01", "to": "2026-02-28"
        })
        ids = [x["id"] for x in res.json()]
        assert w_in["id"] in ids
        assert w_out["id"] not in ids
    finally:
        _cleanup(client, w_in["id"])
        _cleanup(client, w_out["id"])


# ── AC / Step 3: exercise_count query ─────────────────────────────────────────

def test_workout_list_includes_exercise_count(client, alice_id):
    """List endpoint includes correct exercise_count per workout."""
    w = _create_workout(client, alice_id,
                        workout_date="2026-02-10",
                        exercises=[{"name": "X"}, {"name": "Y"}, {"name": "Z"}])
    try:
        res = client.get("/api/workouts", params={
            "user_id": alice_id, "from": "2026-02-01", "to": "2026-02-28"
        })
        match = next((x for x in res.json() if x["id"] == w["id"]), None)
        assert match is not None
        assert match["exercise_count"] == 3
    finally:
        _cleanup(client, w["id"])


# ── AC / Step 2: seed data ────────────────────────────────────────────────────

def test_alice_has_three_seeded_workouts(client, alice_id):
    """Alice has at least 3 workouts covering the last 14 days (seed check)."""
    import datetime
    today = datetime.date.today()
    from_date = str(today - datetime.timedelta(days=14))
    res = client.get("/api/workouts", params={
        "user_id": alice_id, "from": from_date, "to": str(today)
    })
    workouts = res.json()
    assert len(workouts) >= 3, (
        f"Expected ≥3 seeded workouts for Alice in last 14 days, got {len(workouts)}. "
        "Run `python backend/seed.py` on UAT to populate seed data."
    )


def test_seeded_workouts_have_exercises(client, alice_id):
    """Seeded workouts have exercise rows (exercise_count > 0 for strength workouts)."""
    import datetime
    today = datetime.date.today()
    from_date = str(today - datetime.timedelta(days=14))
    res = client.get("/api/workouts", params={
        "user_id": alice_id, "from": from_date, "to": str(today)
    })
    strength = [w for w in res.json() if w.get("workout_type") == "strength"]
    assert any(w["exercise_count"] > 0 for w in strength), (
        "Expected at least one strength workout with exercise rows"
    )
