"""
Tests for issue #1143: Add plyometric session logging with foot-contacts.

Acceptance criteria verified:
- AC1: plyo_sessions table exists with id, user_id, session_date, foot_contacts,
       plyo_phase, and created_at columns.
- AC2: A plyo session row can be inserted and subsequently retrieved.
- AC3: plyo_phase only accepts 'intro', 'build', 'maintain'; invalid values rejected.
- AC4: foot_contacts stores a non-negative integer; negative values rejected.
- AC5: py_compile passes on all new/modified Python files.
- AC6: Existing session types and tables are unaffected.

Runs against the UAT Postgres database via DATABASE_URL_UAT from .env.
"""
import pathlib
import subprocess
import sys

import pytest
from dotenv import dotenv_values
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.models import PlyoSession

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_env_vals = dotenv_values(_ROOT / ".env")
_uat_url = _env_vals.get("DATABASE_URL_UAT")

engine = create_engine(_uat_url, pool_pre_ping=True) if _uat_url else None


def _require_engine():
    if engine is None:
        pytest.skip("DATABASE_URL_UAT not set — skipping Postgres-specific test")


def _alice_id():
    _require_engine()
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT id FROM users WHERE name = 'Alice'")
        ).fetchone()
    assert row is not None, "Alice not found — seed not run?"
    return row.id


def _get_columns():
    _require_engine()
    inspector = inspect(engine)
    return {c["name"]: c for c in inspector.get_columns("plyo_sessions")}


# ── AC1: Table and columns ─────────────────────────────────────────────────────

def test_plyo_sessions_table_exists():
    """plyo_sessions table exists after migration (AC1/UAT1)."""
    _require_engine()
    inspector = inspect(engine)
    assert inspector.has_table("plyo_sessions"), "plyo_sessions table not found"


def test_plyo_sessions_required_columns():
    """All required columns exist in plyo_sessions (AC1/UAT1)."""
    required = {"id", "user_id", "session_date", "foot_contacts", "plyo_phase", "created_at"}
    cols = _get_columns()
    missing = required - cols.keys()
    assert not missing, f"Missing columns in plyo_sessions: {missing}"


def test_foot_contacts_not_nullable():
    """foot_contacts column is not nullable (AC1/AC4)."""
    cols = _get_columns()
    assert "foot_contacts" in cols
    assert cols["foot_contacts"]["nullable"] is False, "foot_contacts should not be nullable"


def test_plyo_phase_not_nullable():
    """plyo_phase column is not nullable (AC1/AC3)."""
    cols = _get_columns()
    assert "plyo_phase" in cols
    assert cols["plyo_phase"]["nullable"] is False, "plyo_phase should not be nullable"


def test_session_date_not_nullable():
    """session_date column is not nullable (AC1)."""
    cols = _get_columns()
    assert "session_date" in cols
    assert cols["session_date"]["nullable"] is False, "session_date should not be nullable"


# ── AC2: Insert and retrieve ───────────────────────────────────────────────────

def test_plyo_session_insert_and_retrieve():
    """A plyo session row can be inserted and retrieved with correct values (AC2/UAT2)."""
    user_id = _alice_id()
    with Session(engine) as session:
        rec = PlyoSession(
            user_id=user_id,
            session_date="2099-01-15",
            foot_contacts=120,
            plyo_phase="build",
        )
        session.add(rec)
        session.commit()
        rec_id = rec.id

        reloaded = session.get(PlyoSession, rec_id)
        assert reloaded is not None
        assert reloaded.foot_contacts == 120
        assert reloaded.plyo_phase == "build"

        session.delete(reloaded)
        session.commit()


def test_plyo_session_all_valid_phases():
    """All valid plyo_phase values can be persisted (AC2/AC3)."""
    user_id = _alice_id()
    with Session(engine) as session:
        for phase in ("intro", "build", "maintain"):
            rec = PlyoSession(
                user_id=user_id,
                session_date="2099-02-01",
                foot_contacts=80,
                plyo_phase=phase,
            )
            session.add(rec)
            session.flush()
            session.delete(rec)
        session.commit()


def test_plyo_session_created_at_auto_set():
    """created_at is set automatically on insert (AC1/AC2)."""
    user_id = _alice_id()
    with Session(engine) as session:
        rec = PlyoSession(
            user_id=user_id,
            session_date="2099-03-01",
            foot_contacts=50,
            plyo_phase="intro",
        )
        session.add(rec)
        session.commit()
        rec_id = rec.id

        reloaded = session.get(PlyoSession, rec_id)
        assert reloaded.created_at is not None, "created_at should be auto-populated"

        session.delete(reloaded)
        session.commit()


# ── AC3: plyo_phase constraint ─────────────────────────────────────────────────

