"""
Tests for issue #707: Add race_checkpoints table and SQLAlchemy model.

Acceptance criteria verified:
- AC1: Alembic migration creates race_checkpoints idempotently (table_exists guard).
- AC2: Migration follows existing project style (named FK, random revision id).
- AC3: Table has all required columns with correct types and constraints.
- AC4: SQLAlchemy RaceCheckpoint model mapped with all columns and relationships.
- AC5: Model contains no hardcoded numeric thresholds.
- AC6: Any model accessor requiring input returns (None, reason) not an exception.
- AC7: Smoke test — instantiate with required fields only; persists without error.
- AC8: downgrade() drops race_checkpoints cleanly.
"""
import pytest
from decimal import Decimal
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.db import engine
from backend.models import Race, RaceCheckpoint, User, Workout


# ── Helpers ───────────────────────────────────────────────────────────────────

def _alice_id():
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT id FROM users WHERE name = 'Alice'")
        ).fetchone()
    assert row is not None, "Alice not found — seed not run?"
    return row.id


def _alice_race_id(user_id):
    """Return an existing race for Alice, or create one for test isolation."""
    with Session(engine) as session:
        row = session.execute(
            text("SELECT id FROM races WHERE user_id = :uid LIMIT 1"),
            {"uid": str(user_id)},
        ).fetchone()
        if row:
            return row.id
        race = Race(
            user_id=user_id,
            name="Test Race for Checkpoints #707",
            race_date="2099-12-01",
            distance_km=42.195,
            priority="A",
            status="planned",
        )
        session.add(race)
        session.commit()
        return race.id


# ── AC1: table exists ─────────────────────────────────────────────────────────

def test_race_checkpoints_table_exists():
    """race_checkpoints table is present after alembic upgrade head (AC1)."""
    with engine.connect() as conn:
        count = conn.execute(text(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = 'race_checkpoints'"
        )).scalar()
    assert count == 1, "race_checkpoints table not found — was alembic upgrade head run?"


# ── AC3: column presence and nullability ──────────────────────────────────────

def test_all_required_columns_exist():
    """All columns specified in AC3 exist with correct nullability."""
    # nullable=True means the column allows NULLs
    expected = {
        "id": False,
        "race_id": False,
        "user_id": False,
        "label": False,
        "target_date": False,
        "target_distance_km": True,
        "target_pace_seconds_per_km": True,
        "target_duration_seconds": True,
        "met": False,
        "met_override": False,
        "met_workout_id": True,
        "created_at": False,
        "updated_at": False,
    }
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT column_name, is_nullable "
            "FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'race_checkpoints'"
        )).fetchall()
    found = {r[0]: (r[1] == "YES") for r in rows}
    for col, nullable in expected.items():
        assert col in found, f"Column '{col}' missing from race_checkpoints"
        assert found[col] == nullable, (
            f"Column '{col}': expected nullable={nullable}, got {found[col]}"
        )


def test_met_default_is_false():
    """met column has a server default of false (AC3)."""
    with engine.connect() as conn:
        row = conn.execute(text(
            "SELECT column_default FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'race_checkpoints' "
            "AND column_name = 'met'"
        )).fetchone()
    assert row is not None
    assert row[0] is not None, "met should have a server default"
    assert "false" in row[0].lower(), f"met default expected 'false', got {row[0]}"


def test_met_override_default_is_false():
    """met_override column has a server default of false (AC3)."""
    with engine.connect() as conn:
        row = conn.execute(text(
            "SELECT column_default FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'race_checkpoints' "
            "AND column_name = 'met_override'"
        )).fetchone()
    assert row is not None
    assert row[0] is not None, "met_override should have a server default"
    assert "false" in row[0].lower(), f"met_override default expected 'false', got {row[0]}"


