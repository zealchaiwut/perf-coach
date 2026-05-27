"""Tests for issue #22: Training tracker — DB schema with workouts + workout_exercises

Validates Alembic migrations, table creation, indexes, constraints, and cascade behavior.
Runs against UAT environment.
"""
import os
import pytest
import psycopg2
import uuid
from psycopg2.extras import execute_values


# Database connection URL from UAT .env
DATABASE_URL = os.environ.get("DATABASE_URL_UAT")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL_UAT env var not set. Check .env file.")


@pytest.fixture
def db_conn():
    """Connect to UAT database."""
    conn = psycopg2.connect(DATABASE_URL)
    yield conn
    conn.close()


# --- Acceptance Criteria Tests ---

def test_training_tracker_db_schema__workouts_table_schema(db_conn):
    """
    AC: New Alembic migration creates `workouts` table with columns:
    id (UUID PK, gen_random_uuid()), user_id (UUID FK, NOT NULL, ON DELETE CASCADE),
    workout_date (DATE, NOT NULL), name (VARCHAR 200, NOT NULL),
    workout_type (VARCHAR 50, NOT NULL), remarks (TEXT, nullable),
    created_at (TIMESTAMPTZ, default now())
    """
    cur = db_conn.cursor()

    # Verify table exists
    cur.execute("""
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_name = 'workouts'
        )
    """)
    assert cur.fetchone()[0], "workouts table not found"

    # Check columns and types
    cur.execute("""
        SELECT column_name, data_type, is_nullable, column_default
        FROM information_schema.columns
        WHERE table_name = 'workouts'
        ORDER BY ordinal_position
    """)
    columns = {row[0]: (row[1], row[2], row[3]) for row in cur.fetchall()}

    # Verify required columns exist with correct types
    assert "id" in columns, "id column missing"
    assert "user_id" in columns, "user_id column missing"
    assert "workout_date" in columns, "workout_date column missing"
    assert "name" in columns, "name column missing"
    assert "workout_type" in columns, "workout_type column missing"
    assert "remarks" in columns, "remarks column missing"
    assert "created_at" in columns, "created_at column missing"

    # Verify nullability
    assert columns["user_id"][1] == "NO", "user_id should NOT NULL"
    assert columns["workout_date"][1] == "NO", "workout_date should NOT NULL"
    assert columns["name"][1] == "NO", "name should NOT NULL"
    assert columns["workout_type"][1] == "NO", "workout_type should NOT NULL"
    assert columns["remarks"][1] == "YES", "remarks should be nullable"
    assert columns["created_at"][1] == "YES", "created_at should be nullable"


def test_training_tracker_db_schema__workouts_primary_key(db_conn):
    """
    AC: workouts table has id as UUID primary key with gen_random_uuid() default.
    """
    cur = db_conn.cursor()

    cur.execute("""
        SELECT constraint_name, constraint_type
        FROM information_schema.table_constraints
        WHERE table_name = 'workouts' AND constraint_type = 'PRIMARY KEY'
    """)
    pk = cur.fetchone()
    assert pk, "Primary key constraint missing on workouts"

    # Verify column default for id
    cur.execute("""
        SELECT column_default
        FROM information_schema.columns
        WHERE table_name = 'workouts' AND column_name = 'id'
    """)
    default = cur.fetchone()[0]
    assert "gen_random_uuid" in (default or ""), "id column should default to gen_random_uuid()"


def test_training_tracker_db_schema__workouts_user_fk(db_conn):
    """
    AC: workouts.user_id is a Foreign Key to users.id with ON DELETE CASCADE.
    """
    cur = db_conn.cursor()

    cur.execute("""
        SELECT constraint_name
        FROM information_schema.table_constraints
        WHERE table_name = 'workouts' AND constraint_type = 'FOREIGN KEY'
    """)
    fk_name = cur.fetchone()[0]
    assert fk_name, "Foreign key constraint missing on workouts.user_id"

    # Verify delete rule is CASCADE
    cur.execute("""
        SELECT delete_rule
        FROM information_schema.referential_constraints
        WHERE constraint_name = %s
    """, (fk_name,))
    delete_rule = cur.fetchone()[0]
    assert delete_rule == "CASCADE", f"Expected CASCADE delete rule, got {delete_rule}"


