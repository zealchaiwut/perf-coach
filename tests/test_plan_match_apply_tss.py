"""Plan match applies planned TSS + exercises onto empty Strava strength rows."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from backend.services.plan_match_apply import (
    apply_planned_session_to_workout,
    resolve_planned_tss,
)
from backend.services.session_pins import structure_actual_spend


def test_resolve_planned_tss_prefers_target_tss():
    structure = {
        "target_tss": 50,
        "exercises": [
            {"name": "Squat", "state": "completed", "spend_tss": 10},
            {"name": "RDL", "state": "completed", "spend_tss": 12},
        ],
    }
    assert resolve_planned_tss(structure) == 50.0


def test_resolve_planned_tss_sums_spend_when_no_target():
    structure = {
        "exercises": [
            {"name": "Squat", "state": "completed", "spend_tss": 10},
            {"name": "RDL", "state": "skipped", "spend_tss": 99},
            {"name": "Press", "state": "done", "spend_tss": 5},
        ],
    }
    assert resolve_planned_tss(structure) == 15.0


def test_structure_actual_spend_treats_completed_as_done():
    structure = {
        "target_tss": 50,
        "exercises": [
            {"name": "Squat", "state": "completed", "spend_tss": 10, "spend_min": 5},
        ],
    }
    spend = structure_actual_spend(structure)
    assert spend is not None
    assert spend["actual_tss"] == 10.0
    assert spend["planned_tss"] == 50.0


def test_apply_stamps_tss_and_exercises_when_workout_empty():
    structure = {
        "target_tss": 50,
        "exercises": [
            {
                "name": "Bodyweight squat",
                "sets": 3,
                "reps": "15",
                "block": "Warm-up",
                "state": "completed",
                "spend_tss": 1,
            },
            {"name": "Skip me", "state": "skipped", "spend_tss": 9},
        ],
    }
    planned = SimpleNamespace(structure=structure)
    workout = SimpleNamespace(id="w1", tss=None, tss_source=None)
    session = MagicMock()
    # No existing exercises
    session.query.return_value.filter.return_value.count.return_value = 0

    stats = apply_planned_session_to_workout(session, planned, workout)

    assert stats["tss_applied"] is True
    assert stats["tss"] == 50.0
    assert workout.tss == 50.0
    assert workout.tss_source == "manual"
    assert stats["exercises_added"] == 1
    assert session.add.call_count == 1
    added = session.add.call_args[0][0]
    assert added.name == "Bodyweight squat"
    assert added.sets == 3
    assert added.reps == 15


def test_apply_does_not_overwrite_existing_tss_or_exercises():
    planned = SimpleNamespace(structure={"target_tss": 50, "exercises": [{"name": "A", "state": "done"}]})
    workout = SimpleNamespace(id="w1", tss=40.0, tss_source="manual")
    session = MagicMock()
    session.query.return_value.filter.return_value.count.return_value = 2

    stats = apply_planned_session_to_workout(session, planned, workout)

    assert stats["tss_applied"] is False
    assert workout.tss == 40.0
    assert stats["exercises_added"] == 0
    session.add.assert_not_called()
