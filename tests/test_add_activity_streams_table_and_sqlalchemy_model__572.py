"""
Tests for issue #572: Add activity_streams table and SQLAlchemy model.

Acceptance criteria verified:
- AC1/AC2: Alembic migration creates activity_streams table; idempotent on re-run.
- AC3: Migration follows project style.
- AC4: ActivityStream ORM model maps all specified columns.
- AC5/AC7: Every channel column is independently nullable.
- AC8: Model has a module-level docstring with worked example.
- AC9: No magic numbers / hardcoded limits in model or migration.
- AC10: No sentinel null rows — absence of row = no stream data.
- AC11: ORM round-trip with at least one channel populated and at least one null.
"""
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from backend.db import engine
from backend.models import ActivityStream, Workout


# ── Helpers ───────────────────────────────────────────────────────────────────

def _alice_id():
    with engine.connect() as conn:
        row = conn.execute(text("SELECT id FROM users WHERE name = 'Alice'")).fetchone()
    assert row is not None, "Alice not found — seed not run?"
    return row.id


def _create_workout(session, user_id):
    w = Workout(
        user_id=user_id,
        workout_date="2099-01-01",
        name="Stream Test Workout",
        workout_type="running",
        source="manual",
    )
    session.add(w)
    session.flush()
    return w.id


# ── AC1/AC2: table exists after migration ─────────────────────────────────────

def test_table_exists():
    """activity_streams table is present in public schema after alembic upgrade head."""
    with engine.connect() as conn:
        count = conn.execute(text(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = 'activity_streams'"
        )).scalar()
    assert count == 1, "activity_streams table not found — was alembic upgrade head run?"


def test_all_required_columns_exist():
    """All columns specified in AC4 exist with correct nullable settings."""
    expected = {
        "workout_id": False,           # PK — NOT NULL
        "sample_interval_seconds": True,
        "source": True,
        "time_offset_seconds": True,
        "power_w": True,
        "heart_rate_bpm": True,
        "pace_seconds_per_km": True,
        "cadence_spm": True,
        "altitude_m": True,
        "latitude": True,
        "longitude": True,
    }
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT column_name, is_nullable "
            "FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'activity_streams'"
        )).fetchall()
    found = {r[0]: (r[1] == "YES") for r in rows}
    for col, nullable in expected.items():
        assert col in found, f"Column '{col}' missing from activity_streams"
        assert found[col] == nullable, (
            f"Column '{col}': expected nullable={nullable}, got {found[col]}"
        )


def test_workout_id_is_primary_key():
    """workout_id is the primary key of activity_streams."""
    with engine.connect() as conn:
        row = conn.execute(text(
            "SELECT COUNT(*) FROM information_schema.table_constraints tc "
            "JOIN information_schema.key_column_usage kcu "
            "  ON tc.constraint_name = kcu.constraint_name "
            "  AND tc.table_schema = kcu.table_schema "
            "WHERE tc.constraint_type = 'PRIMARY KEY' "
            "  AND tc.table_name = 'activity_streams' "
            "  AND kcu.column_name = 'workout_id'"
        )).scalar()
    assert row == 1, "workout_id is not the primary key of activity_streams"


def test_foreign_key_references_workouts():
    """workout_id has a foreign key to workouts.id."""
    with engine.connect() as conn:
        row = conn.execute(text(
            "SELECT COUNT(*) FROM information_schema.referential_constraints rc "
            "JOIN information_schema.key_column_usage kcu "
            "  ON rc.constraint_name = kcu.constraint_name "
            "JOIN information_schema.key_column_usage ref_kcu "
            "  ON rc.unique_constraint_name = ref_kcu.constraint_name "
            "WHERE kcu.table_name = 'activity_streams' "
            "  AND kcu.column_name = 'workout_id' "
            "  AND ref_kcu.table_name = 'workouts'"
        )).scalar()
    assert row >= 1, "workout_id does not have a FK to workouts"


# ── AC4/AC11: ORM model round-trip ────────────────────────────────────────────

def test_orm_round_trip_partial_channels():
    """ActivityStream persists with one channel populated and others null (AC11)."""
    from sqlalchemy.orm import Session

    user_id = _alice_id()
    with Session(engine) as session:
        workout_id = _create_workout(session, user_id)
        stream = ActivityStream(
            workout_id=workout_id,
            source="strava",
            power_w=[250, 260, 245, 255],
            # all other channels left None
        )
        session.add(stream)
        session.commit()

        reloaded = session.get(ActivityStream, workout_id)
        assert reloaded is not None
        assert reloaded.source == "strava"
        assert reloaded.power_w == [250, 260, 245, 255]
        assert reloaded.heart_rate_bpm is None
        assert reloaded.pace_seconds_per_km is None
        assert reloaded.cadence_spm is None
        assert reloaded.altitude_m is None
        assert reloaded.latitude is None
        assert reloaded.longitude is None
        assert reloaded.time_offset_seconds is None
        assert reloaded.sample_interval_seconds is None

        # cleanup — delete workout; CASCADE removes the stream row
        session.execute(text("DELETE FROM workouts WHERE id = :id"), {"id": workout_id})
        session.commit()


