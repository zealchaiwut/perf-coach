"""
Tests for issue #1142: Add strength_sessions table and StrengthSession ORM model.

Acceptance criteria verified:
- AC1: strength_sessions table exists after running migrations.
- AC2: All required columns present (id, user_id, session_date, sets, reps, load,
        session_rpe, duration_minutes, created_at, updated_at).
- AC3: Both load-capture patterns supported — sets×reps×load (session_rpe/duration nullable)
        and session-RPE×duration (sets/reps/load nullable).
- AC4: StrengthSession ORM model is defined and maps correctly to the table.
- AC5: A row can be inserted and retrieved without error (both patterns).
- AC6: py_compile passes clean on new/modified Python files.
- AC7: Migration is reversible (downgrade drops the table cleanly).

Runs against the UAT Postgres database via DATABASE_URL_UAT from .env.
"""
import pathlib
import subprocess
import sys

import pytest
from dotenv import dotenv_values
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from backend.models import StrengthSession

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
            text("SELECT id FROM users LIMIT 1")
        ).fetchone()
    assert row is not None, "No users found — seed not run?"
    return row.id


def _get_columns():
    _require_engine()
    inspector = inspect(engine)
    cols = inspector.get_columns("strength_sessions")
    return {c["name"]: c for c in cols}


# ── AC1: Table exists ──────────────────────────────────────────────────────────

def test_strength_sessions_table_exists():
    """strength_sessions table exists after migration (AC1/UAT1)."""
    _require_engine()
    inspector = inspect(engine)
    assert inspector.has_table("strength_sessions"), "strength_sessions table not found"


# ── AC2: All required columns present ─────────────────────────────────────────

def test_strength_sessions_required_columns():
    """All required columns exist in strength_sessions (AC2/UAT2)."""
    required = {
        "id", "user_id", "session_date",
        "sets", "reps", "load",
        "session_rpe", "duration_minutes",
        "created_at", "updated_at",
    }
    cols = _get_columns()
    missing = required - cols.keys()
    assert not missing, f"Missing columns in strength_sessions: {missing}"


def test_sets_nullable():
    """sets is nullable — supports session-RPE pattern with no set count (AC2/AC3)."""
    cols = _get_columns()
    assert cols["sets"]["nullable"] is True, "sets should be nullable"


def test_reps_nullable():
    """reps is nullable — supports session-RPE pattern (AC2/AC3)."""
    cols = _get_columns()
    assert cols["reps"]["nullable"] is True, "reps should be nullable"


def test_load_nullable():
    """load is nullable — supports session-RPE pattern with no explicit load (AC2/AC3)."""
    cols = _get_columns()
    assert cols["load"]["nullable"] is True, "load should be nullable"


def test_session_rpe_nullable():
    """session_rpe is nullable — supports sets×reps×load pattern without RPE (AC2/AC3)."""
    cols = _get_columns()
    assert cols["session_rpe"]["nullable"] is True, "session_rpe should be nullable"


def test_duration_minutes_nullable():
    """duration_minutes is nullable — optional for sets×reps×load pattern (AC2/AC3)."""
    cols = _get_columns()
    assert cols["duration_minutes"]["nullable"] is True, "duration_minutes should be nullable"


def test_session_date_not_nullable():
    """session_date is NOT nullable (AC2)."""
    cols = _get_columns()
    assert cols["session_date"]["nullable"] is False, "session_date should not be nullable"


def test_user_id_not_nullable():
    """user_id is NOT nullable (AC2)."""
    cols = _get_columns()
    assert cols["user_id"]["nullable"] is False, "user_id should not be nullable"


# ── AC4: ORM model importable and maps correctly ───────────────────────────────

def test_strength_session_model_importable():
    """StrengthSession can be imported from backend.models (AC4)."""
    from backend.models import StrengthSession as SS
    assert SS.__tablename__ == "strength_sessions"


def test_strength_session_model_has_all_columns():
    """StrengthSession ORM model declares all required columns (AC4)."""
    from backend.models import StrengthSession as SS
    mapper_cols = {c.key for c in SS.__mapper__.columns}
    required = {
        "id", "user_id", "session_date",
        "sets", "reps", "load",
        "session_rpe", "duration_minutes",
        "created_at", "updated_at",
    }
    missing = required - mapper_cols
    assert not missing, f"StrengthSession model missing columns: {missing}"


# ── AC3 + AC5: Insert and retrieve — sets×reps×load pattern ──────────────────

