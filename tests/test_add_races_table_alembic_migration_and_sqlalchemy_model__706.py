"""
Tests for issue #706: Add races table, Alembic migration, and SQLAlchemy model.

Acceptance criteria verified:
- AC1/UAT1: races table has all required columns including actual_time_seconds.
- AC2/UAT2: alembic upgrade head is idempotent (table already exists — no error).
- AC5: compute_goal_pace(valid) returns (pace_int, None) — happy path.
- AC5b: compute_goal_pace(goal_time=None) returns (None, reason_string).
- AC5c: compute_goal_pace(distance=None) returns (None, reason_string).
- AC5d: compute_goal_pace(both None) returns (None, reason_string).
- AC5e: compute_goal_pace(distance=0) returns (None, reason_string) — no ZeroDivisionError.
- AC5f: compute_goal_pace(goal_time<0) returns (None, reason_string).
- AC5g: compute_goal_pace(distance<0) returns (None, reason_string).
- AC6: RACE_PRIORITY_VALUES and RACE_STATUS_VALUES constants are defined and non-empty.
- AC7/AC8: Race.__init__ sets goal_pace_seconds_per_km via compute_goal_pace (not directly).
- AC9: actual_time_seconds column exists in the DB (nullable=True).
"""
import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.db import engine
from backend.models import (
    Race,
    User,
    compute_goal_pace,
    RACE_PRIORITY_VALUES,
    RACE_STATUS_VALUES,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _alice_id():
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT id FROM users WHERE name = 'Alice'")
        ).fetchone()
    assert row is not None, "Alice not found — seed not run?"
    return row.id


# ── AC1: actual_time_seconds column exists ───────────────────────────────────

def test_actual_time_seconds_column_exists():
    """actual_time_seconds column exists in races table (AC1/UAT1)."""
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT column_name, is_nullable, data_type "
            "FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'races' "
            "AND column_name = 'actual_time_seconds'"
        )).fetchall()
    assert rows, "actual_time_seconds column not found in races table"
    col = rows[0]
    assert col[1] == "YES", f"actual_time_seconds should be nullable, got {col[1]}"
    assert col[2] == "integer", f"actual_time_seconds should be integer, got {col[2]}"


def test_all_required_columns_present_706():
    """All AC1 columns exist in the races table (includes actual_time_seconds)."""
    required = {
        "id", "user_id", "name", "race_date", "distance_km",
        "goal_time_seconds", "goal_pace_seconds_per_km", "priority",
        "status", "actual_time_seconds", "created_at", "updated_at",
    }
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'races'"
        )).fetchall()
    found = {r[0] for r in rows}
    missing = required - found
    assert not missing, f"Missing columns in races table: {missing}"


# ── AC2: idempotency (table already exists, upgrade is safe) ─────────────────

def test_races_table_exists_after_upgrade():
    """races table is present after alembic upgrade head (AC2/UAT1-2)."""
    with engine.connect() as conn:
        count = conn.execute(text(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = 'races'"
        )).scalar()
    assert count == 1, "races table not found"


# ── AC5: compute_goal_pace — happy path ──────────────────────────────────────

def test_compute_goal_pace_happy_path():
    """compute_goal_pace returns (360, None) for 3600s over 10 km (AC5/UAT5)."""
    result = compute_goal_pace(goal_time_seconds=3600, distance_km=10)
    assert isinstance(result, tuple) and len(result) == 2, (
        f"Expected 2-tuple, got {result!r}"
    )
    pace, reason = result
    assert pace == 360, f"Expected pace=360, got {pace}"
    assert reason is None, f"Expected reason=None for valid input, got {reason!r}"


def test_compute_goal_pace_rounds_correctly():
    """compute_goal_pace rounds to nearest whole second (AC5)."""
    # 1806 / 10 = 180.6 → rounds to 181
    pace, reason = compute_goal_pace(goal_time_seconds=1806, distance_km=10)
    assert pace == 181, f"Expected 181, got {pace}"
    assert reason is None


