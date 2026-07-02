"""Tests for fix-loopholes Task 6: broken compute_decoupling() calls.

_workout_signal_scores and _athlete_scores_as_of called compute_decoupling
with the wrong signature (splits first, {"workout_type": ...} second, no
threshold — 2 positional args instead of 3) and treated the returned 2-tuple
as a dict. This always raised inside the bare `except Exception: dpct = None`,
so decoupling_pct was silently None for every run workout regardless of real
efficiency drift. Both call sites now match the working call in the
/performance endpoint: compute_decoupling(workout_dict, splits, threshold).
"""
import uuid
from datetime import date, timedelta
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

import backend.main as main_mod
from backend.db import engine
from backend.main import _athlete_scores_as_of, _workout_signal_scores
from backend.models import User, Workout, WorkoutSplit


@pytest.fixture
def run_with_decoupling_splits():
    """A run with a clear efficiency drop in the second half: same pace,
    HR climbs from 140 to 170 — should yield a positive decoupling_pct."""
    user = User(name="loophole6-" + uuid.uuid4().hex[:8])
    with Session(engine) as db:
        db.add(user)
        db.commit()
        uid = user.id
        wk = Workout(
            user_id=uid,
            workout_date=date.today() - timedelta(days=1),
            name="Decoupling test run",
            workout_type="run",
        )
        db.add(wk)
        db.commit()
        wk_id = wk.id
        for i in range(10):
            hr = 140 if i < 5 else 170
            db.add(WorkoutSplit(
                workout_id=wk_id,
                split_index=i,
                distance_km=1.0,
                duration_seconds=300,
                avg_hr=hr,
            ))
        db.commit()

    yield uid, wk_id

    with Session(engine) as db:
        db.query(WorkoutSplit).filter(WorkoutSplit.workout_id == wk_id).delete()
        db.query(Workout).filter(Workout.id == wk_id).delete()
        db.query(User).filter(User.id == uid).delete()
        db.commit()


def test_workout_signal_scores_calls_decoupling_without_error(run_with_decoupling_splits, caplog):
    """decoupling_pct isn't surfaced in _workout_signal_scores's return (it only
    feeds compute_endurance_score/compute_speed_score internally), so assert
    indirectly: the fixed call shape must not raise inside the try/except
    (previously the wrong signature always did, silently, via the bare except)."""
    uid, wk_id = run_with_decoupling_splits
    with Session(engine) as db:
        wk = db.get(Workout, wk_id)
        with caplog.at_level("WARNING", logger="backend.main"):
            result = _workout_signal_scores(db, wk)

    assert not any("compute_decoupling failed" in r.message for r in caplog.records), (
        "compute_decoupling must not raise for a well-formed run + splits"
    )
    assert "endurance_score_current" in result


def test_athlete_scores_as_of_calls_decoupling_without_error(run_with_decoupling_splits, caplog):
    """_athlete_scores_as_of doesn't expose decoupling_pct in its return (it only
    feeds compute_endurance_score/compute_speed_score), so assert indirectly:
    the fixed call shape must not raise inside the try/except (previously the
    wrong signature always did, silently, via the bare except)."""
    uid, wk_id = run_with_decoupling_splits
    with Session(engine) as db:
        with caplog.at_level("WARNING", logger="backend.main"):
            scores = _athlete_scores_as_of(db, uid, date.today())

    assert not any("compute_decoupling failed" in r.message for r in caplog.records), (
        "compute_decoupling must not raise for a well-formed run + splits"
    )
    assert "endurance" in scores and "speed" in scores


def test_workout_signal_scores_calls_decoupling_with_correct_arg_order(run_with_decoupling_splits, monkeypatch):
    """Regression guard for the actual bug: workout dict must be the 1st
    positional arg, splits the 2nd, threshold the 3rd — not splits-first
    with no threshold, as it was before this fix."""
    uid, wk_id = run_with_decoupling_splits
    spy = MagicMock(return_value=({"decoupling_pct": 5.0}, None))
    monkeypatch.setattr(main_mod, "_compute_decoupling", spy)

    with Session(engine) as db:
        wk = db.get(Workout, wk_id)
        _workout_signal_scores(db, wk)

    assert spy.called
    args = spy.call_args[0]
    assert len(args) == 3
    assert isinstance(args[0], dict) and "workout_type" in args[0]
    assert isinstance(args[1], list)


def test_athlete_scores_as_of_calls_decoupling_with_correct_arg_order(run_with_decoupling_splits, monkeypatch):
    uid, wk_id = run_with_decoupling_splits
    spy = MagicMock(return_value=({"decoupling_pct": 5.0}, None))
    monkeypatch.setattr(main_mod, "_compute_decoupling", spy)

    with Session(engine) as db:
        _athlete_scores_as_of(db, uid, date.today())

    assert spy.called
    args = spy.call_args[0]
    assert len(args) == 3
    assert isinstance(args[0], dict) and "workout_type" in args[0]
    assert isinstance(args[1], list)
