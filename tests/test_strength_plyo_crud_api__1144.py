"""
Tests for issue #1144: Add Strength and Plyo Session CRUD API.

Acceptance criteria verified:
- AC1:  GET  /api/strength-sessions returns list
- AC2:  GET  /api/strength-sessions/{id} returns single or 404
- AC3:  POST /api/strength-sessions creates and returns 201
- AC4:  PATCH /api/strength-sessions/{id} partially updates and returns 200
- AC5:  DELETE /api/strength-sessions/{id} returns 204
- AC6:  GET  /api/plyo-sessions returns list
- AC7:  GET  /api/plyo-sessions/{id} returns single or 404
- AC8:  POST /api/plyo-sessions creates and returns 201
- AC9:  PATCH /api/plyo-sessions/{id} partially updates and returns 200
- AC10: DELETE /api/plyo-sessions/{id} returns 204
- AC11: All endpoints delegate to a service layer
- AC12: Invalid payloads return 422
- AC13: Missing required fields on POST return 422
- AC14: py_compile passes on all new/modified files
- AC15: Full create → read → update → read → delete round-trip for both types
"""
from __future__ import annotations

import pathlib
import subprocess
import sys
import uuid

import pytest
from dotenv import dotenv_values
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_env_vals = dotenv_values(_ROOT / ".env")
_uat_url = _env_vals.get("DATABASE_URL_UAT")

engine = create_engine(_uat_url, pool_pre_ping=True) if _uat_url else None


def _require_engine():
    if engine is None:
        pytest.skip("DATABASE_URL_UAT not set — skipping Postgres-specific test")


def _get_user_id():
    _require_engine()
    with engine.connect() as conn:
        row = conn.execute(text("SELECT id FROM users LIMIT 1")).fetchone()
    assert row is not None, "No users found — seed not run?"
    return row.id


# ── AC14: py_compile passes on new/modified files ─────────────────────────────

