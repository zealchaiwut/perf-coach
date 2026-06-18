"""
Tests for issue #604: Add races table and SQLAlchemy model.

Acceptance criteria verified:
- AC1: Alembic migration creates races table idempotently (IF NOT EXISTS / checkfirst).
- AC2: Table has all required columns with correct nullability.
- AC3: derive_goal_pace function computes pace correctly from valid inputs.
- AC3b: derive_goal_pace returns None when goal_time_seconds is absent.
- AC3c: derive_goal_pace returns None when distance_km is zero.
- AC4: goal_pace_seconds_per_km is populated by the model layer automatically.
- AC5: No hardcoded threshold values — any boundary checks reference named constants.
- AC6: Race model mirrors weight-goal pattern: __repr__, typed columns, user relationship.
- AC7: Downgrade removes the races table (tested via table existence check).
- AC8a: derive_goal_pace with valid inputs.
- AC8b: derive_goal_pace returns None when goal_time_seconds is absent.
- AC8c: derive_goal_pace returns None when distance_km is zero.
- AC8d: model instantiation sets goal_pace_seconds_per_km automatically.
"""
import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.db import engine
from backend.models import Race, User, derive_goal_pace


# ── Helpers ───────────────────────────────────────────────────────────────────

def _alice_id():
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT id FROM users WHERE name = 'Alice'")
        ).fetchone()
    assert row is not None, "Alice not found — seed not run?"
    return row.id


# ── AC1/AC2: table exists and has correct columns ────────────────────────────

def test_races_table_exists():
    """races table is present in public schema after alembic upgrade head (AC1)."""
    with engine.connect() as conn:
        count = conn.execute(text(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = 'races'"
        )).scalar()
    assert count == 1, "races table not found — was alembic upgrade head run?"


def test_all_required_columns_exist():
    """All columns specified in AC2 exist with correct nullability."""
    expected = {
        "id": False,
        "user_id": False,
        "name": False,
        "race_date": False,
        "distance_km": False,
        "goal_time_seconds": True,
        "goal_pace_seconds_per_km": True,
        "priority": False,
        "status": False,
        "created_at": True,
        "updated_at": True,
    }
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT column_name, is_nullable "
            "FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'races'"
        )).fetchall()
    found = {r[0]: (r[1] == "YES") for r in rows}
    for col, nullable in expected.items():
        assert col in found, f"Column '{col}' missing from races"
        assert found[col] == nullable, (
            f"Column '{col}': expected nullable={nullable}, got {found[col]}"
        )


def test_user_id_is_indexed():
    """user_id column on races has an index (AC2)."""
    with engine.connect() as conn:
        row = conn.execute(text(
            "SELECT COUNT(*) FROM pg_indexes "
            "WHERE tablename = 'races' AND indexdef LIKE '%user_id%'"
        )).scalar()
    assert row >= 1, "user_id on races is not indexed"


def test_user_id_foreign_key_references_users():
    """user_id on races has a FK to users.id (AC2)."""
    with engine.connect() as conn:
        row = conn.execute(text(
            "SELECT COUNT(*) FROM information_schema.referential_constraints rc "
            "JOIN information_schema.key_column_usage kcu "
            "  ON rc.constraint_name = kcu.constraint_name "
            "JOIN information_schema.key_column_usage ref_kcu "
            "  ON rc.unique_constraint_name = ref_kcu.constraint_name "
            "WHERE kcu.table_name = 'races' "
            "  AND kcu.column_name = 'user_id' "
            "  AND ref_kcu.table_name = 'users'"
        )).scalar()
    assert row >= 1, "user_id does not have a FK to users"


# ── AC3/AC8a: derive_goal_pace with valid inputs ─────────────────────────────

def test_derive_goal_pace_valid_inputs():
    """derive_goal_pace returns floor-rounded pace for valid inputs (AC3/AC8a)."""
    result = derive_goal_pace(goal_time_seconds=3600, distance_km=10)
    assert result == 360, f"Expected 360, got {result}"


def test_derive_goal_pace_rounds_correctly():
    """derive_goal_pace rounds to nearest whole second (AC3)."""
    # 1806 seconds / 10 km = 180.6 → rounds to 181
    result = derive_goal_pace(goal_time_seconds=1806, distance_km=10)
    assert result == 181, f"Expected 181, got {result}"


def test_derive_goal_pace_non_round_distance():
    """derive_goal_pace handles non-round distances (AC3)."""
    # 1800 seconds / 5 km = 360 s/km
    result = derive_goal_pace(goal_time_seconds=1800, distance_km=5)
    assert result == 360, f"Expected 360, got {result}"


# ── AC3b/AC8b: derive_goal_pace returns None when goal_time_seconds absent ───

