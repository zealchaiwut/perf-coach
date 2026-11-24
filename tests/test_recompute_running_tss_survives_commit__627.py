"""Regression test for issue #627: recompute_user_running_tss must actually persist.

Context: recompute_user_running_tss() looped over a user's running workouts and
called ``session.expire(w)`` on each one right after persist_running_tss() set
workout.tss / tss_method / tss_source on it, before the caller's session.commit()
ran. SQLAlchemy's session.expire() discards pending, unflushed attribute changes
(they simply never reach the flush), so every threshold-triggered recompute was a
silent no-op — the in-memory objects looked refreshed, but nothing ever reached
the database and callers (e.g. the /api/preferences threshold-update handler,
backend/main.py) would commit an effectively-empty transaction.

This test uses a real SQLAlchemy session (SQLite) rather than a mock, because a
mock's expire() can be (and previously was, in test_persist_running_tss_
threshold_refresh__627.py) a no-op that hides exactly this bug. It monkeypatches
backend.models.Workout/WorkoutSplit/UserPreferences with lightweight SQLite-
compatible equivalents (the real models use Postgres-only UUID/JSONB columns),
then verifies the refreshed TSS is visible from a *separate* session opened
after commit — proving the value actually reached the database, not just the
in-memory object.
"""
import uuid

import pytest
from sqlalchemy import Column, Float, Integer, Numeric, String, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

_Base = declarative_base()


class _Workout(_Base):
    __tablename__ = "workouts"

    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False)
    workout_type = Column(String, nullable=False)
    tss = Column(Float, nullable=True)
    tss_source = Column(String, nullable=True)
    tss_method = Column(String, nullable=True)
    np = Column(Integer, nullable=True)
    avg_hr = Column(Integer, nullable=True)
    distance_km = Column(Numeric(8, 3), nullable=True)
    duration_seconds = Column(Integer, nullable=True)


class _WorkoutSplit(_Base):
    __tablename__ = "workout_splits"

    id = Column(String, primary_key=True)
    workout_id = Column(String, nullable=False)
    split_index = Column(Integer, nullable=False)
    distance_km = Column(Numeric(6, 3), nullable=False)
    duration_seconds = Column(Integer, nullable=False)
    avg_hr = Column(Integer, nullable=True)


class _UserPreferences(_Base):
    __tablename__ = "user_preferences"

    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False, unique=True)
    ftp_w = Column(Integer, nullable=True)
    threshold_hr = Column(Integer, nullable=True)
    threshold_pace_seconds_per_km = Column(Integer, nullable=True)


@pytest.fixture
def sqlite_session(monkeypatch):
    import backend.models as models

    monkeypatch.setattr(models, "Workout", _Workout)
    monkeypatch.setattr(models, "WorkoutSplit", _WorkoutSplit)
    monkeypatch.setattr(models, "UserPreferences", _UserPreferences)

    engine = create_engine("sqlite:///:memory:")
    _Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session, engine
    finally:
        session.close()


def test_recompute_user_running_tss_value_survives_commit(sqlite_session):
    """AC: after recompute_user_running_tss() + the caller's commit, the refreshed
    TSS must be readable from a brand-new session (i.e. actually in the DB), not
    just present on the now-stale in-memory object."""
    from backend.services.tss import recompute_user_running_tss

    session, engine = sqlite_session
    user_id = str(uuid.uuid4())

    # Previously computed at an old, lower FTP → stored tss=50.
    workout_id = str(uuid.uuid4())
    session.add(_Workout(
        id=workout_id,
        user_id=user_id,
        workout_type="Run",
        tss=50,
        tss_source="calculated",
        np=280,
        duration_seconds=3600,
    ))
    # New threshold: FTP raised to 350 → IF = 280/350 = 0.8 → TSS = 0.8^2*100 = 64
    session.add(_UserPreferences(id=str(uuid.uuid4()), user_id=user_id, ftp_w=350))
    session.commit()

    count = recompute_user_running_tss(user_id, session)
    assert count == 1
    session.commit()  # mirrors the caller contract in backend/main.py

    Session = sessionmaker(bind=engine)
    fresh_session = Session()
    try:
        persisted = fresh_session.query(_Workout).filter(_Workout.id == workout_id).first()
        assert persisted.tss == 64, (
            f"expected refreshed TSS=64 to be persisted to the DB, got {persisted.tss} "
            "(if this is still 50, the recompute changes never survived commit)"
        )
        assert persisted.tss_source == "calculated"
    finally:
        fresh_session.close()
