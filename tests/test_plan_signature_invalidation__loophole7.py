"""Tests for fix-loopholes Task 7: Plan-cache invalidation on workout/checkpoint edits.

_plan_signature didn't include workouts.updated_at or race_checkpoints.updated_at,
so editing an existing workout's fields (PATCH /api/workouts/{id}, which stamps
updated_at) or a race checkpoint never changed the signature — the cached
Plan-tab bundle (TrainingPlan.computed_cache) silently went stale. The
workouts.updated_at column existed in some environments but had no Alembic
migration provenance (added here) and no onupdate; race_checkpoints.updated_at
had no onupdate either. Both now stamp automatically and both feed the signature.
"""
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from backend.db import engine
from backend.main import _plan_signature
from backend.models import Race, RaceCheckpoint, TrainingPlan, User, Workout


@pytest.fixture
def user_with_plan():
    user = User(name="loophole7-" + uuid.uuid4().hex[:8])
    with Session(engine) as db:
        db.add(user)
        db.commit()
        uid = user.id
        plan = TrainingPlan(user_id=uid, name="Test plan")
        db.add(plan)
        db.commit()
        plan_id = plan.id

    yield uid, plan_id

    with Session(engine) as db:
        db.query(RaceCheckpoint).filter(RaceCheckpoint.user_id == uid).delete()
        db.query(Race).filter(Race.user_id == uid).delete()
        db.query(Workout).filter(Workout.user_id == uid).delete()
        db.query(TrainingPlan).filter(TrainingPlan.id == plan_id).delete()
        db.query(User).filter(User.id == uid).delete()
        db.commit()


def test_editing_workout_updated_at_changes_signature(user_with_plan):
    uid, plan_id = user_with_plan
    with Session(engine) as db:
        wk = Workout(user_id=uid, workout_date=date.today(), name="Run", workout_type="run")
        db.add(wk)
        db.commit()
        wk_id = wk.id
        plan = db.get(TrainingPlan, plan_id)
        sig_before = _plan_signature(db, uid, plan)

        wk = db.get(Workout, wk_id)
        wk.updated_at = datetime.now(timezone.utc) + timedelta(seconds=1)
        db.commit()

        plan = db.get(TrainingPlan, plan_id)
        sig_after = _plan_signature(db, uid, plan)

    assert sig_before != sig_after, (
        "editing a workout's updated_at must change _plan_signature so the "
        "cached Plan bundle is invalidated"
    )


def test_editing_checkpoint_updated_at_changes_signature(user_with_plan):
    uid, plan_id = user_with_plan
    with Session(engine) as db:
        race = Race(
            user_id=uid, name="Test race", race_date=date.today() + timedelta(days=30),
            priority="A", status="planned",
        )
        db.add(race)
        db.commit()
        cp = RaceCheckpoint(
            race_id=race.id, user_id=uid, label="Halfway", target_date=date.today() + timedelta(days=15)
        )
        db.add(cp)
        db.commit()
        cp_id = cp.id

        plan = db.get(TrainingPlan, plan_id)
        sig_before = _plan_signature(db, uid, plan)

        cp = db.get(RaceCheckpoint, cp_id)
        cp.updated_at = datetime.now(timezone.utc) + timedelta(seconds=1)
        db.commit()

        plan = db.get(TrainingPlan, plan_id)
        sig_after = _plan_signature(db, uid, plan)

    assert sig_before != sig_after, (
        "editing a checkpoint's updated_at must change _plan_signature so the "
        "cached Plan bundle is invalidated"
    )


def test_workout_patch_endpoint_stamps_updated_at_via_onupdate(user_with_plan):
    """The model-level onupdate now stamps updated_at on any ORM UPDATE, not
    just the endpoints that set it manually."""
    uid, plan_id = user_with_plan
    with Session(engine) as db:
        wk = Workout(user_id=uid, workout_date=date.today(), name="Run", workout_type="run")
        db.add(wk)
        db.commit()
        wk_id = wk.id
        assert wk.updated_at is None

        wk = db.get(Workout, wk_id)
        wk.name = "Renamed run"
        db.commit()

        wk = db.get(Workout, wk_id)
        assert wk.updated_at is not None