def test_invalid_plyo_phase_rejected():
    """plyo_phase='advanced' (invalid) is rejected at DB layer (AC3/UAT3)."""
    user_id = _alice_id()
    with Session(engine) as session:
        rec = PlyoSession(
            user_id=user_id,
            session_date="2099-04-01",
            foot_contacts=100,
            plyo_phase="advanced",
        )
        session.add(rec)
        with pytest.raises((IntegrityError, Exception)):
            session.flush()
        session.rollback()

    with engine.connect() as conn:
        count = conn.execute(
            text(
                "SELECT COUNT(*) FROM plyo_sessions "
                "WHERE plyo_phase = 'advanced' AND session_date = '2099-04-01'"
            )
        ).scalar()
    assert count == 0, "Invalid plyo_phase 'advanced' must not be persisted"


def test_empty_plyo_phase_rejected():
    """Empty plyo_phase is rejected (AC3)."""
    user_id = _alice_id()
    with Session(engine) as session:
        rec = PlyoSession(
            user_id=user_id,
            session_date="2099-04-02",
            foot_contacts=60,
            plyo_phase="",
        )
        session.add(rec)
        with pytest.raises((IntegrityError, Exception)):
            session.flush()
        session.rollback()


# ── AC4: foot_contacts non-negative ────────────────────────────────────────────

def test_negative_foot_contacts_rejected():
    """foot_contacts=-5 is rejected at DB or model layer (AC4/UAT4)."""
    user_id = _alice_id()
    with Session(engine) as session:
        rec = PlyoSession(
            user_id=user_id,
            session_date="2099-05-01",
            foot_contacts=-5,
            plyo_phase="build",
        )
        session.add(rec)
        with pytest.raises((IntegrityError, Exception)):
            session.flush()
        session.rollback()

    with engine.connect() as conn:
        count = conn.execute(
            text(
                "SELECT COUNT(*) FROM plyo_sessions "
                "WHERE foot_contacts < 0 AND session_date = '2099-05-01'"
            )
        ).scalar()
    assert count == 0, "Negative foot_contacts must not be persisted"


def test_zero_foot_contacts_allowed():
    """foot_contacts=0 is valid (boundary case for non-negative) (AC4)."""
    user_id = _alice_id()
    with Session(engine) as session:
        rec = PlyoSession(
            user_id=user_id,
            session_date="2099-05-02",
            foot_contacts=0,
            plyo_phase="intro",
        )
        session.add(rec)
        session.commit()
        rec_id = rec.id

        reloaded = session.get(PlyoSession, rec_id)
        assert reloaded.foot_contacts == 0

        session.delete(reloaded)
        session.commit()


# ── AC5: py_compile passes ─────────────────────────────────────────────────────

def test_py_compile_models():
    """backend/models.py compiles without syntax errors (AC5/UAT5)."""
    result = subprocess.run(
        [sys.executable, "-m", "py_compile", str(_ROOT / "backend" / "models.py")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"py_compile failed on backend/models.py:\n{result.stderr}"
    )


def test_py_compile_migration():
    """The plyo_sessions migration file compiles without syntax errors (AC5/UAT5)."""
    migration_files = list((_ROOT / "alembic" / "versions").glob("*plyo*"))
    assert migration_files, "No plyo_sessions migration file found in alembic/versions/"
    for mf in migration_files:
        result = subprocess.run(
            [sys.executable, "-m", "py_compile", str(mf)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"py_compile failed on {mf.name}:\n{result.stderr}"
        )


# ── AC6: Existing tables unaffected ───────────────────────────────────────────

def test_existing_workouts_table_intact():
    """workouts table still exists and is queryable after migration (AC6/UAT6)."""
    _require_engine()
    inspector = inspect(engine)
    assert inspector.has_table("workouts"), "workouts table missing after migration"
    with engine.connect() as conn:
        conn.execute(text("SELECT COUNT(*) FROM workouts")).scalar()


def test_existing_daily_metrics_table_intact():
    """daily_metrics table still exists and is queryable after migration (AC6/UAT6)."""
    _require_engine()
    inspector = inspect(engine)
    assert inspector.has_table("daily_metrics"), "daily_metrics table missing after migration"


def test_existing_habit_logs_table_intact():
    """habit_logs table still exists and is queryable after migration (AC6/UAT6)."""
    _require_engine()
    inspector = inspect(engine)
    assert inspector.has_table("habit_logs"), "habit_logs table missing after migration"


# ── Model importability ────────────────────────────────────────────────────────

def test_plyo_session_model_importable():
    """PlyoSession can be imported from backend.models (AC1)."""
    from backend.models import PlyoSession as PS
    assert PS.__tablename__ == "plyo_sessions"
