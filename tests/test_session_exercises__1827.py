"""Issue #1827 — session exercise JSON parse, validate, format."""

import json

from backend.db import engine
from backend.models import PlanExercise
from backend.services.session_exercises import (
    expand_shorthand,
    format_exercises,
    normalize_exercises,
    validate_session_exercises,
    _validate_set_object,
)
from sqlalchemy.orm import Session


def test_shorthand_expands_to_one_set_per_line():
    raw = {"name": "Calf raise", "sets": 3, "kg": 24, "reps": 15}
    expanded = expand_shorthand(raw)
    assert len(expanded["sets"]) == 3
    assert expanded["sets"][0] == {"kg": 24, "reps": 15}


def test_round_trip_format_stable():
    exercises, errors = normalize_exercises(
        [
            {
                "name": "Single-leg deadlift",
                "sets": [{"kg": 22, "reps": "8/side"}],
            }
        ]
    )
    assert not errors
    first = format_exercises(exercises)
    again_ex, err2 = normalize_exercises(json.loads(first))
    assert not err2
    second = format_exercises(again_ex)
    assert first == second


def test_mixed_set_form_rejected():
    _, msg = _validate_set_object({"kg": 20, "reps": 10, "hold": "45s"})
    assert msg is not None
    assert "mix" in msg.lower()


def test_reps_out_of_range_error_has_line():
    _, errors = normalize_exercises(
        [{"name": "Press", "sets": [{"reps": 0}]}],
        source_text='[{"name": "Press", "sets": [{"reps": 0}]}]',
    )
    assert errors
    assert errors[0]["line"] >= 1
    assert "reps" in errors[0]["message"].lower()


def test_custom_name_closest_match():
    import uuid as _uuid

    lib_name = f"Zealothon split squat {_uuid.uuid4().hex[:8]}"
    with Session(engine) as session:
        lib = PlanExercise(name=lib_name, groups=[], focus_tags=[], body_parts=[], tss_weight=0.7)
        session.add(lib)
        session.commit()
        try:
            payload = validate_session_exercises(
                session,
                exercises=[{"name": "Zealothon split squt", "sets": [{"kg": 20, "reps": 12}]}],
            )
            assert payload["valid"] is True
            assert len(payload["resolutions"]) == 1
            res = payload["resolutions"][0]
            assert res["custom"] is True
            assert res["closest_match"] == lib_name
        finally:
            session.delete(lib)
            session.commit()


def test_validate_endpoint_shape_via_service():
    with Session(engine) as session:
        payload = validate_session_exercises(
            session,
            text='[{"name": "Plank", "sets": 2, "hold": "45s"}]',
        )
    assert payload["valid"] is True
    assert payload["exercises"][0]["sets"] == [{"hold": "45s"}, {"hold": "45s"}]
    assert "formatted" in payload
    assert payload["resolutions"][0]["name"] == "Plank"