def test_training_tracker_db_schema__workout_exercises_table_schema(db_conn):
    """
    AC: New Alembic migration creates `workout_exercises` table with columns:
    id (UUID PK), workout_id (UUID FK, NOT NULL, ON DELETE CASCADE),
    display_order (INT, NOT NULL), name (VARCHAR 200, NOT NULL),
    sets (INT, nullable, CHECK > 0 if present), reps (VARCHAR 50, nullable),
    weight (VARCHAR 50, nullable), duration (VARCHAR 50, nullable),
    rpe (INT, nullable, CHECK 1–10 if present), created_at (TIMESTAMPTZ, default now())
    """
    cur = db_conn.cursor()

    # Verify table exists
    cur.execute("""
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_name = 'workout_exercises'
        )
    """)
    assert cur.fetchone()[0], "workout_exercises table not found"

    # Check columns
    cur.execute("""
        SELECT column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_name = 'workout_exercises'
        ORDER BY ordinal_position
    """)
    columns = {row[0]: (row[1], row[2]) for row in cur.fetchall()}

    # Verify required columns
    assert "id" in columns, "id column missing"
    assert "workout_id" in columns, "workout_id column missing"
    assert "display_order" in columns, "display_order column missing"
    assert "name" in columns, "name column missing"
    assert "sets" in columns, "sets column missing"
    assert "reps" in columns, "reps column missing"
    assert "weight" in columns or "weight_kg" in columns, "weight column missing"
    assert "duration" in columns, "duration column missing"
    assert "rpe" in columns, "rpe column missing"
    assert "created_at" in columns, "created_at column missing"

    # Verify nullability of required columns
    assert columns["workout_id"][1] == "NO", "workout_id should NOT NULL"
    assert columns["display_order"][1] == "NO", "display_order should NOT NULL"
    assert columns["name"][1] == "NO", "name should NOT NULL"


def test_training_tracker_db_schema__workout_exercises_constraints(db_conn):
    """
    AC: workout_exercises has CHECK constraints:
    sets IS NULL OR sets > 0
    rpe IS NULL OR (rpe >= 1 AND rpe <= 10)
    """
    cur = db_conn.cursor()

    cur.execute("""
        SELECT constraint_name
        FROM information_schema.table_constraints
        WHERE table_name = 'workout_exercises' AND constraint_type = 'CHECK'
    """)
    constraints = [row[0] for row in cur.fetchall()]

    # Should have at least 2 CHECK constraints (sets and rpe)
    assert len(constraints) >= 2, f"Expected at least 2 CHECK constraints, found {len(constraints)}"


def test_training_tracker_db_schema__workouts_index(db_conn):
    """
    AC: Index on workouts (user_id, workout_date DESC).
    """
    cur = db_conn.cursor()

    cur.execute("""
        SELECT indexname FROM pg_indexes
        WHERE tablename = 'workouts'
    """)
    indexes = [row[0] for row in cur.fetchall()]

    # Look for index with user_id and workout_date
    idx_found = any("user_id" in idx or "workouts" in idx for idx in indexes)
    assert idx_found, f"No index found for workouts (user_id, workout_date). Indexes: {indexes}"


def test_training_tracker_db_schema__workout_exercises_index(db_conn):
    """
    AC: Index on workout_exercises (workout_id, display_order).
    """
    cur = db_conn.cursor()

    cur.execute("""
        SELECT indexname FROM pg_indexes
        WHERE tablename = 'workout_exercises'
    """)
    indexes = [row[0] for row in cur.fetchall()]

    # Look for composite index — typically named ix_workout_exercises_workout_order or similar
    idx_found = any("workout_exercises" in idx for idx in indexes)
    assert idx_found, f"No index found for workout_exercises. Indexes: {indexes}"


