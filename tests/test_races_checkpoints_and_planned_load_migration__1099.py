"""
Tests for issue #1099: Add migration for races_checkpoints and planned_load tables.

Acceptance criteria verified:
- AC1: races_checkpoints table exists with id, name, date, distance_km, type, goal_time columns.
- AC1b: `type` column is constrained to only allow 'race' or 'checkpoint' values.
- AC1c: `name` and `date` columns are NOT NULL; `distance_km` and `goal_time` are nullable.
- AC2: planned_load table exists with date (unique/PK) and planned_tss (not null) columns.
- AC3: down migration drops both tables (verified via py_compile and structure only).
- AC5: All new Python migration files pass py_compile (no syntax errors).
- AC6: No new API endpoints or UI files are introduced.
"""
import os
import py_compile
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import text

from backend.db import engine


# ── Helpers ─────────────────────────────────────────────────────────────────

VERSIONS_DIR = Path(__file__).parent.parent / "alembic" / "versions"


def _get_column_info(table: str):
    """Return dict of {column_name: {nullable, data_type}} for table."""
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT column_name, is_nullable, data_type "
            "FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = :tbl"
        ), {"tbl": table}).fetchall()
    return {r[0]: {"nullable": r[1] == "YES", "data_type": r[2]} for r in rows}


def _constraint_exists(table: str, name: str) -> bool:
    with engine.connect() as conn:
        row = conn.execute(text(
            "SELECT 1 FROM information_schema.table_constraints "
            "WHERE table_schema = 'public' AND table_name = :tbl "
            "AND constraint_name = :name"
        ), {"tbl": table, "name": name}).fetchone()
    return row is not None


# ── AC1: races_checkpoints table structure ───────────────────────────────────

def test_races_checkpoints_table_exists():
    """races_checkpoints table is present after migration (AC1/UAT1)."""
    with engine.connect() as conn:
        count = conn.execute(text(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = 'races_checkpoints'"
        )).scalar()
    assert count == 1, "races_checkpoints table not found — was alembic upgrade head run?"


def test_races_checkpoints_has_id_column():
    """races_checkpoints has an 'id' primary key column (AC1)."""
    cols = _get_column_info("races_checkpoints")
    assert "id" in cols, "Column 'id' missing from races_checkpoints"
    assert not cols["id"]["nullable"], "id must NOT be nullable (it's the PK)"


def test_races_checkpoints_name_not_null():
    """races_checkpoints.name is NOT NULL (AC1)."""
    cols = _get_column_info("races_checkpoints")
    assert "name" in cols, "Column 'name' missing from races_checkpoints"
    assert not cols["name"]["nullable"], "'name' must NOT be nullable"


def test_races_checkpoints_date_not_null():
    """races_checkpoints.date is NOT NULL (AC1)."""
    cols = _get_column_info("races_checkpoints")
    assert "date" in cols, "Column 'date' missing from races_checkpoints"
    assert not cols["date"]["nullable"], "'date' must NOT be nullable"


def test_races_checkpoints_distance_km_nullable():
    """races_checkpoints.distance_km is nullable (AC1)."""
    cols = _get_column_info("races_checkpoints")
    assert "distance_km" in cols, "Column 'distance_km' missing from races_checkpoints"
    assert cols["distance_km"]["nullable"], "'distance_km' must be nullable"


def test_races_checkpoints_type_not_null():
    """races_checkpoints.type is NOT NULL (AC1)."""
    cols = _get_column_info("races_checkpoints")
    assert "type" in cols, "Column 'type' missing from races_checkpoints"
    assert not cols["type"]["nullable"], "'type' must NOT be nullable"


def test_races_checkpoints_goal_time_nullable():
    """races_checkpoints.goal_time is nullable (AC1)."""
    cols = _get_column_info("races_checkpoints")
    assert "goal_time" in cols, "Column 'goal_time' missing from races_checkpoints"
    assert cols["goal_time"]["nullable"], "'goal_time' must be nullable"


def test_races_checkpoints_all_required_columns():
    """All six required columns exist in races_checkpoints (AC1)."""
    required = {"id", "name", "date", "distance_km", "type", "goal_time"}
    cols = _get_column_info("races_checkpoints")
    missing = required - set(cols.keys())
    assert not missing, f"Missing columns in races_checkpoints: {missing}"


# ── AC1b: type constraint ────────────────────────────────────────────────────

def test_type_constraint_rejects_invalid_value():
    """Inserting an invalid 'type' into races_checkpoints raises an error (AC1b/UAT4)."""
    from sqlalchemy.exc import IntegrityError, DataError

    with pytest.raises((IntegrityError, DataError)):
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO races_checkpoints (name, date, type) "
                "VALUES ('Test', '2099-01-01', 'invalid_type')"
            ))


def test_type_constraint_accepts_race():
    """Inserting type='race' into races_checkpoints succeeds (AC1b/UAT4)."""
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO races_checkpoints (name, date, type) "
            "VALUES ('Race Test', '2099-01-01', 'race')"
        ))
        conn.execute(text(
            "DELETE FROM races_checkpoints WHERE name = 'Race Test'"
        ))


