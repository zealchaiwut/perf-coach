"""Issue #1831 — pending custom exercises queue and remap."""

import uuid
from datetime import date

import pytest
from sqlalchemy.orm import Session

from backend.db import engine
from backend.models import PendingExercise, PlanExercise, User, Workout
from backend.services.pending_exercises import normalize_exercise_name, remap_custom, upsert_custom_names


@pytest.fixture
def session_db():
    with Session(engine) as session:
        yield session
        session.rollback()


def test_normalize_collapses_spaces():
    assert normalize_exercise_name("  Foo   Bar ") == "foo bar"


def test_two_sessions_one_pending_record(session_db):
    u = session_db.query(User).first()
    if u is None:
        pytest.skip("no user in DB")
    w1 = Workout(user_id=u.id, name="S1", workout_date=date(2025, 1, 6), workout_type="strength")
    w2 = Workout(user_id=u.id, name="S2", workout_date=date(2025, 1, 7), workout_type="strength")
    session_db.add_all([w1, w2])
    session_db.flush()
    ex = [{"name": "My Custom Press", "sets": [{"reps": 8, "kg": 20}]}]
    upsert_custom_names(session_db, workout_id=w1.id, exercises=ex)
    session_db.flush()
    upsert_custom_names(session_db, workout_id=w2.id, exercises=ex)
    session_db.flush()
    row = (
        session_db.query(PendingExercise)
        .filter(PendingExercise.normalized_name == normalize_exercise_name("My Custom Press"))
        .one()
    )
    assert row.occurrence_count == 2


def test_remap_custom_updates_sessions(session_db):
    u = session_db.query(User).first()
    lib = session_db.query(PlanExercise).filter(PlanExercise.active.is_(True)).first()
    if u is None or lib is None:
        pytest.skip("needs user and plan exercise")
    w1 = Workout(
        user_id=u.id,
        name="A",
        workout_date=date(2025, 2, 3),
        workout_type="strength",
        exercises_json=[{"name": "Zebra Custom", "sets": [{"reps": 5}]}],
    )
    w2 = Workout(
        user_id=u.id,
        name="B",
        workout_date=date(2025, 2, 4),
        workout_type="strength",
        exercises_json=[{"name": "Zebra Custom", "sets": [{"reps": 6}]}],
    )
    session_db.add_all([w1, w2])
    session_db.flush()
    upsert_custom_names(session_db, workout_id=w1.id, exercises=w1.exercises_json)
    upsert_custom_names(session_db, workout_id=w2.id, exercises=w2.exercises_json)
    session_db.flush()
    stats = remap_custom(session_db, name="Zebra Custom", library_id=lib.id)
    assert stats["sessions_updated"] == 2
    session_db.refresh(w1)
    assert w1.exercises_json[0]["name"] == lib.name