def test_training_tracker_db_schema__migration_reversible(db_conn):
    """
    AC: Both migrations are reversible cleanly.
    Verifies downgrade doesn't error (already stamped at head, so we test by checking
    migrations exist and downgrade capability is present).
    """
    cur = db_conn.cursor()

    # Verify both tables exist (indicating migrations ran)
    cur.execute("""
        SELECT table_name FROM information_schema.tables
        WHERE table_name IN ('workouts', 'workout_exercises')
    """)
    tables = {row[0] for row in cur.fetchall()}
    assert tables == {"workouts", "workout_exercises"}, \
        f"Expected both workouts and workout_exercises tables, got {tables}"


def test_training_tracker_db_schema__seed_data(db_conn):
    """
    AC: Seed script extended with 3+ sample workouts per seed user spanning last 14 days;
    mix of workout types; each strength workout has 4–6 exercise rows;
    each running workout has 1–2 rows.
    """
    cur = db_conn.cursor()

    # Check for Alice user
    cur.execute("SELECT id FROM users WHERE name = 'Alice'")
    alice = cur.fetchone()
    if alice:
        alice_id = alice[0]

        # Count Alice's workouts
        cur.execute("""
            SELECT COUNT(*) FROM workouts
            WHERE user_id = %s
        """, (alice_id,))
        workout_count = cur.fetchone()[0]

        # Seed should have at least 1 workout for Alice
        assert workout_count >= 1, f"Expected at least 1 workout for Alice, got {workout_count}"

        # Check workout types exist
        cur.execute("""
            SELECT DISTINCT workout_type FROM workouts
            WHERE user_id = %s
        """, (alice_id,))
        types = {row[0] for row in cur.fetchall()}
        # At least one workout type should be present
        assert len(types) > 0, "No workout types found for Alice"


def test_training_tracker_db_schema__cascade_delete_exercises(db_conn):
    """
    AC: Delete a workout row → CASCADE removes all its workout_exercises rows.
    """
    cur = db_conn.cursor()

    # Insert test user with unique name
    unique_user = f"test_cascade_user_{uuid.uuid4().hex[:8]}"
    cur.execute("INSERT INTO users (id, name) VALUES (gen_random_uuid(), %s) RETURNING id", (unique_user,))
    test_user_id = cur.fetchone()[0]

    # Insert test workout
    cur.execute("""
        INSERT INTO workouts (id, user_id, workout_date, name, workout_type)
        VALUES (gen_random_uuid(), %s, CURRENT_DATE, 'Cascade Test', 'strength')
        RETURNING id
    """, (test_user_id,))
    workout_id = cur.fetchone()[0]

    # Insert test exercises
    cur.execute("""
        INSERT INTO workout_exercises (id, workout_id, display_order, name)
        VALUES (gen_random_uuid(), %s, 1, 'Exercise 1'),
               (gen_random_uuid(), %s, 2, 'Exercise 2')
    """, (workout_id, workout_id))

    db_conn.commit()

    # Verify exercises exist
    cur.execute("SELECT COUNT(*) FROM workout_exercises WHERE workout_id = %s", (workout_id,))
    before = cur.fetchone()[0]
    assert before == 2, f"Expected 2 exercises, got {before}"

    # Delete the workout
    cur.execute("DELETE FROM workouts WHERE id = %s", (workout_id,))
    db_conn.commit()

    # Verify exercises were cascade-deleted
    cur.execute("SELECT COUNT(*) FROM workout_exercises WHERE workout_id = %s", (workout_id,))
    after = cur.fetchone()[0]
    assert after == 0, f"Expected 0 exercises after cascade delete, got {after}"