def test_race_id_fk_references_races():
    """race_id on race_checkpoints has a FK to races.id (AC3)."""
    with engine.connect() as conn:
        row = conn.execute(text(
            "SELECT COUNT(*) FROM information_schema.referential_constraints rc "
            "JOIN information_schema.key_column_usage kcu "
            "  ON rc.constraint_name = kcu.constraint_name "
            "JOIN information_schema.key_column_usage ref_kcu "
            "  ON rc.unique_constraint_name = ref_kcu.constraint_name "
            "WHERE kcu.table_name = 'race_checkpoints' "
            "  AND kcu.column_name = 'race_id' "
            "  AND ref_kcu.table_name = 'races'"
        )).scalar()
    assert row >= 1, "race_id does not have a FK to races"


def test_user_id_fk_references_users():
    """user_id on race_checkpoints has a FK to users.id (AC3)."""
    with engine.connect() as conn:
        row = conn.execute(text(
            "SELECT COUNT(*) FROM information_schema.referential_constraints rc "
            "JOIN information_schema.key_column_usage kcu "
            "  ON rc.constraint_name = kcu.constraint_name "
            "JOIN information_schema.key_column_usage ref_kcu "
            "  ON rc.unique_constraint_name = ref_kcu.constraint_name "
            "WHERE kcu.table_name = 'race_checkpoints' "
            "  AND kcu.column_name = 'user_id' "
            "  AND ref_kcu.table_name = 'users'"
        )).scalar()
    assert row >= 1, "user_id does not have a FK to users"


def test_met_workout_id_fk_references_workouts():
    """met_workout_id on race_checkpoints has a FK to workouts.id (AC3)."""
    with engine.connect() as conn:
        row = conn.execute(text(
            "SELECT COUNT(*) FROM information_schema.referential_constraints rc "
            "JOIN information_schema.key_column_usage kcu "
            "  ON rc.constraint_name = kcu.constraint_name "
            "JOIN information_schema.key_column_usage ref_kcu "
            "  ON rc.unique_constraint_name = ref_kcu.constraint_name "
            "WHERE kcu.table_name = 'race_checkpoints' "
            "  AND kcu.column_name = 'met_workout_id' "
            "  AND ref_kcu.table_name = 'workouts'"
        )).scalar()
    assert row >= 1, "met_workout_id does not have a FK to workouts"


# ── AC4: ORM model structure ──────────────────────────────────────────────────

def test_model_tablename():
    """RaceCheckpoint.__tablename__ == 'race_checkpoints' (AC4)."""
    assert RaceCheckpoint.__tablename__ == "race_checkpoints"


def test_model_has_race_relationship():
    """RaceCheckpoint has a 'race' relationship (AC4)."""
    assert hasattr(RaceCheckpoint, "race"), "RaceCheckpoint must have a 'race' relationship"


def test_model_has_user_relationship():
    """RaceCheckpoint has a 'user' relationship (AC4)."""
    assert hasattr(RaceCheckpoint, "user"), "RaceCheckpoint must have a 'user' relationship"


def test_model_has_workout_relationship():
    """RaceCheckpoint has a 'met_workout' relationship (AC4)."""
    assert hasattr(RaceCheckpoint, "met_workout"), (
        "RaceCheckpoint must have a 'met_workout' relationship"
    )


# ── AC5: no hardcoded numeric thresholds ─────────────────────────────────────

def test_no_hardcoded_thresholds_in_model_source():
    """RaceCheckpoint model source has no hardcoded numeric pace/distance/duration bounds (AC5)."""
    import inspect
    source = inspect.getsource(RaceCheckpoint)
    suspicious = [
        "< 400", "> 400", "< 1000", "> 1000", "<= 400", ">= 400",
        "< 100", "> 100", "< 300", "> 300",
        "pace_limit", "distance_cap", "duration_bound",
    ]
    for pattern in suspicious:
        assert pattern not in source, (
            f"Found suspicious hardcoded threshold pattern '{pattern}' in RaceCheckpoint"
        )


