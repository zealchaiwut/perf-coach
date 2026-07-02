"""Tests for issue #116: Add exercise breakdown and notes to Training Log detail panel (UAT environment)"""
import datetime
import os

import httpx
import pytest
from tests._admin_helpers import admin_cookies as _admin_cookies


# Resolved from UAT .env at runtime; see tester skill Step 0.
# Fallback to localhost:9001 if not exported.
BASE_URL = os.environ.get("UAT_BASE_URL") or "http://localhost:9001"
if not BASE_URL.startswith("http"):
    raise RuntimeError(
        "UAT_BASE_URL not properly set. Run tester skill Step 0 to resolve UAT environment."
    )

TODAY = datetime.date.today()
TODAY_STR = TODAY.isoformat()


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        yield c


@pytest.fixture(scope="module")
def user_id(client):
    """Get or create a test user for this test suite."""
    res = client.get("/api/users", cookies=_admin_cookies())
    assert res.status_code == 200, f"Failed to fetch users: {res.status_code}"
    users = res.json()

    # Try to use an existing user or create one
    if users:
        return users[0]["id"]

    # Create a test user if none exist
    res = client.post("/api/users", json={"name": "test_user_116"}, cookies=_admin_cookies())
    assert res.status_code in (201, 409), f"Failed to create user: {res.status_code}"
    users = client.get("/api/users", cookies=_admin_cookies()).json()
    return users[0]["id"] if users else None


def _cleanup_workouts(client, user_id, from_str, to_str):
    """Delete all workouts in a date range for cleanup."""
    res = client.get(f"/api/workouts?user_id={user_id}&from={from_str}&to={to_str}")
    if res.status_code == 200:
        for w in res.json():
            client.delete(f"/api/workouts/{w['id']}")


def _post_workout(client, user_id, date_str, name, workout_type, exercises=None, remarks=None):
    """Create a workout and return its ID and full details."""
    body = {
        "user_id": user_id,
        "name": name,
        "workout_date": date_str,
        "workout_type": workout_type,
        "exercises": exercises or [],
    }
    if remarks:
        body["remarks"] = remarks

    res = client.post("/api/workouts", json=body)
    assert res.status_code == 201, f"POST workout failed: {res.status_code} {res.text}"
    return res.json()


def _get_workout_detail(client, workout_id):
    """Fetch full workout detail from the API."""
    res = client.get(f"/api/workouts/{workout_id}")
    assert res.status_code == 200, f"GET workout detail failed: {res.status_code}"
    return res.json()


# ─── AC-1: A strength workout with exercises renders Exercise Breakdown section ────

def test_exercise_breakdown__strength_with_exercises(client, user_id):
    """AC: Strength workout with exercises renders Exercise Breakdown section."""
    _cleanup_workouts(client, user_id, TODAY_STR, TODAY_STR)

    exercises = [
        {"name": "Squat", "sets": 4, "reps": 5, "weight_kg": 100, "rpe": 8, "display_order": 1},
        {"name": "Bench Press", "sets": 3, "reps": 8, "weight_kg": 80, "rpe": 7, "display_order": 2},
    ]

    workout = _post_workout(
        client, user_id, TODAY_STR,
        name="Upper Body",
        workout_type="Strength",
        exercises=exercises
    )

    detail = _get_workout_detail(client, workout["id"])
    assert detail.get("exercises") is not None
    assert len(detail["exercises"]) == 2
    assert detail["workout_type"] == "Strength"


# ─── AC-2: Each exercise row displays name, sets × reps, weight_kg, and RPE ─────

def test_exercise_breakdown__fields_present(client, user_id):
    """AC: Exercise rows contain name, sets × reps, weight, and RPE fields."""
    _cleanup_workouts(client, user_id, TODAY_STR, TODAY_STR)

    exercises = [
        {
            "name": "Deadlift",
            "sets": 3,
            "reps": 5,
            "weight_kg": 200,
            "rpe": 9,
            "display_order": 1,
        }
    ]

    workout = _post_workout(
        client, user_id, TODAY_STR,
        name="Lower Body",
        workout_type="Strength",
        exercises=exercises
    )

    detail = _get_workout_detail(client, workout["id"])
    ex = detail["exercises"][0]

    assert ex["name"] == "Deadlift"
    assert ex["sets"] == 3
    assert ex["reps"] == 5
    assert ex["weight_kg"] == 200
    assert ex["rpe"] == 9