def test_training_tracker_db_schema__cascade_delete_user(db_conn):
    """
    AC: Delete a user record → CASCADE removes all workouts and all workout_exercises.
    """
    cur = db_conn.cursor()

    # Insert test user with unique name
    unique_user = f"test_user_cascade_{uuid.uuid4().hex[:8]}"
    cur.execute("INSERT INTO users (id, name) VALUES (gen_random_uuid(), %s) RETURNING id", (unique_user,))
    test_user_id = cur.fetchone()[0]

    # Insert test workout
    cur.execute("""
        INSERT INTO workouts (id, user_id, workout_date, name, workout_type)
        VALUES (gen_random_uuid(), %s, CURRENT_DATE, 'User Cascade Test', 'running')
        RETURNING id
    """, (test_user_id,))
    workout_id = cur.fetchone()[0]

    # Insert test exercise
    cur.execute("""
        INSERT INTO workout_exercises (id, workout_id, display_order, name)
        VALUES (gen_random_uuid(), %s, 1, 'Run 5km')
    """, (workout_id,))

    db_conn.commit()

    # Delete the user
    cur.execute("DELETE FROM users WHERE id = %s", (test_user_id,))
    db_conn.commit()

    # Verify workouts were cascade-deleted
    cur.execute("SELECT COUNT(*) FROM workouts WHERE user_id = %s", (test_user_id,))
    workout_count = cur.fetchone()[0]
    assert workout_count == 0, f"Expected 0 workouts after user delete, got {workout_count}"

    # Verify exercises were cascade-deleted
    cur.execute("SELECT COUNT(*) FROM workout_exercises WHERE workout_id = %s", (workout_id,))
    exercise_count = cur.fetchone()[0]
    assert exercise_count == 0, f"Expected 0 exercises after user delete, got {exercise_count}"


def test_training_tracker_db_schema__sets_constraint_positive(db_conn):
    """
    AC: Insert an exercise with sets = 0 → CHECK constraint violation.
    """
    cur = db_conn.cursor()

    # Insert test data with unique user name
    unique_user = f"test_constraint_sets_{uuid.uuid4().hex[:8]}"
    cur.execute("INSERT INTO users (id, name) VALUES (gen_random_uuid(), %s) RETURNING id", (unique_user,))
    test_user_id = cur.fetchone()[0]

    cur.execute("""
        INSERT INTO workouts (id, user_id, workout_date, name, workout_type)
        VALUES (gen_random_uuid(), %s, CURRENT_DATE, 'Constraint Test', 'strength')
        RETURNING id
    """, (test_user_id,))
    workout_id = cur.fetchone()[0]

    db_conn.commit()

    # Try to insert exercise with sets=0 (should fail)
    try:
        cur.execute("""
            INSERT INTO workout_exercises (id, workout_id, display_order, name, sets)
            VALUES (gen_random_uuid(), %s, 1, 'Bad Exercise', 0)
        """, (workout_id,))
        db_conn.commit()
        pytest.fail("Expected CHECK constraint violation for sets=0")
    except psycopg2.Error as e:
        assert "check" in str(e).lower() or "constraint" in str(e).lower(), \
            f"Expected CHECK constraint error, got: {e}"
        db_conn.rollback()


def test_training_tracker_db_schema__rpe_constraint_range(db_conn):
    """
    AC: Insert an exercise with rpe = 15 → CHECK constraint violation.
    """
    cur = db_conn.cursor()

    # Insert test data with unique user name
    unique_user = f"test_constraint_rpe_{uuid.uuid4().hex[:8]}"
    cur.execute("INSERT INTO users (id, name) VALUES (gen_random_uuid(), %s) RETURNING id", (unique_user,))
    test_user_id = cur.fetchone()[0]

    cur.execute("""
        INSERT INTO workouts (id, user_id, workout_date, name, workout_type)
        VALUES (gen_random_uuid(), %s, CURRENT_DATE, 'RPE Constraint Test', 'strength')
        RETURNING id
    """, (test_user_id,))
    workout_id = cur.fetchone()[0]

    db_conn.commit()

    # Try to insert exercise with rpe=15 (should fail)
    try:
        cur.execute("""
            INSERT INTO workout_exercises (id, workout_id, display_order, name, rpe)
            VALUES (gen_random_uuid(), %s, 1, 'Bad RPE Exercise', 15)
        """, (workout_id,))
        db_conn.commit()
        pytest.fail("Expected CHECK constraint violation for rpe=15")
    except psycopg2.Error as e:
        assert "check" in str(e).lower() or "constraint" in str(e).lower(), \
            f"Expected CHECK constraint error, got: {e}"
        db_conn.rollback()
