"""Tests for issue #385: Migrate habits table to unified weekly tracking schema.

Each test is anchored to one Acceptance Criterion item.
Tests use direct DB connections — alembic upgrade head must have been run first.
"""
import uuid
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from backend.db import engine


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def test_user_id():
    """Create a transient user for this test module; delete on teardown."""
    name = f"test_habits_385_{uuid.uuid4().hex[:8]}"
    with engine.begin() as conn:
        row = conn.execute(
            text("INSERT INTO users (name) VALUES (:name) RETURNING id"),
            {"name": name},
        ).fetchone()
        uid = str(row.id)
    yield uid
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": uid})


# ── AC: table exists with all required columns ────────────────────────────────

def test_habits_table_exists():
    """AC: habits table exists in public schema."""
    with engine.connect() as conn:
        count = conn.execute(text(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = 'habits'"
        )).scalar()
    assert count == 1, "habits table not found — run alembic upgrade head"


def test_all_required_columns_exist():
    """AC: all required columns present with correct nullability."""
    required = {
        "id":               False,  # NOT NULL
        "user_id":          False,
        "name":             False,
        "description":      True,   # nullable
        "tracking_type":    False,
        "weekly_target":    True,
        "unit":             True,
        "auto_fill_source": True,
        "icon":             True,
        "color":            True,
        "sort_order":       False,  # default 0, not null
        "is_archived":      False,  # default false, not null
        "created_at":       True,
        "updated_at":       True,
    }
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT column_name, is_nullable "
            "FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'habits'"
        )).fetchall()
    found = {r.column_name: (r.is_nullable == "YES") for r in rows}
    for col, nullable in required.items():
        assert col in found, f"Column '{col}' missing from habits table"
        assert found[col] == nullable, (
            f"habits.{col}: expected nullable={nullable}, got nullable={found[col]}"
        )


# ── AC: tracking_type check constraint ───────────────────────────────────────

def test_tracking_type_invalid_rejected(test_user_id):
    """AC: tracking_type='invalid_type' rejected by DB check constraint."""
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO habits (user_id, name, tracking_type) "
                "VALUES (:uid, :name, 'invalid_type')"
            ), {"uid": test_user_id, "name": "bad habit"})


def test_tracking_type_daily_checkmark_accepted(test_user_id):
    """AC: tracking_type='daily_checkmark' accepted."""
    with engine.begin() as conn:
        row = conn.execute(text(
            "INSERT INTO habits (user_id, name, tracking_type) "
            "VALUES (:uid, :name, 'daily_checkmark') RETURNING id"
        ), {"uid": test_user_id, "name": "daily_checkmark_test"}).fetchone()
        conn.execute(text("DELETE FROM habits WHERE id = :id"), {"id": str(row.id)})


def test_tracking_type_weekly_count_accepted(test_user_id):
    """AC: tracking_type='weekly_count' accepted."""
    with engine.begin() as conn:
        row = conn.execute(text(
            "INSERT INTO habits (user_id, name, tracking_type) "
            "VALUES (:uid, :name, 'weekly_count') RETURNING id"
        ), {"uid": test_user_id, "name": "weekly_count_test"}).fetchone()
        conn.execute(text("DELETE FROM habits WHERE id = :id"), {"id": str(row.id)})


def test_tracking_type_weekly_minutes_accepted(test_user_id):
    """AC: tracking_type='weekly_minutes' accepted."""
    with engine.begin() as conn:
        row = conn.execute(text(
            "INSERT INTO habits (user_id, name, tracking_type) "
            "VALUES (:uid, :name, 'weekly_minutes') RETURNING id"
        ), {"uid": test_user_id, "name": "weekly_minutes_test"}).fetchone()
        conn.execute(text("DELETE FROM habits WHERE id = :id"), {"id": str(row.id)})


def test_tracking_type_weekly_quantity_accepted(test_user_id):
    """AC: tracking_type='weekly_quantity' accepted."""
    with engine.begin() as conn:
        row = conn.execute(text(
            "INSERT INTO habits (user_id, name, tracking_type) "
            "VALUES (:uid, :name, 'weekly_quantity') RETURNING id"
        ), {"uid": test_user_id, "name": "weekly_quantity_test"}).fetchone()
        conn.execute(text("DELETE FROM habits WHERE id = :id"), {"id": str(row.id)})


# ── AC: auto_fill_source check constraint ────────────────────────────────────

def test_auto_fill_source_invalid_rejected(test_user_id):
    """AC: auto_fill_source='workout.nonexistent' rejected by check constraint."""
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO habits (user_id, name, tracking_type, auto_fill_source) "
                "VALUES (:uid, :name, 'weekly_minutes', 'workout.nonexistent')"
            ), {"uid": test_user_id, "name": "bad_source"})