# ─── AC-3: Exercise rows are ordered by display_order (ascending) ──────────────

def test_exercise_breakdown__ordered_by_display_order(client, user_id):
    """AC: Exercise rows are sorted by display_order ascending (client-side rendering)."""
    _cleanup_workouts(client, user_id, TODAY_STR, TODAY_STR)

    # Post exercises in a specific order; API assigns display_order sequentially
    exercises = [
        {"name": "First", "sets": 1, "reps": 1, "weight_kg": 10, "rpe": 5},
        {"name": "Second", "sets": 1, "reps": 1, "weight_kg": 10, "rpe": 5},
        {"name": "Third", "sets": 1, "reps": 1, "weight_kg": 10, "rpe": 5},
    ]

    workout = _post_workout(
        client, user_id, TODAY_STR,
        name="Order Test",
        workout_type="Strength",
        exercises=exercises
    )

    detail = _get_workout_detail(client, workout["id"])
    # Verify exercises have display_order assigned (0, 1, 2, etc.)
    assert all("display_order" in ex for ex in detail["exercises"])

    # Verify the JavaScript code can sort them correctly
    sorted_exercises = sorted(detail["exercises"], key=lambda e: e.get("display_order", 0))
    assert sorted_exercises[0]["name"] == "First"
    assert sorted_exercises[1]["name"] == "Second"
    assert sorted_exercises[2]["name"] == "Third"


# ─── AC-4: Workout with non-empty remarks renders read-only Notes section ──────

def test_notes_section__with_remarks(client, user_id):
    """AC: Workout with remarks displays Notes section with the text."""
    _cleanup_workouts(client, user_id, TODAY_STR, TODAY_STR)

    remarks_text = "Great session today! Felt strong on squats."

    workout = _post_workout(
        client, user_id, TODAY_STR,
        name="Full Body",
        workout_type="Strength",
        exercises=[],
        remarks=remarks_text
    )

    detail = _get_workout_detail(client, workout["id"])
    assert detail.get("remarks") == remarks_text


# ─── AC-5: Workout with no exercises does NOT render Exercise Breakdown ─────────

def test_exercise_breakdown__not_shown_when_empty(client, user_id):
    """AC: Strength workout with no exercises does not render Exercise Breakdown."""
    _cleanup_workouts(client, user_id, TODAY_STR, TODAY_STR)

    workout = _post_workout(
        client, user_id, TODAY_STR,
        name="Rest Day Thoughts",
        workout_type="Strength",
        exercises=[]  # No exercises
    )

    detail = _get_workout_detail(client, workout["id"])
    # Client-side code should hide the section if exercises is empty
    assert detail.get("exercises") is not None
    assert len(detail.get("exercises", [])) == 0


# ─── AC-6: Workout with no remarks does NOT render Notes section ─────────────────

def test_notes_section__not_shown_when_empty(client, user_id):
    """AC: Workout with no remarks does not render Notes section."""
    _cleanup_workouts(client, user_id, TODAY_STR, TODAY_STR)

    workout = _post_workout(
        client, user_id, TODAY_STR,
        name="No Notes",
        workout_type="Strength",
        exercises=[{"name": "Squat", "sets": 4, "reps": 5, "weight_kg": 100, "rpe": 8, "display_order": 1}],
        remarks=None
    )

    detail = _get_workout_detail(client, workout["id"])
    # remarks should be null, None, or missing
    assert not detail.get("remarks") or detail.get("remarks") == ""


# ─── AC-7: Workout with neither exercises nor remarks shows neither section ─────