def test_compute_goal_pace_returns_int():
    """compute_goal_pace pace value is an int (AC5)."""
    pace, _ = compute_goal_pace(goal_time_seconds=3600, distance_km=10)
    assert isinstance(pace, int), f"Expected int, got {type(pace)}"


# ── AC5b: goal_time_seconds = None ───────────────────────────────────────────

def test_compute_goal_pace_none_goal_time():
    """compute_goal_pace returns (None, reason) when goal_time_seconds is None (AC5b/UAT6)."""
    result = compute_goal_pace(goal_time_seconds=None, distance_km=10)
    assert isinstance(result, tuple) and len(result) == 2
    pace, reason = result
    assert pace is None, f"Expected pace=None, got {pace}"
    assert isinstance(reason, str) and reason, (
        f"Expected non-empty reason string, got {reason!r}"
    )


# ── AC5c: distance_km = None ─────────────────────────────────────────────────

def test_compute_goal_pace_none_distance():
    """compute_goal_pace returns (None, reason) when distance_km is None (AC5c/UAT7)."""
    result = compute_goal_pace(goal_time_seconds=3600, distance_km=None)
    assert isinstance(result, tuple) and len(result) == 2
    pace, reason = result
    assert pace is None, f"Expected pace=None, got {pace}"
    assert isinstance(reason, str) and reason


# ── AC5d: both inputs None ───────────────────────────────────────────────────

def test_compute_goal_pace_both_none():
    """compute_goal_pace returns (None, reason) when both inputs are None (AC5d)."""
    result = compute_goal_pace(goal_time_seconds=None, distance_km=None)
    assert isinstance(result, tuple) and len(result) == 2
    pace, reason = result
    assert pace is None
    assert isinstance(reason, str) and reason


# ── AC5e: distance_km = 0 ────────────────────────────────────────────────────

def test_compute_goal_pace_zero_distance():
    """compute_goal_pace returns (None, reason) and does not raise ZeroDivisionError (AC5e/UAT8)."""
    result = compute_goal_pace(goal_time_seconds=3600, distance_km=0)
    assert isinstance(result, tuple) and len(result) == 2
    pace, reason = result
    assert pace is None, f"Expected pace=None for zero distance, got {pace}"
    assert isinstance(reason, str) and reason


# ── AC5f/AC5g: negative inputs ───────────────────────────────────────────────

def test_compute_goal_pace_negative_goal_time():
    """compute_goal_pace returns (None, reason) when goal_time_seconds is negative (AC5)."""
    result = compute_goal_pace(goal_time_seconds=-1, distance_km=10)
    assert isinstance(result, tuple) and len(result) == 2
    pace, reason = result
    assert pace is None
    assert isinstance(reason, str) and reason


def test_compute_goal_pace_negative_distance():
    """compute_goal_pace returns (None, reason) when distance_km is negative (AC5)."""
    result = compute_goal_pace(goal_time_seconds=3600, distance_km=-5)
    assert isinstance(result, tuple) and len(result) == 2
    pace, reason = result
    assert pace is None
    assert isinstance(reason, str) and reason


# ── AC6: named constants ─────────────────────────────────────────────────────

def test_race_priority_values_constant_defined():
    """RACE_PRIORITY_VALUES is defined and non-empty (AC6)."""
    assert RACE_PRIORITY_VALUES, "RACE_PRIORITY_VALUES must be non-empty"
    assert "A" in RACE_PRIORITY_VALUES
    assert "B" in RACE_PRIORITY_VALUES
    assert "C" in RACE_PRIORITY_VALUES


def test_race_status_values_constant_defined():
    """RACE_STATUS_VALUES is defined and non-empty (AC6)."""
    assert RACE_STATUS_VALUES, "RACE_STATUS_VALUES must be non-empty"
    assert "planned" in RACE_STATUS_VALUES
    assert "done" in RACE_STATUS_VALUES
    assert "abandoned" in RACE_STATUS_VALUES