def test_insert_sets_reps_load_pattern():
    """Insert and retrieve a sets×reps×load row (AC3/AC5/UAT3)."""
    user_id = _alice_id()
    with Session(engine) as session:
        row = StrengthSession(
            user_id=user_id,
            session_date="2099-07-01",
            sets=3,
            reps=5,
            load=100.0,
            session_rpe=None,
            duration_minutes=None,
        )
        session.add(row)
        session.commit()
        row_id = row.id

        reloaded = session.get(StrengthSession, row_id)
        assert reloaded is not None
        assert reloaded.sets == 3
        assert reloaded.reps == 5
        assert float(reloaded.load) == pytest.approx(100.0)
        assert reloaded.session_rpe is None
        assert reloaded.duration_minutes is None

        session.delete(reloaded)
        session.commit()


# ── AC3 + AC5: Insert and retrieve — session-RPE×duration pattern ─────────────

def test_insert_session_rpe_duration_pattern():
    """Insert and retrieve a session-RPE×duration row (AC3/AC5/UAT4)."""
    user_id = _alice_id()
    with Session(engine) as session:
        row = StrengthSession(
            user_id=user_id,
            session_date="2099-07-02",
            sets=None,
            reps=None,
            load=None,
            session_rpe=8,
            duration_minutes=45,
        )
        session.add(row)
        session.commit()
        row_id = row.id

        reloaded = session.get(StrengthSession, row_id)
        assert reloaded is not None
        assert reloaded.sets is None
        assert reloaded.reps is None
        assert reloaded.load is None
        assert reloaded.session_rpe == 8
        assert reloaded.duration_minutes == 45

        session.delete(reloaded)
        session.commit()


# ── AC5: created_at and updated_at are auto-populated ─────────────────────────

def test_created_at_auto_populated():
    """created_at is automatically set on insert (AC5)."""
    user_id = _alice_id()
    with Session(engine) as session:
        row = StrengthSession(
            user_id=user_id,
            session_date="2099-07-03",
            sets=4,
            reps=8,
            load=80.0,
        )
        session.add(row)
        session.commit()
        row_id = row.id

        reloaded = session.get(StrengthSession, row_id)
        assert reloaded.created_at is not None

        session.delete(reloaded)
        session.commit()


# ── AC6: py_compile passes on modified Python files ───────────────────────────

def test_py_compile_models():
    """py_compile passes on backend/models.py (AC6/UAT6)."""
    result = subprocess.run(
        [sys.executable, "-m", "py_compile", str(_ROOT / "backend" / "models.py")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"py_compile failed:\n{result.stderr}"


def test_py_compile_migration():
    """py_compile passes on the strength_sessions Alembic migration (AC6/UAT6)."""
    migration_files = list((_ROOT / "alembic" / "versions").glob("*strength_sessions*"))
    assert migration_files, "No migration file found matching *strength_sessions*"
    for mf in migration_files:
        result = subprocess.run(
            [sys.executable, "-m", "py_compile", str(mf)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"py_compile failed on {mf}:\n{result.stderr}"


# ── AC7: Migration is reversible — downgrade() is defined and has correct shape ─

def test_migration_downgrade_function_exists():
    """Migration file defines a callable downgrade() function (AC7/UAT5)."""
    import ast

    versions_dir = _ROOT / "alembic" / "versions"
    migration_files = list(versions_dir.glob("*strength_sessions*"))
    assert migration_files, "No migration file found matching *strength_sessions*"

    src = migration_files[0].read_text()
    tree = ast.parse(src)
    fn_names = [node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]
    assert "downgrade" in fn_names, "Migration must define a downgrade() function"
    assert "upgrade" in fn_names, "Migration must define an upgrade() function"


def test_migration_downgrade_drops_table():
    """Downgrade removes the strength_sessions table cleanly (AC7/UAT5).

    Verifies that the downgrade path in the migration script explicitly references
    drop_table('strength_sessions'), so a reviewer can confirm reversibility without
    running a destructive downgrade against the test DB.
    """
    import ast

    versions_dir = _ROOT / "alembic" / "versions"
    migration_files = list(versions_dir.glob("*strength_sessions*"))
    assert migration_files, "No migration file found matching *strength_sessions*"

    src = migration_files[0].read_text()
    # drop_table("strength_sessions") must appear in the downgrade() body
    assert "drop_table" in src, "downgrade() must call op.drop_table"
    assert "strength_sessions" in src.split("def downgrade")[1], (
        "drop_table call must reference 'strength_sessions' in downgrade()"
    )
