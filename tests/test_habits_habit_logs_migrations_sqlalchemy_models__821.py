"""Tests for issue #821: Add habits and habit_logs migrations and SQLAlchemy models.

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
    name = f"test_821_{uuid.uuid4().hex[:8]}"
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
                "INSERT INTO habits (user_id, name, habit_type, schedule_type, display_order) "
                "VALUES (:uid, :name, 'binary', 'daily', 0) RETURNING id"
            ),
            {"uid": test_user_id, "name": f"habit_821_{uuid.uuid4().hex[:8]}"},
        ).fetchone()
        hid = str(row.id)
    yield hid
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM habits WHERE id = :hid"), {"hid": hid})


# ── AC: migration file exists ──────────────────────────────────────────────────

def test_migration_file_exists():
    """AC: A single Alembic migration file exists that creates both habits and habit_logs."""
    import os
    import glob
    versions_dir = os.path.join(
        os.path.dirname(__file__), "..", "alembic", "versions"
    )
    pattern = os.path.join(versions_dir, "*habits_and_habit_logs*")
    files = glob.glob(pattern)
    assert files, "No migration file matching '*habits_and_habit_logs*' found in alembic/versions/"


# ── AC: habits table v2 columns ───────────────────────────────────────────────

def test_habits_table_has_all_v2_columns():
    """AC: habits table contains all v2 columns with correct nullability."""
    required = {
        "id":              False,  # NOT NULL
        "user_id":         False,  # NOT NULL
        "name":            False,  # NOT NULL
        "habit_type":      False,  # NOT NULL, default 'binary'
        "target_value":    True,   # nullable
        "unit":            True,   # nullable
        "schedule_type":   False,  # NOT NULL, default 'daily'
        "schedule_target": True,   # nullable
        "active":          False,  # NOT NULL, default true
        "display_order":   False,  # NOT NULL
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


def test_habits_habit_type_invalid_rejected(test_user_id):
    """AC: habit_type constrained to exactly binary, count, duration."""
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO habits (user_id, name, habit_type, schedule_type, display_order) "
                "VALUES (:uid, 'bad', 'streak', 'daily', 0)"
            ), {"uid": test_user_id})


def test_habits_habit_type_binary_accepted(test_user_id):
    """AC: habit_type='binary' accepted."""
    with engine.begin() as conn:
        row = conn.execute(text(
            "INSERT INTO habits (user_id, name, habit_type, schedule_type, display_order) "
            "VALUES (:uid, 'b_test', 'binary', 'daily', 0) RETURNING id"
        ), {"uid": test_user_id}).fetchone()
        conn.execute(text("DELETE FROM habits WHERE id = :id"), {"id": str(row.id)})


def test_habits_habit_type_count_accepted(test_user_id):
    """AC: habit_type='count' accepted."""
    with engine.begin() as conn:
        row = conn.execute(text(
            "INSERT INTO habits (user_id, name, habit_type, schedule_type, display_order) "
            "VALUES (:uid, 'c_test', 'count', 'daily', 0) RETURNING id"
        ), {"uid": test_user_id}).fetchone()
        conn.execute(text("DELETE FROM habits WHERE id = :id"), {"id": str(row.id)})


def test_habits_habit_type_duration_accepted(test_user_id):
    """AC: habit_type='duration' accepted."""
    with engine.begin() as conn:
        row = conn.execute(text(
            "INSERT INTO habits (user_id, name, habit_type, schedule_type, display_order) "
            "VALUES (:uid, 'd_test', 'duration', 'daily', 0) RETURNING id"
        ), {"uid": test_user_id}).fetchone()
        conn.execute(text("DELETE FROM habits WHERE id = :id"), {"id": str(row.id)})


def test_habits_schedule_type_invalid_rejected(test_user_id):
    """AC: schedule_type constrained to exactly daily, weekly, times_per_week."""
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO habits (user_id, name, habit_type, schedule_type, display_order) "
                "VALUES (:uid, 'bad', 'binary', 'monthly', 0)"
            ), {"uid": test_user_id})


def test_habits_schedule_type_daily_accepted(test_user_id):
    """AC: schedule_type='daily' accepted."""
    with engine.begin() as conn:
        row = conn.execute(text(
            "INSERT INTO habits (user_id, name, habit_type, schedule_type, display_order) "
            "VALUES (:uid, 'st_daily', 'binary', 'daily', 0) RETURNING id"
        ), {"uid": test_user_id}).fetchone()
        conn.execute(text("DELETE FROM habits WHERE id = :id"), {"id": str(row.id)})


def test_habits_schedule_type_weekly_accepted(test_user_id):
    """AC: schedule_type='weekly' accepted."""
    with engine.begin() as conn:
        row = conn.execute(text(
            "INSERT INTO habits (user_id, name, habit_type, schedule_type, display_order) "
            "VALUES (:uid, 'st_weekly', 'binary', 'weekly', 0) RETURNING id"
        ), {"uid": test_user_id}).fetchone()
        conn.execute(text("DELETE FROM habits WHERE id = :id"), {"id": str(row.id)})


def test_habits_schedule_type_times_per_week_accepted(test_user_id):
    """AC: schedule_type='times_per_week' accepted."""
    with engine.begin() as conn:
        row = conn.execute(text(
            "INSERT INTO habits (user_id, name, habit_type, schedule_type, display_order) "
            "VALUES (:uid, 'st_tpw', 'count', 'times_per_week', 0) RETURNING id"
        ), {"uid": test_user_id}).fetchone()
        conn.execute(text("DELETE FROM habits WHERE id = :id"), {"id": str(row.id)})


def test_habits_active_defaults_to_true(test_user_id):
    """AC: active defaults to true."""
    with engine.begin() as conn:
        row = conn.execute(text(
            "INSERT INTO habits (user_id, name, habit_type, schedule_type, display_order) "
            "VALUES (:uid, 'active_def', 'binary', 'daily', 0) RETURNING id, active"
        ), {"uid": test_user_id}).fetchone()
        assert row.active is True, f"Expected active=True, got {row.active}"
        conn.execute(text("DELETE FROM habits WHERE id = :id"), {"id": str(row.id)})


# ── AC: habit_logs table v2 columns ───────────────────────────────────────────

def test_habit_logs_has_note_column():
    """AC: habit_logs table has note column (nullable)."""
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT column_name, is_nullable "
            "FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'habit_logs'"
        )).fetchall()
    found = {r.column_name: (r.is_nullable == "YES") for r in rows}
    assert "note" in found, "Column 'note' missing from habit_logs table"
    assert found["note"] is True, "habit_logs.note should be nullable"


def test_habit_logs_required_columns_present():
    """AC: habit_logs contains id, habit_id, user_id, log_date, value, note."""
    required = {
        "id":       False,
        "habit_id": False,
        "user_id":  False,
        "log_date": False,
        "value":    False,
        "note":     True,
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


def test_habit_logs_unique_constraint_on_habit_id_log_date(test_habit_id, test_user_id):
    """AC: Unique constraint exists on habit_logs(habit_id, log_date)."""
    log_date = "2026-07-01"
    week_start = "2026-06-29"
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO habit_logs (habit_id, user_id, log_date, log_week_start, value, source) "
            "VALUES (:hid, :uid, :ld, :ws, 1, 'manual')"
        ), {"hid": test_habit_id, "uid": test_user_id, "ld": log_date, "ws": week_start})

    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO habit_logs (habit_id, user_id, log_date, log_week_start, value, source) "
                "VALUES (:hid, :uid, :ld, :ws, 1, 'manual')"
            ), {"hid": test_habit_id, "uid": test_user_id, "ld": log_date, "ws": week_start})

    with engine.begin() as conn:
        conn.execute(text(
            "DELETE FROM habit_logs WHERE habit_id = :hid AND log_date = :ld"
        ), {"hid": test_habit_id, "ld": log_date})


# ── AC: Habit ORM model columns ───────────────────────────────────────────────

def test_habit_model_has_all_v2_columns():
    """AC: Habit SQLAlchemy model declares all required v2 columns."""
    from backend.models import Habit
    cols = {c.key for c in Habit.__table__.columns}
    required = {"id", "user_id", "name", "habit_type", "target_value", "unit",
                "schedule_type", "schedule_target", "active", "display_order",
                "created_at", "updated_at"}
    missing = required - cols
    assert not missing, f"Habit model missing columns: {missing}"


def test_habit_log_model_has_all_v2_columns():
    """AC: HabitLog SQLAlchemy model declares all required v2 columns."""
    from backend.models import HabitLog
    cols = {c.key for c in HabitLog.__table__.columns}
    required = {"id", "habit_id", "user_id", "log_date", "value", "note",
                "created_at", "updated_at"}
    missing = required - cols
    assert not missing, f"HabitLog model missing columns: {missing}"


# ── AC: relationship back-population ──────────────────────────────────────────

def test_habit_model_has_habit_logs_relationship():
    """AC: Habit model exposes a habit_logs relationship back-populated on HabitLog."""
    from backend.models import Habit
    assert hasattr(Habit, "habit_logs"), "Habit model missing 'habit_logs' relationship"


def test_habit_log_model_has_back_populated_relationship():
    """AC: HabitLog model has back-populated 'habit' relationship."""
    from backend.models import HabitLog
    assert hasattr(HabitLog, "habit"), "HabitLog model missing 'habit' relationship"


# ── AC: ORM-level validation ───────────────────────────────────────────────────

def test_habit_model_validates_habit_type_at_orm_level():
    """AC: Habit ORM model validates habit_type (binary, count, duration)."""
    from backend.models import Habit
    with pytest.raises(ValueError):
        Habit(
            user_id=uuid.uuid4(),
            name="test",
            habit_type="streak",
            schedule_type="daily",
            display_order=0,
        )


def test_habit_model_validates_schedule_type_at_orm_level():
    """AC: Habit ORM model validates schedule_type (daily, weekly, times_per_week)."""
    from backend.models import Habit
    with pytest.raises(ValueError):
        Habit(
            user_id=uuid.uuid4(),
            name="test",
            habit_type="binary",
            schedule_type="monthly",
            display_order=0,
        )


def test_habit_model_accepts_all_valid_habit_types():
    """AC: Habit ORM model accepts all three valid habit_type values."""
    from backend.models import Habit
    for ht in ("binary", "count", "duration"):
        h = Habit(
            user_id=uuid.uuid4(),
            name="ok",
            habit_type=ht,
            schedule_type="daily",
            display_order=0,
        )
        assert h.habit_type == ht


def test_habit_model_accepts_all_valid_schedule_types():
    """AC: Habit ORM model accepts all three valid schedule_type values."""
    from backend.models import Habit
    for st in ("daily", "weekly", "times_per_week"):
        h = Habit(
            user_id=uuid.uuid4(),
            name="ok",
            habit_type="binary",
            schedule_type=st,
            display_order=0,
        )
        assert h.schedule_type == st


# ── AC: no hardcoded user IDs ─────────────────────────────────────────────────

def test_no_hardcoded_user_id_in_migration():
    """AC: No user ID or any user value is hardcoded anywhere in the migration."""
    import os
    import glob
    versions_dir = os.path.join(
        os.path.dirname(__file__), "..", "alembic", "versions"
    )
    pattern = os.path.join(versions_dir, "*habits_and_habit_logs*")
    files = glob.glob(pattern)
    assert files, "Migration file not found"
    with open(files[0]) as f:
        content = f.read()
    # Check for obvious hardcoded user patterns
    forbidden = ["user_id = 1", "user_id = '1'", "WHERE user_id = 1"]
    for pat in forbidden:
        assert pat not in content, (
            f"Hardcoded user_id pattern '{pat}' found in migration"
        )


# ── AC: null/missing input returns (None, reason) ─────────────────────────────

def test_effective_schedule_target_returns_none_reason_when_null():
    """AC: Model method returns (None, reason) for null schedule_target."""
    from backend.models import Habit
    h = Habit(
        user_id=uuid.uuid4(),
        name="test",
        habit_type="count",
        schedule_type="times_per_week",
        display_order=0,
        schedule_target=None,
    )
    result = h.effective_schedule_target()
    assert result[0] is None, f"Expected None, got {result[0]}"
    assert isinstance(result[1], str) and result[1], (
        f"Expected non-empty reason string, got {result[1]!r}"
    )


def test_effective_schedule_target_returns_value_when_set():
    """AC: Model method returns (value, None) when schedule_target is set."""
    from backend.models import Habit
    h = Habit(
        user_id=uuid.uuid4(),
        name="test",
        habit_type="count",
        schedule_type="times_per_week",
        display_order=0,
        schedule_target=3,
    )
    result = h.effective_schedule_target()
    assert result[0] == 3, f"Expected 3, got {result[0]}"
    assert result[1] is None, f"Expected None reason, got {result[1]!r}"


# ── AC: FK cascade from habit to habit_logs ───────────────────────────────────

def test_habit_logs_cascade_delete_on_habit_delete(test_user_id):
    """AC: Deleting a habit cascades to its habit_logs rows."""
    with engine.begin() as conn:
        hrow = conn.execute(text(
            "INSERT INTO habits (user_id, name, habit_type, schedule_type, display_order) "
            "VALUES (:uid, 'cascade_821', 'binary', 'daily', 0) RETURNING id"
        ), {"uid": test_user_id}).fetchone()
        hid = str(hrow.id)
        conn.execute(text(
            "INSERT INTO habit_logs "
            "(habit_id, user_id, log_date, log_week_start, value, source) "
            "VALUES (:hid, :uid, '2026-07-10', '2026-07-07', 1, 'manual')"
        ), {"hid": hid, "uid": test_user_id})

    with engine.begin() as conn:
        conn.execute(text("DELETE FROM habits WHERE id = :hid"), {"hid": hid})

    with engine.connect() as conn:
        count = conn.execute(
            text("SELECT COUNT(*) FROM habit_logs WHERE habit_id = :hid"), {"hid": hid}
        ).scalar()
    assert count == 0, f"Expected 0 habit_logs after cascade, got {count}"


# ── AC: ORM relationship works end-to-end ─────────────────────────────────────

def test_orm_relationship_habit_to_habit_logs(test_user_id):
    """AC: Habit.habit_logs relationship returns HabitLog instances."""
    from sqlalchemy.orm import Session
    from backend.models import Habit, HabitLog

    with Session(engine) as session:
        habit = Habit(
            user_id=uuid.UUID(test_user_id),
            name=f"orm_rel_821_{uuid.uuid4().hex[:6]}",
            habit_type="binary",
            schedule_type="daily",
            display_order=0,
        )
        session.add(habit)
        session.flush()

        log = HabitLog(
            habit_id=habit.id,
            user_id=uuid.UUID(test_user_id),
            log_date="2026-07-15",
            log_week_start="2026-07-14",
            value=1,
            source="manual",
        )
        session.add(log)
        session.commit()
        hid = str(habit.id)
        lid = str(log.id)

    with Session(engine) as session:
        h = session.get(Habit, uuid.UUID(hid))
        assert h is not None
        assert len(h.habit_logs) == 1
        assert str(h.habit_logs[0].id) == lid

    with engine.begin() as conn:
        conn.execute(text("DELETE FROM habits WHERE id = :hid"), {"hid": hid})