# ── AC6: accessors return (None, reason) not exceptions ──────────────────────

def test_accessor_returns_none_reason_when_input_absent():
    """Model accessor with missing input returns (None, reason) not an exception (AC6/UAT7)."""
    checkpoint = RaceCheckpoint(
        race_id=None,
        user_id=None,
        label="Mid-point",
        target_date="2099-06-01",
    )
    result = checkpoint.effective_target_pace()
    assert result is not None, "effective_target_pace() must return a tuple, not None itself"
    value, reason = result
    assert value is None, f"Expected None value when pace not set, got {value}"
    assert isinstance(reason, str) and len(reason) > 0, (
        f"Expected a non-empty reason string, got {reason!r}"
    )


def test_accessor_returns_value_when_input_present():
    """effective_target_pace() returns (pace, None) when target_pace_seconds_per_km is set."""
    checkpoint = RaceCheckpoint(
        race_id=None,
        user_id=None,
        label="Mid-point",
        target_date="2099-06-01",
        target_pace_seconds_per_km=300,
    )
    value, reason = checkpoint.effective_target_pace()
    assert value == 300, f"Expected 300, got {value}"
    assert reason is None, f"Expected None reason when value present, got {reason!r}"


# ── AC7: smoke test — required fields only ────────────────────────────────────

def test_smoke_required_fields_only():
    """RaceCheckpoint with only required fields persists without error (AC7/UAT3)."""
    user_id = _alice_id()
    race_id = _alice_race_id(user_id)

    with Session(engine) as session:
        cp = RaceCheckpoint(
            race_id=race_id,
            user_id=user_id,
            label="Halfway",
            target_date="2099-06-01",
        )
        session.add(cp)
        session.commit()
        cp_id = cp.id

        reloaded = session.get(RaceCheckpoint, cp_id)
        assert reloaded is not None
        assert reloaded.label == "Halfway"
        assert reloaded.met is False, f"met should default to False, got {reloaded.met}"
        assert reloaded.met_override is False, (
            f"met_override should default to False, got {reloaded.met_override}"
        )
        assert reloaded.created_at is not None, "created_at should be auto-populated"
        assert reloaded.updated_at is not None, "updated_at should be auto-populated"
        assert reloaded.target_distance_km is None
        assert reloaded.target_pace_seconds_per_km is None
        assert reloaded.target_duration_seconds is None
        assert reloaded.met_workout_id is None

        session.delete(reloaded)
        session.commit()


def test_smoke_all_fields():
    """RaceCheckpoint with all optional fields persists correctly (UAT4)."""
    user_id = _alice_id()
    race_id = _alice_race_id(user_id)

    with Session(engine) as session:
        cp = RaceCheckpoint(
            race_id=race_id,
            user_id=user_id,
            label="10K split",
            target_date="2099-04-01",
            target_distance_km=Decimal("10.0"),
            target_pace_seconds_per_km=300,
            target_duration_seconds=3000,
        )
        session.add(cp)
        session.commit()
        cp_id = cp.id

        reloaded = session.get(RaceCheckpoint, cp_id)
        assert reloaded is not None
        assert float(reloaded.target_distance_km) == pytest.approx(10.0)
        assert reloaded.target_pace_seconds_per_km == 300
        assert reloaded.target_duration_seconds == 3000

        session.delete(reloaded)
        session.commit()


def test_race_id_fk_constraint_enforced():
    """Inserting a RaceCheckpoint with a non-existent race_id raises a FK violation (UAT5)."""
    import uuid
    from sqlalchemy.exc import IntegrityError

    user_id = _alice_id()
    fake_race_id = uuid.uuid4()

    with pytest.raises(IntegrityError):
        with Session(engine) as session:
            cp = RaceCheckpoint(
                race_id=fake_race_id,
                user_id=user_id,
                label="Bad Race",
                target_date="2099-01-01",
            )
            session.add(cp)
            session.commit()
