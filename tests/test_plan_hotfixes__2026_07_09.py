"""Plan hotfixes (2026-07-09), reported live with 3 screenshots:

1. A real Run + Lift logged on a day whose only planned session was strength
   ("Tuesday leg day") hid the Run entirely from the Week Plan pane —
   unplanned_workout_ids() required a same-day compatible-type planned
   session to exist before a workout counted as a ghost. Fixed: every real,
   unmatched workout in the loaded window now surfaces as a ghost.
2. A matched planned session's detail should show what actually happened at
   the gym (real exercises + RPE from the matched Workout), not just the
   plan, and flag when RPE is still missing. Fixed: _workout_actual_summary
   now includes `exercises` + `needs_rpe`.
3. (frontend-only, no Python surface — see training-plan.js _renderWeekList
   is-past / pl-addday.is-disabled; verified via node --check + manual UI.)

Real-Postgres for the DB-backed pieces, matching the existing plan-suggestion
test fixture pattern (users.id CASCADE deletes workouts/planned_sessions).
"""
import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.db import engine
from backend.main import _workout_actual_summary
from backend.models import PlannedSession, User, Workout, WorkoutExercise
from backend.services import plan_matching as pm


@pytest.fixture()
def hotfix_user():
    with Session(engine) as s:
        u = User(name=f"plan-hotfix-{uuid.uuid4().hex[:8]}", is_active=True)
        s.add(u); s.commit(); s.refresh(u)
        uid = u.id
    yield uid
    with Session(engine) as s:
        s.execute(text("DELETE FROM users WHERE id = :i"), {"i": uid})
        s.commit()


# ── Fix 1: unplanned_workout_ids no longer gates on a same-day planned type ──

def test_ghost_surfaces_even_when_only_planned_session_that_day_is_incompatible(hotfix_user):
    """A logged Run on a day whose only planned session is strength (already
    matched to a different workout) must still surface as a ghost."""
    tuesday = date.today() - timedelta(days=1)
    with Session(engine) as s:
        lift = Workout(user_id=hotfix_user, workout_date=tuesday, name="Leg day", workout_type="strength")
        run = Workout(user_id=hotfix_user, workout_date=tuesday, name="Tuesday run", workout_type="run")
        s.add_all([lift, run]); s.flush()
        run_id = run.id

        ps = PlannedSession(
            user_id=hotfix_user, planned_date=tuesday, session_type="strength",
            name="Leg day", status="done_manual", matched_workout_id=lift.id,
        )
        s.add(ps); s.commit()

    with Session(engine) as s:
        ghosts = pm.unplanned_workout_ids(s, hotfix_user, tuesday, tuesday)
    assert run_id in ghosts


def test_matched_workout_is_never_a_ghost(hotfix_user):
    day = date.today() - timedelta(days=1)
    with Session(engine) as s:
        w = Workout(user_id=hotfix_user, workout_date=day, name="Leg day", workout_type="strength")
        s.add(w); s.flush()
        w_id = w.id
        s.add(PlannedSession(
            user_id=hotfix_user, planned_date=day, session_type="strength",
            name="Leg day", status="done_manual", matched_workout_id=w.id,
        ))
        s.commit()

    with Session(engine) as s:
        ghosts = pm.unplanned_workout_ids(s, hotfix_user, day, day)
    assert w_id not in ghosts


def test_ghost_surfaces_with_no_planned_session_at_all_that_day(hotfix_user):
    day = date.today() - timedelta(days=1)
    with Session(engine) as s:
        w = Workout(user_id=hotfix_user, workout_date=day, name="Solo run", workout_type="run")
        s.add(w); s.commit()
        w_id = w.id

    with Session(engine) as s:
        ghosts = pm.unplanned_workout_ids(s, hotfix_user, day, day)
    assert w_id in ghosts


# ── Fix 2: _workout_actual_summary carries real exercises + needs_rpe ───────

def test_actual_summary_includes_exercises_and_flags_missing_rpe(hotfix_user):
    day = date.today() - timedelta(days=1)
    with Session(engine) as s:
        w = Workout(user_id=hotfix_user, workout_date=day, name="Leg day", workout_type="strength")
        s.add(w); s.flush()
        s.add(WorkoutExercise(workout_id=w.id, display_order=0, name="Back squat", sets=4, reps=8, weight_kg=100, rpe=8))
        s.add(WorkoutExercise(workout_id=w.id, display_order=1, name="Romanian deadlift", sets=3, reps=10, weight_kg=80, rpe=None))
        s.commit()

    with Session(engine) as s:
        w = s.query(Workout).filter(Workout.user_id == hotfix_user, Workout.workout_date == day).one()
        summary = _workout_actual_summary(w)

    names = [e["name"] for e in summary["exercises"]]
    assert names == ["Back squat", "Romanian deadlift"]
    assert summary["exercises"][0]["rpe"] == 8
    assert summary["exercises"][1]["rpe"] is None
    assert summary["needs_rpe"] is True


def test_actual_summary_needs_rpe_false_when_all_have_rpe(hotfix_user):
    day = date.today() - timedelta(days=1)
    with Session(engine) as s:
        w = Workout(user_id=hotfix_user, workout_date=day, name="Leg day", workout_type="strength")
        s.add(w); s.flush()
        s.add(WorkoutExercise(workout_id=w.id, display_order=0, name="Back squat", sets=4, reps=8, rpe=8))
        s.commit()

    with Session(engine) as s:
        w = s.query(Workout).filter(Workout.user_id == hotfix_user, Workout.workout_date == day).one()
        summary = _workout_actual_summary(w)
    assert summary["needs_rpe"] is False


def test_actual_summary_no_exercises_needs_rpe_false(hotfix_user):
    day = date.today() - timedelta(days=1)
    with Session(engine) as s:
        w = Workout(user_id=hotfix_user, workout_date=day, name="Easy run", workout_type="run")
        s.add(w); s.commit()

    with Session(engine) as s:
        w = s.query(Workout).filter(Workout.user_id == hotfix_user, Workout.workout_date == day).one()
        summary = _workout_actual_summary(w)
    assert summary["exercises"] == []
    assert summary["needs_rpe"] is False
