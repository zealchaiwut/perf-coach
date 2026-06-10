"""Tests for issue #386: Add habit_logs table for habit completion tracking.

Each test anchored to one Acceptance Criterion item.
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
    name = f"test_hlogs_386_{uuid.uuid4().hex[:8]}"
    with engine.begin() as conn:
        row = conn.execute(
            text("INSERT INTO users (name) VALUES (:name) RETURNING id"),
            {"name": name},
        ).fetchone()
        uid = str(row.id)
    yield uid
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": uid})


@pytest.fixture(scope="module")
def test_habit_id(test_user_id):
    with engine.begin() as conn:
        row = conn.execute(
            text(
                "INSERT INTO habits (user_id, name, tracking_type) "
                "VALUES (:uid, :name, 'daily_checkmark') RETURNING id"
            ),
            {"uid": test_user_id, "name": f"habit_386_{uuid.uuid4().hex[:8]}"},
        ).fetchone()
        hid = str(row.id)
    yield hid
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM habits WHERE id = :hid"), {"hid": hid})


# ── AC: table exists ──────────────────────────────────────────────────────────

def test_habit_logs_table_exists():
    """AC: habit_logs table exists in public schema."""
    with engine.connect() as conn:
        count = conn.execute(text(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = 'habit_logs'"
        )).scalar()
    assert count == 1, "habit_logs table not found — run alembic upgrade head"


# ── AC: all required columns present ─────────────────────────────────────────

def test_all_required_columns_exist():
    """AC: habit_logs has id, habit_id, user_id, log_date, log_week_start, value, notes, source, created_at, updated_at."""
    required = {
        "id":             False,  # NOT NULL
        "habit_id":       False,
        "user_id":        False,
        "log_date":       False,
        "log_week_start": False,
        "value":          False,
        "notes":          True,   # nullable
        "source":         False,
        "created_at":     True,
        "updated_at":     True,
    }
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT column_name, is_nullable "
            "FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'habit_logs'"
        )).fetchall()
    found = {r.column_name: (r.is_nullable == "YES") for r in rows}
    for col, nullable in required.items():
        assert col in found, f"Column '{col}' missing from habit_logs table"
        assert found[col] == nullable, (
            f"habit_logs.{col}: expected nullable={nullable}, got nullable={found[col]}"
        )


# ── AC: composite index on (habit_id, log_week_start) ────────────────────────

def test_composite_index_exists():
    """AC: composite index on (habit_id, log_week_start) exists."""
    with engine.connect() as conn:
        row = conn.execute(text(
            "SELECT indexname FROM pg_indexes "
            "WHERE tablename = 'habit_logs' "
            "AND indexdef ILIKE '%habit_id%' "
            "AND indexdef ILIKE '%log_week_start%'"
        )).fetchone()
    assert row is not None, (
        "Composite index on (habit_id, log_week_start) not found in habit_logs"
    )


# ── AC: unique constraint on (habit_id, log_date) ────────────────────────────

def test_unique_constraint_habit_log_date_exists():
    """AC: unique constraint on (habit_id, log_date) exists."""
    with engine.connect() as conn:
        row = conn.execute(text(
            "SELECT constraint_name FROM information_schema.table_constraints "
            "WHERE table_schema = 'public' AND table_name = 'habit_logs' "
            "AND constraint_type = 'UNIQUE'"
        )).fetchone()
    assert row is not None, "No UNIQUE constraint found on habit_logs"


# ── AC: FKs have cascade delete ──────────────────────────────────────────────

def test_habit_fk_cascade_delete():
    """AC: FK habit_id → habits has ON DELETE CASCADE."""
    with engine.connect() as conn:
        row = conn.execute(text(
            "SELECT rc.delete_rule "
            "FROM information_schema.referential_constraints rc "
            "JOIN information_schema.key_column_usage kcu "
            "  ON rc.constraint_name = kcu.constraint_name "
            " AND kcu.table_schema = 'public' "
            " AND kcu.table_name = 'habit_logs' "
            " AND kcu.column_name = 'habit_id' "
            "LIMIT 1"
        )).fetchone()
    assert row is not None, "FK from habit_logs.habit_id to habits not found"
    assert row.delete_rule == "CASCADE", (
        f"habit_logs.habit_id FK delete_rule={row.delete_rule!r}, expected CASCADE"
    )


def test_user_fk_cascade_delete():
    """AC: FK user_id → users has ON DELETE CASCADE."""
    with engine.connect() as conn:
        row = conn.execute(text(
            "SELECT rc.delete_rule "
            "FROM information_schema.referential_constraints rc "
            "JOIN information_schema.key_column_usage kcu "
            "  ON rc.constraint_name = kcu.constraint_name "
            " AND kcu.table_schema = 'public' "
            " AND kcu.table_name = 'habit_logs' "
            " AND kcu.column_name = 'user_id' "
            "LIMIT 1"
        )).fetchone()
    assert row is not None, "FK from habit_logs.user_id to users not found"
    assert row.delete_rule == "CASCADE", (
        f"habit_logs.user_id FK delete_rule={row.delete_rule!r}, expected CASCADE"
    )


# ── AC: duplicate (habit_id, log_date) raises unique constraint violation ─────

def test_duplicate_habit_log_date_rejected(test_habit_id):
    """AC: inserting duplicate (habit_id, log_date) raises IntegrityError."""
    log_date = "2026-01-05"
    week_start = "2026-01-05"
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO habit_logs (habit_id, user_id, log_date, log_week_start, value, source) "
            "VALUES (:hid, (SELECT user_id FROM habits WHERE id = :hid), "
            ":log_date, :week_start, 1, 'manual')"
        ), {"hid": test_habit_id, "log_date": log_date, "week_start": week_start})

    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO habit_logs (habit_id, user_id, log_date, log_week_start, value, source) "
                "VALUES (:hid, (SELECT user_id FROM habits WHERE id = :hid), "
                ":log_date, :week_start, 1, 'manual')"
            ), {"hid": test_habit_id, "log_date": log_date, "week_start": week_start})

    # Cleanup
    with engine.begin() as conn:
        conn.execute(text(
            "DELETE FROM habit_logs WHERE habit_id = :hid AND log_date = :log_date"
        ), {"hid": test_habit_id, "log_date": log_date})


# ── AC: cascade delete from habit ────────────────────────────────────────────

def test_cascade_delete_on_habit_delete(test_user_id):
    """AC: deleting a habit removes all related habit_logs rows."""
    with engine.begin() as conn:
        hid_row = conn.execute(text(
            "INSERT INTO habits (user_id, name, tracking_type) "
            "VALUES (:uid, :name, 'daily_checkmark') RETURNING id"
        ), {"uid": test_user_id, "name": f"cascade_habit_{uuid.uuid4().hex[:8]}"}).fetchone()
        hid = str(hid_row.id)

    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO habit_logs (habit_id, user_id, log_date, log_week_start, value, source) "
            "VALUES (:hid, :uid, '2026-01-05', '2026-01-05', 1, 'manual'), "
            "       (:hid, :uid, '2026-01-06', '2026-01-05', 1, 'manual')"
        ), {"hid": hid, "uid": test_user_id})

    with engine.connect() as conn:
        count_before = conn.execute(
            text("SELECT COUNT(*) FROM habit_logs WHERE habit_id = :hid"), {"hid": hid}
        ).scalar()
    assert count_before == 2

    with engine.begin() as conn:
        conn.execute(text("DELETE FROM habits WHERE id = :hid"), {"hid": hid})

    with engine.connect() as conn:
        count_after = conn.execute(
            text("SELECT COUNT(*) FROM habit_logs WHERE habit_id = :hid"), {"hid": hid}
        ).scalar()
    assert count_after == 0, f"Cascade delete failed: {count_after} habit_log rows remain after habit deleted"


# ── AC: cascade delete from user ─────────────────────────────────────────────

def test_cascade_delete_on_user_delete():
    """AC: deleting a user removes all related habit_logs rows."""
    name = f"cascade_user_{uuid.uuid4().hex[:8]}"
    with engine.begin() as conn:
        uid_row = conn.execute(
            text("INSERT INTO users (name) VALUES (:name) RETURNING id"),
            {"name": name},
        ).fetchone()
        uid = str(uid_row.id)

    with engine.begin() as conn:
        hid_row = conn.execute(text(
            "INSERT INTO habits (user_id, name, tracking_type) "
            "VALUES (:uid, 'cascade_test_habit', 'daily_checkmark') RETURNING id"
        ), {"uid": uid}).fetchone()
        hid = str(hid_row.id)

    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO habit_logs (habit_id, user_id, log_date, log_week_start, value, source) "
            "VALUES (:hid, :uid, '2026-02-03', '2026-02-03', 1, 'manual'), "
            "       (:hid, :uid, '2026-02-04', '2026-02-03', 1, 'manual')"
        ), {"hid": hid, "uid": uid})

    with engine.connect() as conn:
        count_before = conn.execute(
            text("SELECT COUNT(*) FROM habit_logs WHERE user_id = :uid"), {"uid": uid}
        ).scalar()
    assert count_before == 2

    with engine.begin() as conn:
        conn.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": uid})

    with engine.connect() as conn:
        count_after = conn.execute(
            text("SELECT COUNT(*) FROM habit_logs WHERE user_id = :uid"), {"uid": uid}
        ).scalar()
    assert count_after == 0, f"Cascade delete failed: {count_after} habit_log rows remain after user deleted"


# ── AC: table-level docstring in migration ────────────────────────────────────

def test_migration_docstring():
    """AC: migration file has the required table docstring."""
    import os
    import glob

    versions_dir = os.path.join(
        os.path.dirname(__file__), "..", "alembic", "versions"
    )
    pattern = os.path.join(versions_dir, "*habit_logs*")
    files = glob.glob(pattern)
    # Find the migration that is NOT the original create (b2c3d4e5f6a7)
    target_files = [f for f in files if "b2c3d4e5f6a7" not in f]
    assert target_files, (
        "No migration file matching '*habit_logs*' (excluding b2c3d4e5f6a7) found in alembic/versions/"
    )

    expected = (
        "Habit log entries. For daily_checkmark habits, one row per day checked (value=1). "
        "For weekly_count/minutes/quantity habits, one row per logged event with the contributed value. "
        "Week aggregation done at read time by summing values where log_week_start matches."
    )
    with open(target_files[0]) as f:
        content = f.read()
    assert expected in content, (
        f"Table docstring not found in {target_files[0]}.\nExpected substring:\n{expected}"
    )


# ── AC: value defaults to 1, source defaults to manual ───────────────────────

def test_value_defaults_to_one(test_habit_id):
    """AC: value column defaults to 1 when not supplied."""
    with engine.begin() as conn:
        row = conn.execute(text(
            "INSERT INTO habit_logs (habit_id, user_id, log_date, log_week_start, source) "
            "VALUES (:hid, (SELECT user_id FROM habits WHERE id = :hid), "
            "'2026-03-10', '2026-03-09', 'manual') "
            "RETURNING id, value"
        ), {"hid": test_habit_id}).fetchone()
        assert float(row.value) == 1.0, f"Expected value=1, got {row.value}"
        conn.execute(text("DELETE FROM habit_logs WHERE id = :id"), {"id": str(row.id)})


def test_source_defaults_to_manual(test_habit_id):
    """AC: source column defaults to 'manual' when not supplied."""
    with engine.begin() as conn:
        row = conn.execute(text(
            "INSERT INTO habit_logs (habit_id, user_id, log_date, log_week_start) "
            "VALUES (:hid, (SELECT user_id FROM habits WHERE id = :hid), "
            "'2026-03-11', '2026-03-09') "
            "RETURNING id, source"
        ), {"hid": test_habit_id}).fetchone()
        assert row.source == "manual", f"Expected source='manual', got {row.source!r}"
        conn.execute(text("DELETE FROM habit_logs WHERE id = :id"), {"id": str(row.id)})


# ── AC: week aggregation via log_week_start ───────────────────────────────────

def test_week_aggregation_by_log_week_start(test_habit_id):
    """AC: SUM(value) GROUP BY log_week_start returns correct per-week sums."""
    rows_to_insert = [
        ("2026-04-07", "2026-04-06", 1),  # week of Apr 6
        ("2026-04-08", "2026-04-06", 2),  # week of Apr 6
        ("2026-04-14", "2026-04-13", 3),  # week of Apr 13
    ]
    inserted_ids = []
    with engine.begin() as conn:
        for log_date, week_start, val in rows_to_insert:
            row = conn.execute(text(
                "INSERT INTO habit_logs (habit_id, user_id, log_date, log_week_start, value, source) "
                "VALUES (:hid, (SELECT user_id FROM habits WHERE id = :hid), "
                ":log_date, :week_start, :val, 'manual') "
                "RETURNING id"
            ), {"hid": test_habit_id, "log_date": log_date, "week_start": week_start, "val": val}).fetchone()
            inserted_ids.append(str(row.id))

    with engine.connect() as conn:
        agg = conn.execute(text(
            "SELECT log_week_start, SUM(value) AS total "
            "FROM habit_logs "
            "WHERE habit_id = :hid AND log_date IN ('2026-04-07','2026-04-08','2026-04-14') "
            "GROUP BY log_week_start ORDER BY log_week_start"
        ), {"hid": test_habit_id}).fetchall()

    week_sums = {str(r.log_week_start): float(r.total) for r in agg}
    assert week_sums.get("2026-04-06") == 3.0, f"Expected week Apr 6 = 3, got {week_sums}"
    assert week_sums.get("2026-04-13") == 3.0, f"Expected week Apr 13 = 3, got {week_sums}"

    with engine.begin() as conn:
        for rid in inserted_ids:
            conn.execute(text("DELETE FROM habit_logs WHERE id = :id"), {"id": rid})