def test_auto_fill_source_zone2_minutes_accepted(test_user_id):
    """AC: auto_fill_source='workout.zone2_minutes' accepted."""
    with engine.begin() as conn:
        row = conn.execute(text(
            "INSERT INTO habits (user_id, name, tracking_type, auto_fill_source) "
            "VALUES (:uid, :name, 'weekly_minutes', 'workout.zone2_minutes') RETURNING id"
        ), {"uid": test_user_id, "name": "z2_source_test"}).fetchone()
        conn.execute(text("DELETE FROM habits WHERE id = :id"), {"id": str(row.id)})


def test_auto_fill_source_run_count_accepted(test_user_id):
    """AC: auto_fill_source='workout.run_count' accepted."""
    with engine.begin() as conn:
        row = conn.execute(text(
            "INSERT INTO habits (user_id, name, tracking_type, auto_fill_source) "
            "VALUES (:uid, :name, 'weekly_count', 'workout.run_count') RETURNING id"
        ), {"uid": test_user_id, "name": "run_count_source_test"}).fetchone()
        conn.execute(text("DELETE FROM habits WHERE id = :id"), {"id": str(row.id)})


def test_auto_fill_source_lift_count_accepted(test_user_id):
    """AC: auto_fill_source='workout.lift_count' accepted."""
    with engine.begin() as conn:
        row = conn.execute(text(
            "INSERT INTO habits (user_id, name, tracking_type, auto_fill_source) "
            "VALUES (:uid, :name, 'weekly_count', 'workout.lift_count') RETURNING id"
        ), {"uid": test_user_id, "name": "lift_count_source_test"}).fetchone()
        conn.execute(text("DELETE FROM habits WHERE id = :id"), {"id": str(row.id)})


def test_auto_fill_source_total_duration_minutes_accepted(test_user_id):
    """AC: auto_fill_source='workout.total_duration_minutes' accepted."""
    with engine.begin() as conn:
        row = conn.execute(text(
            "INSERT INTO habits (user_id, name, tracking_type, auto_fill_source) "
            "VALUES (:uid, :name, 'weekly_minutes', 'workout.total_duration_minutes') RETURNING id"
        ), {"uid": test_user_id, "name": "total_dur_source_test"}).fetchone()
        conn.execute(text("DELETE FROM habits WHERE id = :id"), {"id": str(row.id)})


def test_auto_fill_source_distance_km_accepted(test_user_id):
    """AC: auto_fill_source='workout.distance_km' accepted."""
    with engine.begin() as conn:
        row = conn.execute(text(
            "INSERT INTO habits (user_id, name, tracking_type, auto_fill_source) "
            "VALUES (:uid, :name, 'weekly_quantity', 'workout.distance_km') RETURNING id"
        ), {"uid": test_user_id, "name": "distance_km_source_test"}).fetchone()
        conn.execute(text("DELETE FROM habits WHERE id = :id"), {"id": str(row.id)})


def test_auto_fill_source_null_accepted(test_user_id):
    """AC: auto_fill_source=NULL accepted (manual habit)."""
    with engine.begin() as conn:
        row = conn.execute(text(
            "INSERT INTO habits (user_id, name, tracking_type, auto_fill_source) "
            "VALUES (:uid, :name, 'daily_checkmark', NULL) RETURNING id"
        ), {"uid": test_user_id, "name": "null_source_test"}).fetchone()
        conn.execute(text("DELETE FROM habits WHERE id = :id"), {"id": str(row.id)})


# ── AC: sort_order default 0, is_archived default false ──────────────────────

def test_sort_order_defaults_to_zero(test_user_id):
    """AC: sort_order defaults to 0 when not specified."""
    with engine.begin() as conn:
        row = conn.execute(text(
            "INSERT INTO habits (user_id, name, tracking_type) "
            "VALUES (:uid, :name, 'daily_checkmark') RETURNING id, sort_order"
        ), {"uid": test_user_id, "name": "sort_order_default_test"}).fetchone()
        assert row.sort_order == 0, f"Expected sort_order=0, got {row.sort_order}"
        conn.execute(text("DELETE FROM habits WHERE id = :id"), {"id": str(row.id)})


def test_is_archived_defaults_to_false(test_user_id):
    """AC: is_archived defaults to false when not specified."""
    with engine.begin() as conn:
        row = conn.execute(text(
            "INSERT INTO habits (user_id, name, tracking_type) "
            "VALUES (:uid, :name, 'daily_checkmark') RETURNING id, is_archived"
        ), {"uid": test_user_id, "name": "is_archived_default_test"}).fetchone()
        assert row.is_archived is False, f"Expected is_archived=False, got {row.is_archived}"
        conn.execute(text("DELETE FROM habits WHERE id = :id"), {"id": str(row.id)})


# ── AC: full row with all nullable cols omitted ───────────────────────────────