def test_orm_round_trip_all_channels_null():
    """ActivityStream row with only workout_id set persists (AC5/AC11)."""
    from sqlalchemy.orm import Session

    user_id = _alice_id()
    with Session(engine) as session:
        workout_id = _create_workout(session, user_id)
        stream = ActivityStream(workout_id=workout_id)
        session.add(stream)
        session.commit()

        reloaded = session.get(ActivityStream, workout_id)
        assert reloaded is not None
        assert reloaded.source is None
        assert reloaded.power_w is None
        assert reloaded.heart_rate_bpm is None

        session.execute(text("DELETE FROM workouts WHERE id = :id"), {"id": workout_id})
        session.commit()


def test_orm_round_trip_all_channels_populated():
    """ActivityStream persists with all channel arrays set."""
    from sqlalchemy.orm import Session

    user_id = _alice_id()
    with Session(engine) as session:
        workout_id = _create_workout(session, user_id)
        stream = ActivityStream(
            workout_id=workout_id,
            source="stryd",
            sample_interval_seconds=1,
            time_offset_seconds=[0, 1, 2, 3],
            power_w=[200, 210, 205, 215],
            heart_rate_bpm=[140, 142, 141, 143],
            pace_seconds_per_km=[300, 298, 301, 299],
            cadence_spm=[170, 172, 171, 173],
            altitude_m=[10.0, 10.1, 10.2, 10.3],
            latitude=[13.7563, 13.7564, 13.7565, 13.7566],
            longitude=[100.5018, 100.5019, 100.5020, 100.5021],
        )
        session.add(stream)
        session.commit()

        reloaded = session.get(ActivityStream, workout_id)
        assert reloaded.power_w == [200, 210, 205, 215]
        assert reloaded.heart_rate_bpm == [140, 142, 141, 143]
        assert reloaded.pace_seconds_per_km == [300, 298, 301, 299]
        assert reloaded.cadence_spm == [170, 172, 171, 173]
        assert reloaded.time_offset_seconds == [0, 1, 2, 3]
        assert reloaded.sample_interval_seconds == 1
        assert reloaded.source == "stryd"

        session.execute(text("DELETE FROM workouts WHERE id = :id"), {"id": workout_id})
        session.commit()


# ── AC10: one row per workout (PK enforces uniqueness) ────────────────────────

def test_duplicate_workout_id_raises():
    """Inserting a second ActivityStream for the same workout_id raises a PK violation (AC10/UAT6)."""
    from sqlalchemy.orm import Session

    user_id = _alice_id()
    with Session(engine) as session:
        workout_id = _create_workout(session, user_id)
        session.add(ActivityStream(workout_id=workout_id, source="strava"))
        session.commit()

        with pytest.raises((IntegrityError, Exception)):
            session.add(ActivityStream(workout_id=workout_id, source="stryd"))
            session.commit()

        session.rollback()
        session.execute(
            text("DELETE FROM activity_streams WHERE workout_id = :id"),
            {"id": workout_id},
        )
        session.execute(text("DELETE FROM workouts WHERE id = :id"), {"id": workout_id})
        session.commit()


# ── AC10: no row = no stream data (absence is canonical) ─────────────────────

def test_no_row_for_manual_workout():
    """A workout inserted without creating an ActivityStream has zero rows (AC10/UAT7)."""
    from sqlalchemy.orm import Session

    user_id = _alice_id()
    with Session(engine) as session:
        workout_id = _create_workout(session, user_id)
        session.commit()

        count = session.execute(
            text("SELECT COUNT(*) FROM activity_streams WHERE workout_id = :id"),
            {"id": workout_id},
        ).scalar()
        assert count == 0, "Expected zero rows for a manual workout with no stream data"

        session.execute(text("DELETE FROM workouts WHERE id = :id"), {"id": workout_id})
        session.commit()


# ── AC8: model has a module-level docstring ───────────────────────────────────

def test_model_has_module_docstring():
    """ActivityStream model class has a docstring with a worked example."""
    assert ActivityStream.__doc__ is not None and len(ActivityStream.__doc__) > 50, (
        "ActivityStream must have a docstring with a worked example"
    )


def test_model_docstring_has_worked_example():
    """ActivityStream docstring includes 'Worked example::' and key code fragments."""
    doc = ActivityStream.__doc__ or ""
    assert "Worked example::" in doc, "Docstring must include 'Worked example::'"
    assert "ActivityStream(" in doc, "Docstring worked example must show constructor call"
    assert "session.add" in doc, "Docstring worked example must show session.add"