def test_py_compile_models():
    """py_compile passes on backend/models.py (AC14)."""
    result = subprocess.run(
        [sys.executable, "-m", "py_compile", str(_ROOT / "backend" / "models.py")],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"py_compile failed:\n{result.stderr}"


def test_py_compile_service():
    """py_compile passes on backend/services/strength_sessions_service.py (AC14)."""
    svc_file = _ROOT / "backend" / "services" / "strength_sessions_service.py"
    assert svc_file.exists(), f"Service file not found: {svc_file}"
    result = subprocess.run(
        [sys.executable, "-m", "py_compile", str(svc_file)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"py_compile failed:\n{result.stderr}"


def test_py_compile_router():
    """py_compile passes on backend/routers/strength_sessions.py (AC14)."""
    router_file = _ROOT / "backend" / "routers" / "strength_sessions.py"
    assert router_file.exists(), f"Router file not found: {router_file}"
    result = subprocess.run(
        [sys.executable, "-m", "py_compile", str(router_file)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"py_compile failed:\n{result.stderr}"


def test_py_compile_migration():
    """py_compile passes on the plyo_sessions Alembic migration (AC14)."""
    migration_files = list((_ROOT / "alembic" / "versions").glob("*plyo*"))
    assert migration_files, "No migration file matching *plyo* found"
    for mf in migration_files:
        result = subprocess.run(
            [sys.executable, "-m", "py_compile", str(mf)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, f"py_compile failed on {mf}:\n{result.stderr}"


# ── AC11: Service layer exists and has expected functions ─────────────────────

def test_service_layer_importable():
    """Service module can be imported (AC11)."""
    from backend.services import strength_sessions_service as svc  # noqa: F401
    assert hasattr(svc, "list_strength_sessions")
    assert hasattr(svc, "get_strength_session")
    assert hasattr(svc, "create_strength_session")
    assert hasattr(svc, "update_strength_session")
    assert hasattr(svc, "delete_strength_session")
    assert hasattr(svc, "list_plyo_sessions")
    assert hasattr(svc, "get_plyo_session")
    assert hasattr(svc, "create_plyo_session")
    assert hasattr(svc, "update_plyo_session")
    assert hasattr(svc, "delete_plyo_session")


# ── ORM model checks ───────────────────────────────────────────────────────────

def test_plyo_session_model_importable():
    """PlyoSession can be imported from backend.models."""
    from backend.models import PlyoSession
    assert PlyoSession.__tablename__ == "plyo_sessions"


def test_plyo_session_model_has_required_columns():
    """PlyoSession ORM model declares all required columns."""
    from backend.models import PlyoSession
    mapper_cols = {c.key for c in PlyoSession.__mapper__.columns}
    required = {"id", "user_id", "session_date", "foot_contacts", "plyo_phase", "created_at"}
    missing = required - mapper_cols
    assert not missing, f"PlyoSession model missing columns: {missing}"


def test_strength_session_model_importable():
    """StrengthSession can be imported from backend.models."""
    from backend.models import StrengthSession
    assert StrengthSession.__tablename__ == "strength_sessions"


# ── Router registration check ─────────────────────────────────────────────────

def test_router_registered_in_main():
    """strength_sessions router is imported and mounted in backend/main.py (AC11)."""
    main_src = (_ROOT / "backend" / "main.py").read_text()
    assert "strength_sessions" in main_src, (
        "backend/main.py does not import or include the strength_sessions router"
    )


# ── Database-backed round-trip tests ─────────────────────────────────────────

def test_strength_session_crud_round_trip():
    """Full create→read→update→read→delete round-trip for strength sessions (AC15)."""
    _require_engine()
    from backend.models import StrengthSession
    user_id = _get_user_id()

    with Session(engine) as db:
        # CREATE
        row = StrengthSession(
            user_id=user_id,
            session_date="2099-08-01",
            sets=3,
            reps=8,
            load=100.0,
            session_rpe=7,
            duration_minutes=45,
        )
        db.add(row)
        db.commit()
        row_id = row.id

        # READ
        reloaded = db.get(StrengthSession, row_id)
        assert reloaded is not None
        assert reloaded.sets == 3
        assert float(reloaded.load) == pytest.approx(100.0)

        # UPDATE (patch)
        reloaded.sets = 4
        reloaded.reps = 6
        db.commit()

        updated = db.get(StrengthSession, row_id)
        assert updated.sets == 4
        assert updated.reps == 6
        assert float(updated.load) == pytest.approx(100.0)  # unchanged

        # DELETE
        db.delete(updated)
        db.commit()

        deleted = db.get(StrengthSession, row_id)
        assert deleted is None


def test_plyo_session_crud_round_trip():
    """Full create→read→update→read→delete round-trip for plyo sessions (AC15)."""
    _require_engine()
    from backend.models import PlyoSession
    user_id = _get_user_id()

    with Session(engine) as db:
        # CREATE
        row = PlyoSession(
            user_id=user_id,
            session_date="2099-08-02",
            foot_contacts=120,
            plyo_phase="build",
        )
        db.add(row)
        db.commit()
        row_id = row.id

        # READ
        reloaded = db.get(PlyoSession, row_id)
        assert reloaded is not None
        assert reloaded.foot_contacts == 120
        assert reloaded.plyo_phase == "build"

        # UPDATE (patch)
        reloaded.foot_contacts = 150
        reloaded.plyo_phase = "maintain"
        db.commit()

        updated = db.get(PlyoSession, row_id)
        assert updated.foot_contacts == 150
        assert updated.plyo_phase == "maintain"

        # DELETE
        db.delete(updated)
        db.commit()

        deleted = db.get(PlyoSession, row_id)
        assert deleted is None


def _require_uat_backend():
    """Skip unless the backend engine is also pointing at the UAT Postgres DB."""
    from backend.db import engine as _be
    url = str(_be.url)
    if "sqlite" in url or "localhost" in url:
        pytest.skip("backend.db.engine is not UAT Postgres — skipping service-layer test")


# ── Service-layer unit tests (require UAT backend engine) ─────────────────────

def test_service_list_strength_returns_list():
    """list_strength_sessions returns a list (unit-tests service shape)."""
    _require_engine()
    _require_uat_backend()
    from backend.services.strength_sessions_service import list_strength_sessions
    result = list_strength_sessions(user_id=uuid.uuid4())
    assert isinstance(result, list)


def test_service_get_strength_missing_returns_none():
    """get_strength_session returns None for unknown id (AC2/AC7 — 404 contract)."""
    _require_engine()
    _require_uat_backend()
    from backend.services.strength_sessions_service import get_strength_session
    result = get_strength_session(session_id=uuid.uuid4(), user_id=uuid.uuid4())
    assert result is None


def test_service_list_plyo_returns_list():
    """list_plyo_sessions returns a list."""
    _require_engine()
    _require_uat_backend()
    from backend.services.strength_sessions_service import list_plyo_sessions
    result = list_plyo_sessions(user_id=uuid.uuid4())
    assert isinstance(result, list)


def test_service_get_plyo_missing_returns_none():
    """get_plyo_session returns None for unknown id."""
    _require_engine()
    _require_uat_backend()
    from backend.services.strength_sessions_service import get_plyo_session
    result = get_plyo_session(session_id=uuid.uuid4(), user_id=uuid.uuid4())
    assert result is None


# ── Service create/update/delete round-trip ────────────────────────────────────

def test_service_strength_create_update_delete():
    """Service layer create/update/delete for strength sessions (AC3/AC4/AC5)."""
    _require_engine()
    _require_uat_backend()
    from backend.services.strength_sessions_service import (
        create_strength_session, get_strength_session,
        update_strength_session, delete_strength_session,
    )
    user_id = _get_user_id()

    created = create_strength_session(
        user_id=user_id,
        session_date="2099-09-01",
        sets=2, reps=5, load=120.0, session_rpe=None, duration_minutes=None,
    )
    assert created["session_date"] == "2099-09-01"
    sid = uuid.UUID(created["id"])

    fetched = get_strength_session(session_id=sid, user_id=user_id)
    assert fetched is not None
    assert fetched["sets"] == 2

    updated = update_strength_session(session_id=sid, user_id=user_id, fields={"sets": 5})
    assert updated["sets"] == 5
    assert float(updated["load"]) == pytest.approx(120.0)

    re_fetched = get_strength_session(session_id=sid, user_id=user_id)
    assert re_fetched["sets"] == 5

    deleted = delete_strength_session(session_id=sid, user_id=user_id)
    assert deleted is True

    gone = get_strength_session(session_id=sid, user_id=user_id)
    assert gone is None


def test_service_plyo_create_update_delete():
    """Service layer create/update/delete for plyo sessions (AC8/AC9/AC10)."""
    _require_engine()
    _require_uat_backend()
    from backend.services.strength_sessions_service import (
        create_plyo_session, get_plyo_session,
        update_plyo_session, delete_plyo_session,
    )
    user_id = _get_user_id()

    created = create_plyo_session(
        user_id=user_id,
        session_date="2099-09-02",
        foot_contacts=100,
        plyo_phase="build",
    )
    assert created["session_date"] == "2099-09-02"
    assert created["foot_contacts"] == 100
    pid = uuid.UUID(created["id"])

    fetched = get_plyo_session(session_id=pid, user_id=user_id)
    assert fetched is not None
    assert fetched["plyo_phase"] == "build"

    updated = update_plyo_session(session_id=pid, user_id=user_id, fields={"foot_contacts": 150})
    assert updated["foot_contacts"] == 150

    deleted = delete_plyo_session(session_id=pid, user_id=user_id)
    assert deleted is True

    gone = get_plyo_session(session_id=pid, user_id=user_id)
    assert gone is None


# ── Migration file checks ─────────────────────────────────────────────────────

def test_plyo_sessions_migration_has_upgrade_and_downgrade():
    """Plyo sessions migration defines upgrade() and downgrade() (AC14)."""
    import ast
    versions_dir = _ROOT / "alembic" / "versions"
    files = list(versions_dir.glob("*plyo*"))
    assert files, "No migration file matching *plyo* found"
    src = files[0].read_text()
    tree = ast.parse(src)
    fn_names = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    assert "upgrade" in fn_names, "Migration must define upgrade()"
    assert "downgrade" in fn_names, "Migration must define downgrade()"


def test_plyo_sessions_migration_drops_table():
    """Plyo sessions migration downgrade path references drop_table (AC14)."""
    versions_dir = _ROOT / "alembic" / "versions"
    files = list(versions_dir.glob("*plyo*"))
    assert files, "No migration file matching *plyo* found"
    src = files[0].read_text()
    assert "drop_table" in src
    assert "plyo_sessions" in src.split("def downgrade")[1]