def test_minimal_habit_row_persists(test_user_id):
    """AC: daily_checkmark with no optional fields persists cleanly."""
    with engine.begin() as conn:
        row = conn.execute(text(
            "INSERT INTO habits (user_id, name, tracking_type) "
            "VALUES (:uid, :name, 'daily_checkmark') "
            "RETURNING id, description, weekly_target, unit, auto_fill_source, icon, color"
        ), {"uid": test_user_id, "name": "minimal_habit_test"}).fetchone()
        assert row.description is None
        assert row.weekly_target is None
        assert row.unit is None
        assert row.auto_fill_source is None
        assert row.icon is None
        assert row.color is None
        conn.execute(text("DELETE FROM habits WHERE id = :id"), {"id": str(row.id)})


# ── AC: full weekly_minutes with auto_fill_source ────────────────────────────

def test_full_weekly_minutes_habit_persists(test_user_id):
    """AC: weekly_minutes habit with target + unit + auto_fill_source persists."""
    with engine.begin() as conn:
        row = conn.execute(text(
            "INSERT INTO habits (user_id, name, tracking_type, weekly_target, unit, auto_fill_source) "
            "VALUES (:uid, :name, 'weekly_minutes', 210, 'min', 'workout.zone2_minutes') "
            "RETURNING id, tracking_type, weekly_target, unit, auto_fill_source"
        ), {"uid": test_user_id, "name": "full_habit_test"}).fetchone()
        assert row.tracking_type == "weekly_minutes"
        assert float(row.weekly_target) == 210.0
        assert row.unit == "min"
        assert row.auto_fill_source == "workout.zone2_minutes"
        conn.execute(text("DELETE FROM habits WHERE id = :id"), {"id": str(row.id)})


# ── AC: cascade delete when user deleted ─────────────────────────────────────

def test_cascade_delete_on_user_delete():
    """AC: deleting user cascades to all their habit rows."""
    name = f"cascade_test_{uuid.uuid4().hex[:8]}"
    with engine.begin() as conn:
        uid_row = conn.execute(
            text("INSERT INTO users (name) VALUES (:name) RETURNING id"),
            {"name": name},
        ).fetchone()
        uid = str(uid_row.id)

    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO habits (user_id, name, tracking_type) "
            "VALUES (:uid, 'h1', 'daily_checkmark'), (:uid, 'h2', 'weekly_count')"
        ), {"uid": uid})

    with engine.connect() as conn:
        count_before = conn.execute(
            text("SELECT COUNT(*) FROM habits WHERE user_id = :uid"), {"uid": uid}
        ).scalar()
    assert count_before == 2

    with engine.begin() as conn:
        conn.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": uid})

    with engine.connect() as conn:
        count_after = conn.execute(
            text("SELECT COUNT(*) FROM habits WHERE user_id = :uid"), {"uid": uid}
        ).scalar()
    assert count_after == 0, f"Cascade delete failed: {count_after} habit rows remain"


# ── AC: migration docstring ───────────────────────────────────────────────────

def test_migration_docstring():
    """AC: migration file has the exact required docstring."""
    import os
    import glob

    versions_dir = os.path.join(
        os.path.dirname(__file__), "..", "alembic", "versions"
    )
    pattern = os.path.join(versions_dir, "*unified_habits*")
    files = glob.glob(pattern)
    assert files, "No migration file matching '*unified_habits*' found in alembic/versions/"

    expected = (
        "Unified habits table. Replaces separate weekly-target concept. "
        "Each habit can be manual (daily_checkmark with weekly_target as days/week) "
        "or auto-fill from workouts. Manual entries logged via habit_logs "
        "(separate table, see next ticket)."
    )
    with open(files[0]) as f:
        content = f.read()
    assert expected in content, (
        f"Migration docstring not found in {files[0]}.\nExpected substring:\n{expected}"
    )


# ── AC: FK to users exists ────────────────────────────────────────────────────

def test_fk_to_users_exists():
    """AC: habits.user_id has a FK referencing users."""
    with engine.connect() as conn:
        count = conn.execute(text(
            "SELECT COUNT(*) FROM information_schema.referential_constraints rc "
            "JOIN information_schema.table_constraints tc "
            "  ON rc.constraint_name = tc.constraint_name "
            " AND tc.table_schema = 'public' "
            " AND tc.table_name = 'habits'"
        )).scalar()
    assert count >= 1, "No FK from habits to users found"


# ── AC: new nullable columns don't break existing ORM queries ─────────────────

def test_orm_query_habits_table_works():
    """AC: ORM can query habits table without error after migration."""
    from sqlalchemy.orm import Session
    from backend.models import Habit
    from backend.db import engine

    with Session(engine) as db:
        habits = db.query(Habit).limit(1).all()
        for h in habits:
            _ = h.tracking_type
            _ = h.auto_fill_source
            _ = h.is_archived