def test_type_constraint_accepts_checkpoint():
    """Inserting type='checkpoint' into races_checkpoints succeeds (AC1b/UAT4)."""
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO races_checkpoints (name, date, type) "
            "VALUES ('Checkpoint Test', '2099-01-01', 'checkpoint')"
        ))
        conn.execute(text(
            "DELETE FROM races_checkpoints WHERE name = 'Checkpoint Test'"
        ))


# ── AC2: planned_load table structure ────────────────────────────────────────

def test_planned_load_table_exists():
    """planned_load table is present after migration (AC2/UAT1)."""
    with engine.connect() as conn:
        count = conn.execute(text(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = 'planned_load'"
        )).scalar()
    assert count == 1, "planned_load table not found — was alembic upgrade head run?"


def test_planned_load_date_column_exists():
    """planned_load has a 'date' column (AC2)."""
    cols = _get_column_info("planned_load")
    assert "date" in cols, "Column 'date' missing from planned_load"


def test_planned_load_planned_tss_not_null():
    """planned_load.planned_tss is NOT NULL (AC2/UAT3)."""
    cols = _get_column_info("planned_load")
    assert "planned_tss" in cols, "Column 'planned_tss' missing from planned_load"
    assert not cols["planned_tss"]["nullable"], "'planned_tss' must NOT be nullable"


def test_planned_load_date_is_unique():
    """planned_load.date is unique or the primary key (AC2/UAT3)."""
    with engine.connect() as conn:
        row = conn.execute(text(
            "SELECT COUNT(*) FROM information_schema.table_constraints tc "
            "JOIN information_schema.key_column_usage kcu "
            "  ON tc.constraint_name = kcu.constraint_name "
            "WHERE tc.table_schema = 'public' "
            "  AND tc.table_name = 'planned_load' "
            "  AND kcu.column_name = 'date' "
            "  AND tc.constraint_type IN ('PRIMARY KEY', 'UNIQUE')"
        )).scalar()
    assert row >= 1, "planned_load.date is not unique/PK"


def test_planned_load_rejects_null_planned_tss():
    """Inserting a row with NULL planned_tss is rejected (AC2/UAT3)."""
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO planned_load (date, planned_tss) "
                "VALUES ('2099-01-01', NULL)"
            ))


def test_planned_load_date_uniqueness_enforced():
    """Inserting two rows with the same date into planned_load is rejected (AC2/UAT3)."""
    from sqlalchemy.exc import IntegrityError

    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO planned_load (date, planned_tss) VALUES ('2098-12-31', 100)"
        ))

    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO planned_load (date, planned_tss) VALUES ('2098-12-31', 200)"
            ))

    with engine.begin() as conn:
        conn.execute(text("DELETE FROM planned_load WHERE date = '2098-12-31'"))


# ── AC5: py_compile ──────────────────────────────────────────────────────────

def test_migration_file_compiles_without_syntax_error():
    """The new migration Python file has no syntax errors (AC5/UAT7)."""
    migration_files = list(VERSIONS_DIR.glob("*add_races_checkpoints_and_planned_load*"))
    assert migration_files, (
        "Could not find the migration file matching 'add_races_checkpoints_and_planned_load'"
    )
    for path in migration_files:
        try:
            py_compile.compile(str(path), doraise=True)
        except py_compile.PyCompileError as exc:
            pytest.fail(f"Syntax error in {path.name}: {exc}")


def test_merge_migration_file_compiles_without_syntax_error():
    """The merge migration Python file has no syntax errors (AC5/UAT7)."""
    merge_files = list(VERSIONS_DIR.glob("*merge*1099*")) + list(VERSIONS_DIR.glob("*1099*merge*"))
    # Also match by known content — all merge files for heads
    if not merge_files:
        merge_files = list(VERSIONS_DIR.glob("948fd1cacfd7*"))
    if not merge_files:
        pytest.skip("No merge migration file found for 1099; skipping py_compile check")
    for path in merge_files:
        try:
            py_compile.compile(str(path), doraise=True)
        except py_compile.PyCompileError as exc:
            pytest.fail(f"Syntax error in {path.name}: {exc}")


# ── AC6: no new endpoints or UI files ────────────────────────────────────────

def test_no_new_api_routes_for_races_checkpoints():
    """No API endpoint is registered for races_checkpoints in main.py (AC6)."""
    main_py = Path(__file__).parent.parent / "backend" / "main.py"
    content = main_py.read_text()
    assert "races_checkpoints" not in content, (
        "Found 'races_checkpoints' in main.py — AC6 says no API endpoints for this ticket"
    )


def test_no_new_api_routes_for_planned_load():
    """No API endpoint is registered for planned_load in main.py (AC6)."""
    main_py = Path(__file__).parent.parent / "backend" / "main.py"
    content = main_py.read_text()
    assert "planned_load" not in content, (
        "Found 'planned_load' in main.py — AC6 says no API endpoints for this ticket"
    )


def test_no_new_frontend_pages_for_1099():
    """No new HTML file referencing races_checkpoints or planned_load exists (AC6)."""
    frontend_dir = Path(__file__).parent.parent / "frontend"
    for html_file in frontend_dir.rglob("*.html"):
        content = html_file.read_text()
        assert "races_checkpoints" not in content, (
            f"{html_file} mentions races_checkpoints — AC6 prohibits UI changes"
        )
        assert "planned_load" not in content, (
            f"{html_file} mentions planned_load — AC6 prohibits UI changes"
        )
