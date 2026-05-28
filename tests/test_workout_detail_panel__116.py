"""Tests for issue #116: Exercise breakdown and notes in Training Log detail panel

Verifies the API contract the detail panel depends on:
- GET /api/workouts/{id} returns exercises ordered by display_order for lift workouts
- exercises array includes name, sets, reps, weight_kg, rpe, display_order
- remarks field is present and correctly returned
- Empty exercises array and null remarks are returned when not provided
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
    assert alice is not None, "Alice not found — seed the DB first"
    return alice["id"]


def _create_lift(client, user_id, exercises=None, remarks=None):
    payload = {
        "user_id": user_id,
        "name": "Test Lift",
        "workout_date": "2026-01-15",
        "workout_type": "lift",
        "exercises": exercises or [],
    }
    if remarks is not None:
        payload["remarks"] = remarks
    res = client.post("/api/workouts", json=payload)
    assert res.status_code == 201, f"create failed: {res.text}"
    return res.json()


def _delete(client, workout_id):
    client.delete(f"/api/workouts/{workout_id}")


# ── AC1 / AC2 / AC3: exercise breakdown for lift with exercises ───────────────

def test_lift_with_exercises_returns_sorted_breakdown(client, alice_id):
    exercises = [
        {"name": "Deadlift", "sets": 3, "reps": 5, "weight_kg": 120.0, "rpe": 8, "display_order": 1},
        {"name": "Squat",    "sets": 4, "reps": 5, "weight_kg": 100.0, "rpe": 7, "display_order": 0},
    ]
    w = _create_lift(client, alice_id, exercises=exercises, remarks="Heavy day")
    try:
        res = client.get(f"/api/workouts/{w['id']}")
        assert res.status_code == 200
        data = res.json()

        exs = data["exercises"]
        assert len(exs) == 2

        # AC3: ordered by display_order ascending
        assert exs[0]["name"] == "Squat"
        assert exs[1]["name"] == "Deadlift"

        # AC2: each exercise row fields
        squat = exs[0]
        assert squat["sets"] == 4
        assert squat["reps"] == 5
        assert squat["weight_kg"] == pytest.approx(100.0)
        assert squat["rpe"] == 7

        dead = exs[1]
        assert dead["sets"] == 3
        assert dead["reps"] == 5
        assert dead["weight_kg"] == pytest.approx(120.0)
        assert dead["rpe"] == 8
    finally:
        _delete(client, w["id"])


# ── AC3: display_order is preserved in the response ──────────────────────────

def test_exercises_carry_display_order(client, alice_id):
    exercises = [
        {"name": "Press",  "sets": 3, "reps": 8, "display_order": 2},
        {"name": "Row",    "sets": 3, "reps": 8, "display_order": 0},
        {"name": "Pullup", "sets": 3, "reps": 6, "display_order": 1},
    ]
    w = _create_lift(client, alice_id, exercises=exercises)
    try:
        res = client.get(f"/api/workouts/{w['id']}")
        assert res.status_code == 200
        exs = res.json()["exercises"]
        names = [e["name"] for e in exs]
        assert names == ["Row", "Pullup", "Press"]
    finally:
        _delete(client, w["id"])


# ── AC4 / AC5: lift with no exercises → empty array ──────────────────────────

def test_lift_without_exercises_returns_empty_array(client, alice_id):
    w = _create_lift(client, alice_id, exercises=[], remarks="Just cardio warmup")
    try:
        res = client.get(f"/api/workouts/{w['id']}")
        assert res.status_code == 200
        data = res.json()
        assert data["exercises"] == []
        # remarks still present
        assert data["remarks"] == "Just cardio warmup"
    finally:
        _delete(client, w["id"])


# ── AC3 (notes): remarks field round-trips correctly ─────────────────────────

def test_remarks_field_round_trips(client, alice_id):
    notes = "Felt strong today. PR on deadlift."
    w = _create_lift(client, alice_id, remarks=notes)
    try:
        res = client.get(f"/api/workouts/{w['id']}")
        assert res.status_code == 200
        assert res.json()["remarks"] == notes
    finally:
        _delete(client, w["id"])


# ── AC6 / AC7: workout with no remarks → null ────────────────────────────────

def test_workout_without_remarks_returns_null(client, alice_id):
    w = _create_lift(client, alice_id, exercises=[], remarks=None)
    try:
        res = client.get(f"/api/workouts/{w['id']}")
        assert res.status_code == 200
        assert res.json()["remarks"] is None
    finally:
        _delete(client, w["id"])


# ── AC7: workout with neither exercises nor remarks ──────────────────────────

def test_workout_with_no_exercises_no_remarks(client, alice_id):
    w = _create_lift(client, alice_id, exercises=[], remarks=None)
    try:
        res = client.get(f"/api/workouts/{w['id']}")
        assert res.status_code == 200
        data = res.json()
        assert data["exercises"] == []
        assert data["remarks"] is None
    finally:
        _delete(client, w["id"])


# ── AC8: remarks is returned as plain text (no edit affordance in API) ────────

def test_remarks_is_read_only_text_not_editable_via_get(client, alice_id):
    notes = "Back felt tight, reduced weight on last set."
    w = _create_lift(client, alice_id, remarks=notes)
    try:
        res = client.get(f"/api/workouts/{w['id']}")
        assert res.status_code == 200
        data = res.json()
        # remarks is a plain string, not a dict or object with edit fields
        assert isinstance(data["remarks"], str)
        assert data["remarks"] == notes
    finally:
        _delete(client, w["id"])


# ── log.html HTML structure: panel sections exist ────────────────────────────

def test_log_page_contains_exercise_section_element(client):
    res = client.get("/log")
    assert res.status_code == 200
    html = res.text
    assert 'id="detail-exercise-section"' in html


def test_log_page_contains_notes_section_element(client):
    res = client.get("/log")
    assert res.status_code == 200
    html = res.text
    assert 'id="detail-notes-section"' in html


def test_log_page_exercise_sections_hidden_by_default(client):
    res = client.get("/log")
    assert res.status_code == 200
    html = res.text
    # Both sections start hidden
    assert 'id="detail-exercise-section"' in html
    assert 'id="detail-notes-section"' in html
    # They must have display:none in their inline style on page load
    import re
    ex_match = re.search(r'id="detail-exercise-section"[^>]*>', html)
    notes_match = re.search(r'id="detail-notes-section"[^>]*>', html)
    assert ex_match and "display:none" in ex_match.group(0)
    assert notes_match and "display:none" in notes_match.group(0)