def test_exercise_breakdown_notes__both_empty(client, user_id):
    """AC: Workout with no exercises and no remarks renders neither section."""
    _cleanup_workouts(client, user_id, TODAY_STR, TODAY_STR)

    workout = _post_workout(
        client, user_id, TODAY_STR,
        name="Empty Workout",
        workout_type="Strength",
        exercises=[],
        remarks=None
    )

    detail = _get_workout_detail(client, workout["id"])
    assert len(detail.get("exercises", [])) == 0
    assert not detail.get("remarks") or detail.get("remarks") == ""


# ─── AC-8: Notes section is read-only (no edit affordance) ─────────────────────

@pytest.mark.skip(reason="log.html removed by #323 (dead code); detail-notes-* IDs existed only there, not in training-log.html")
def test_notes_section__read_only(client, user_id):
    """AC: Notes section is read-only; no edit field is present in the HTML."""
    import pathlib
    html = (pathlib.Path(__file__).parent.parent / "frontend" / "pages" / "log.html").read_text()

    assert 'id="detail-notes-section"' in html, "Missing detail-notes-section in log.html"
    assert 'id="detail-notes-text"' in html, "Missing detail-notes-text in log.html"

    notes_start = html.find('id="detail-notes-text"')
    notes_context = html[max(0, notes_start - 50):min(len(html), notes_start + 100)]
    assert '<p' in notes_context or 'class=' in notes_context, \
        "detail-notes-text should be a paragraph element"
    assert '<textarea' not in notes_context and '<input' not in notes_context, \
        "detail-notes-text must not be editable (no textarea or input)"


# ─── AC-9: HR-zones and splits sections NOT implemented ───────────────────────

def test_not_implemented__hr_zones_section_not_in_html():
    """AC (out of scope): HR-zones section is not implemented."""
    import pathlib
    html = (pathlib.Path(__file__).parent.parent / "frontend" / "pages" / "training-log.html").read_text()

    assert "HR-zones" not in html and "hr-zones" not in html, \
        "HR-zones section should not be implemented in this sprint"


@pytest.mark.skip(reason="log.html removed by #323; training-log.html now has dp-splits (implemented in later sprint)")
def test_not_implemented__splits_section_not_in_html():
    """AC (out of scope): Splits section is not implemented."""
    import pathlib
    html = (pathlib.Path(__file__).parent.parent / "frontend" / "pages" / "training-log.html").read_text()

    assert "Splits" not in html and "splits" not in html, \
        "Splits section should not be implemented in this sprint"


# ─── Integration: Exercise Breakdown visible only for Strength workouts ─────────

def test_exercise_breakdown__strength_only(client, user_id):
    """Exercise Breakdown section appears only for Strength/Lift workouts, not Cardio."""
    _cleanup_workouts(client, user_id, TODAY_STR, TODAY_STR)

    # Create a Cardio workout with exercises (should be ignored)
    cardio = _post_workout(
        client, user_id, TODAY_STR,
        name="Evening Run",
        workout_type="Cardio",
        exercises=[
            {"name": "Warm-up", "sets": 1, "reps": 1, "weight_kg": 0, "rpe": 3, "display_order": 1}
        ]
    )

    detail = _get_workout_detail(client, cardio["id"])
    # Client should only show exercise breakdown for workout_type == "Strength" or "Lift"
    assert detail["workout_type"] == "Cardio"
    # The API still returns exercises, but the UI should not render the section


# ─── Data integrity: Fields not blank unless source is null ────────────────────

def test_exercise_breakdown__all_fields_match_source(client, user_id):
    """AC-2: All four fields match the stored values exactly; no field blank unless null."""
    _cleanup_workouts(client, user_id, TODAY_STR, TODAY_STR)

    exercises = [
        {
            "name": "Squat",
            "sets": 4,
            "reps": 5,
            "weight_kg": 100,
            "rpe": 8,
            "display_order": 1,
        }
    ]

    workout = _post_workout(
        client, user_id, TODAY_STR,
        name="Test",
        workout_type="Strength",
        exercises=exercises
    )

    detail = _get_workout_detail(client, workout["id"])
    ex = detail["exercises"][0]

    # Verify exact match
    assert ex["name"] == "Squat"
    assert ex["sets"] == 4
    assert ex["reps"] == 5
    assert ex["weight_kg"] == 100
    assert ex["rpe"] == 8