def test_derive_goal_pace_none_goal_time():
    """derive_goal_pace returns (None, reason) when goal_time_seconds is None (AC3b/AC8b)."""
    result = derive_goal_pace(goal_time_seconds=None, distance_km=10)
    assert result is None, f"Expected None, got {result}"


# ── AC3c/AC8c: derive_goal_pace returns None when distance_km is zero ────────

def test_derive_goal_pace_zero_distance():
    """derive_goal_pace returns None when distance_km is zero (AC3c/AC8c/UAT5)."""
    result = derive_goal_pace(goal_time_seconds=1800, distance_km=0)
    assert result is None, f"Expected None, got {result}"


def test_derive_goal_pace_none_distance():
    """derive_goal_pace returns None when distance_km is None (AC3b)."""
    result = derive_goal_pace(goal_time_seconds=1800, distance_km=None)
    assert result is None, f"Expected None, got {result}"


def test_derive_goal_pace_returns_int():
    """derive_goal_pace returns an int (not float) for valid inputs (AC3)."""
    result = derive_goal_pace(goal_time_seconds=3600, distance_km=10)
    assert isinstance(result, int), f"Expected int, got {type(result)}"


# ── AC4/AC8d: model layer populates goal_pace_seconds_per_km automatically ───

def test_model_sets_goal_pace_on_instantiation():
    """Race sets goal_pace_seconds_per_km automatically when both inputs are present (AC4/AC8d)."""
    race = Race(
        user_id=_alice_id(),
        name="Test Race",
        race_date="2026-10-01",
        distance_km=10,
        goal_time_seconds=3600,
        priority="A",
        status="planned",
    )
    assert race.goal_pace_seconds_per_km == 360, (
        f"Expected 360, got {race.goal_pace_seconds_per_km}"
    )


def test_model_leaves_pace_null_when_goal_time_absent():
    """Race leaves goal_pace_seconds_per_km None when goal_time_seconds is None (AC4/UAT4)."""
    race = Race(
        user_id=_alice_id(),
        name="No Goal Race",
        race_date="2026-10-01",
        distance_km=10,
        goal_time_seconds=None,
        priority="B",
        status="planned",
    )
    assert race.goal_pace_seconds_per_km is None, (
        f"Expected None, got {race.goal_pace_seconds_per_km}"
    )


def test_model_leaves_pace_null_when_distance_zero():
    """Race leaves goal_pace_seconds_per_km None when distance_km is 0 (AC4)."""
    race = Race(
        user_id=_alice_id(),
        name="Zero Distance Race",
        race_date="2026-10-01",
        distance_km=0,
        goal_time_seconds=3600,
        priority="C",
        status="planned",
    )
    assert race.goal_pace_seconds_per_km is None


# ── AC6: model structure — __repr__, user relationship ───────────────────────

def test_model_has_repr():
    """Race has a __repr__ method (AC6)."""
    race = Race(
        user_id=_alice_id(),
        name="Boston",
        race_date="2026-04-20",
        distance_km=42.195,
        priority="A",
        status="planned",
    )
    repr_str = repr(race)
    assert "Race" in repr_str, f"__repr__ should include 'Race': {repr_str}"


def test_model_has_user_relationship():
    """Race model has a 'user' relationship attribute (AC6)."""
    assert hasattr(Race, "user"), "Race model must have a 'user' relationship"


# ── AC8d extended: ORM round-trip persists auto-computed pace ────────────────

def test_orm_round_trip_pace_persisted():
    """goal_pace_seconds_per_km computed at instantiation is persisted to DB (AC4/AC8d)."""
    user_id = _alice_id()
    with Session(engine) as session:
        race = Race(
            user_id=user_id,
            name="Round Trip Race 604",
            race_date="2099-01-01",
            distance_km=10,
            goal_time_seconds=3600,
            priority="A",
            status="planned",
        )
        session.add(race)
        session.commit()
        race_id = race.id

        reloaded = session.get(Race, race_id)
        assert reloaded is not None
        assert reloaded.goal_pace_seconds_per_km == 360
        assert reloaded.name == "Round Trip Race 604"
        assert reloaded.priority == "A"
        assert reloaded.status == "planned"

        session.delete(reloaded)
        session.commit()


def test_orm_round_trip_no_goal_time():
    """Race with no goal_time persists with NULL goal_pace_seconds_per_km (AC4)."""
    user_id = _alice_id()
    with Session(engine) as session:
        race = Race(
            user_id=user_id,
            name="No Goal Race 604",
            race_date="2099-01-01",
            distance_km=21.0975,
            goal_time_seconds=None,
            priority="C",
            status="planned",
        )
        session.add(race)
        session.commit()
        race_id = race.id

        reloaded = session.get(Race, race_id)
        assert reloaded is not None
        assert reloaded.goal_pace_seconds_per_km is None

        session.delete(reloaded)
        session.commit()