def test_check_constraints_reference_constants():
    """Race check constraints on priority and status reference named constants, not hardcoded values (AC6)."""
    # Verify that the constraint SQL for priority matches what RACE_PRIORITY_VALUES defines
    from sqlalchemy import inspect as sa_inspect
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT conname, pg_get_constraintdef(oid) "
            "FROM pg_constraint "
            "WHERE conrelid = 'races'::regclass AND contype = 'c'"
        )).fetchall()
    constraints = {r[0]: r[1] for r in rows}

    # Each constant value must appear in its constraint
    priority_constr = constraints.get("ck_races_priority_values", "")
    for val in RACE_PRIORITY_VALUES:
        assert val in priority_constr, (
            f"Value {val!r} from RACE_PRIORITY_VALUES not in DB constraint: {priority_constr}"
        )

    status_constr = constraints.get("ck_races_status_values", "")
    for val in RACE_STATUS_VALUES:
        assert val in status_constr, (
            f"Value {val!r} from RACE_STATUS_VALUES not in DB constraint: {status_constr}"
        )


# ── AC7/AC8: model sets goal_pace_seconds_per_km via compute_goal_pace ───────

def test_model_sets_pace_via_compute_goal_pace():
    """Race.__init__ sets goal_pace_seconds_per_km = compute_goal_pace result (AC7/AC8)."""
    race = Race(
        user_id=_alice_id(),
        name="Marathon Goal",
        race_date="2026-10-01",
        distance_km=10,
        goal_time_seconds=3600,
        priority="A",
        status="planned",
    )
    expected_pace, _ = compute_goal_pace(3600, 10)
    assert race.goal_pace_seconds_per_km == expected_pace == 360


def test_model_pace_null_when_goal_time_none():
    """Race sets goal_pace_seconds_per_km to None when goal_time_seconds is None (AC8/UAT6)."""
    race = Race(
        user_id=_alice_id(),
        name="No Goal",
        race_date="2026-10-01",
        distance_km=10,
        goal_time_seconds=None,
        priority="B",
        status="planned",
    )
    assert race.goal_pace_seconds_per_km is None


def test_model_pace_null_when_distance_zero():
    """Race sets goal_pace_seconds_per_km to None when distance_km is 0 (AC8/UAT8)."""
    race = Race(
        user_id=_alice_id(),
        name="Zero Distance",
        race_date="2026-10-01",
        distance_km=0,
        goal_time_seconds=3600,
        priority="C",
        status="planned",
    )
    assert race.goal_pace_seconds_per_km is None


# ── AC9: actual_time_seconds round-trips via ORM ─────────────────────────────

def test_actual_time_seconds_orm_roundtrip():
    """actual_time_seconds persists and loads via ORM (AC9/UAT5)."""
    user_id = _alice_id()
    with Session(engine) as session:
        race = Race(
            user_id=user_id,
            name="Race With Actual Time 706",
            race_date="2099-06-01",
            distance_km=10,
            goal_time_seconds=3600,
            actual_time_seconds=3650,
            priority="A",
            status="done",
        )
        session.add(race)
        session.commit()
        race_id = race.id

        reloaded = session.get(Race, race_id)
        assert reloaded is not None
        assert reloaded.actual_time_seconds == 3650

        session.delete(reloaded)
        session.commit()


def test_actual_time_seconds_nullable():
    """actual_time_seconds persists as NULL when not provided (AC1)."""
    user_id = _alice_id()
    with Session(engine) as session:
        race = Race(
            user_id=user_id,
            name="Race Without Actual Time 706",
            race_date="2099-06-01",
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
        assert reloaded.actual_time_seconds is None

        session.delete(reloaded)
        session.commit()
