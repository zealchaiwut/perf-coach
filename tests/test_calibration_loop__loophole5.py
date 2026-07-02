"""Tests for fix-loopholes Task 5: close the calibration loop.

UserPreferences.ctl_days / atl_days were saved by the accept-calibration
endpoint but never read back — current_load/daily_update/compute_load_curves
always used the module constants (CTL_DAYS=42, ATL_DAYS=7). Now
resolve_user_ewma_days() reads the user's saved calibration (falling back
to the module constants when unset), and current_load/daily_update honor it.
"""
import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy.orm import Session

from backend.db import engine
from backend.models import User, UserPreferences, Workout
from backend.services.training_load import (
    CTL_DAYS,
    ATL_DAYS,
    current_load,
    daily_update,
    resolve_user_ewma_days,
)


@pytest.fixture
def user_with_custom_calibration():
    user = User(name="loophole5-" + uuid.uuid4().hex[:8])
    with Session(engine) as db:
        db.add(user)
        db.commit()
        uid = user.id
        prefs = UserPreferences(user_id=uid, ctl_days=20, atl_days=5)
        db.add(prefs)
        db.commit()

        today = date.today()
        for i in range(10):
            db.add(Workout(
                user_id=uid,
                workout_date=today - timedelta(days=i),
                name="Run",
                workout_type="run",
                tss=50.0,
            ))
        db.commit()

    yield uid

    with Session(engine) as db:
        db.query(Workout).filter(Workout.user_id == uid).delete()
        db.query(UserPreferences).filter(UserPreferences.user_id == uid).delete()
        db.query(User).filter(User.id == uid).delete()
        db.commit()


def test_resolve_user_ewma_days_returns_saved_calibration(user_with_custom_calibration):
    ctl_days, atl_days = resolve_user_ewma_days(str(user_with_custom_calibration))
    assert (ctl_days, atl_days) == (20, 5)


def test_resolve_user_ewma_days_falls_back_to_constants_when_unset():
    user = User(name="loophole5-nocal-" + uuid.uuid4().hex[:8])
    with Session(engine) as db:
        db.add(user)
        db.commit()
        uid = user.id
    try:
        ctl_days, atl_days = resolve_user_ewma_days(str(uid))
        assert (ctl_days, atl_days) == (CTL_DAYS, ATL_DAYS)
    finally:
        with Session(engine) as db:
            db.query(User).filter(User.id == uid).delete()
            db.commit()


def test_current_load_honors_custom_calibration(user_with_custom_calibration):
    uid = user_with_custom_calibration
    default_result = daily_update(str(uid), target_date=date.today(), ctl_days=CTL_DAYS, atl_days=ATL_DAYS)
    custom_result = current_load(str(uid))

    assert custom_result["ctl"] != default_result["ctl"], (
        "current_load should use the user's custom ctl_days/atl_days, "
        "not the module default constants"
    )


def test_daily_update_skips_snapshot_write_for_custom_calibration(user_with_custom_calibration):
    from backend.models import TrainingLoadSnapshot

    uid = user_with_custom_calibration
    today = date.today()
    with Session(engine) as db:
        db.query(TrainingLoadSnapshot).filter(
            TrainingLoadSnapshot.user_id == uid, TrainingLoadSnapshot.snapshot_date == today
        ).delete()
        db.commit()

    daily_update(str(uid), target_date=today, ctl_days=20, atl_days=5)

    with Session(engine) as db:
        snap = (
            db.query(TrainingLoadSnapshot)
            .filter(TrainingLoadSnapshot.user_id == uid, TrainingLoadSnapshot.snapshot_date == today)
            .first()
        )
        assert snap is None, (
            "custom-calibration daily_update should not write to the shared "
            "snapshot cache (it doesn't record which constants produced a row)"
        )
