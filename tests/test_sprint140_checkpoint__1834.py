"""Issue #1834 — Phase 2 checkpoint smoke (API + services)."""

from sqlalchemy.orm import Session

from backend.db import engine
from backend.services.session_exercises import format_exercises, validate_session_exercises
from backend.services.session_strength_save import strength_type_allowed
from backend.services.strength_tss import from_effort_time


def test_phase2_strength_pipeline_smoke():
    assert strength_type_allowed("strength")
    assert from_effort_time(duration_min=52, effort=7)["tss"] == 42
    with Session(engine) as session:
        v = validate_session_exercises(
            session,
            exercises=[{"name": "Goblet squat", "sets": 3, "reps": 10, "kg": 24}],
        )
        assert v["valid"]
        text = format_exercises(v["exercises"])
        v2 = validate_session_exercises(session, text=text)
        assert v2["valid"]
        assert v2["formatted"] == text