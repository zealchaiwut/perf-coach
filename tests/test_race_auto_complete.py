"""Unit tests for planned-race auto-complete from synced runs."""
from __future__ import annotations

import datetime
import uuid
from datetime import date

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session as _OrmSess

try:
    @compiles(JSONB, "sqlite")
    def _jsonb_as_json_on_sqlite(type_, compiler, **kw):
        return "JSON"
except Exception:
    pass

from backend.models import Base, Race, User, Workout
from backend.services.race_auto_complete import (
    apply_race_autocomplete_for_workout,
    backfill_planned_races,
    match_workout_to_race,
)

_UTC = datetime.timezone.utc
_SQLITE_TABLES = (User, Workout, Race)


@pytest.fixture(scope="module")
def sqlite_engine():
    eng = create_engine("sqlite:///:memory:")

    @event.listens_for(eng, "connect")
    def _register_pg_functions(dbapi_conn, _record):
        dbapi_conn.create_function(
            "now", 0, lambda: datetime.datetime.now(_UTC).isoformat(sep=" ")
        )
        dbapi_conn.create_function("gen_random_uuid", 0, lambda: str(uuid.uuid4()))

    Base.metadata.create_all(eng, tables=[t.__table__ for t in _SQLITE_TABLES])
    yield eng
    eng.dispose()


@pytest.fixture()
def db(sqlite_engine):
    with _OrmSess(sqlite_engine) as session:
        yield session
        session.rollback()


@pytest.fixture()
def test_user(db):
    user = User(
        id=uuid.uuid4(),
        name=f"race-auto-{uuid.uuid4().hex[:8]}",
        is_active=True,
        created_at=datetime.datetime.now(_UTC),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_match_workout_to_race_accepts_10k_on_race_day():
    race_day = date(2026, 9, 6)
    assert match_workout_to_race(
        race_date=race_day,
        race_distance_km=10.0,
        race_status="planned",
        race_type="race",
        workout_date=race_day,
        workout_type="run",
        workout_distance_km=10.02,
    )


def test_match_workout_to_race_rejects_wrong_day():
    assert not match_workout_to_race(
        race_date=date(2026, 9, 6),
        race_distance_km=10.0,
        race_status="planned",
        race_type="race",
        workout_date=date(2026, 9, 7),
        workout_type="run",
        workout_distance_km=10.0,
    )


def test_match_workout_to_race_rejects_already_done():
    assert not match_workout_to_race(
        race_date=date(2026, 9, 27),
        race_distance_km=21.1,
        race_status="done",
        race_type="race",
        workout_date=date(2026, 9, 27),
        workout_type="run",
        workout_distance_km=21.45,
    )


def test_match_workout_to_race_accepts_half_with_gps_slack():
    race_day = date(2026, 9, 27)
    assert match_workout_to_race(
        race_date=race_day,
        race_distance_km=21.1,
        race_status="planned",
        race_type="race",
        workout_date=race_day,
        workout_type="run",
        workout_distance_km=21.45,
    )


def test_apply_race_autocomplete_marks_planned_race_done(db, test_user):
    race_day = date(2026, 9, 6)
    race = Race(
        id=uuid.uuid4(),
        user_id=test_user.id,
        name="KFC Run 10K",
        race_date=race_day,
        distance_km=10.0,
        race_type="race",
        status="planned",
        priority="B",
    )
    workout = Workout(
        id=uuid.uuid4(),
        user_id=test_user.id,
        workout_date=race_day,
        name="KFC Run",
        workout_type="run",
        distance_km=10.02,
        duration_seconds=3238,
    )
    db.add_all([race, workout])
    db.commit()

    assert apply_race_autocomplete_for_workout(db, workout) is True
    db.commit()
    db.refresh(race)

    assert race.status == "done"
    assert race.actual_time_seconds == 3238


def test_backfill_planned_races_heals_past_races(db, test_user):
    race_day = date(2026, 9, 27)
    race = Race(
        id=uuid.uuid4(),
        user_id=test_user.id,
        name="BA Chiang Mai Half",
        race_date=race_day,
        distance_km=21.1,
        race_type="race",
        status="planned",
        priority="A",
    )
    workout = Workout(
        id=uuid.uuid4(),
        user_id=test_user.id,
        workout_date=race_day,
        name="BA Half",
        workout_type="run",
        distance_km=21.45,
        duration_seconds=7166,
    )
    db.add_all([race, workout])
    db.commit()

    updated = backfill_planned_races(db, test_user.id)
    assert updated == 1
    db.commit()
    db.refresh(race)

    assert race.status == "done"
    assert race.actual_time_seconds == 7166
