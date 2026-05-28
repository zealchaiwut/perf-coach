"""Tests for issue #38: Create daily_metrics table for rhr, hrv, sleep, energy, mood

Validates Alembic migrations, table creation, columns, constraints, indexes,
cascade behavior, triggers, and seed data. Runs against UAT environment.
"""
import os
import pytest
import psycopg2
import uuid
from datetime import date, timedelta
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


def get_alice_id(db_conn):
    """Fetch Alice's user ID from the database."""
    cur = db_conn.cursor()
    cur.execute("SELECT id FROM users WHERE name = 'Alice'")
    result = cur.fetchone()
    return result[0] if result else None


# --- Acceptance Criteria Tests ---

def test_daily_metrics_table__table_exists_with_correct_schema(db_conn):
    """
    AC: New Alembic migration creates `daily_metrics` table with columns:
    - id (UUID PK, default gen_random_uuid())
    - user_id (UUID FK → users.id, NOT NULL, ON DELETE CASCADE)
    - metric_date (DATE, NOT NULL)
    - resting_hr (INT, nullable, CHECK 20–200 if present)
    - hrv (INT, nullable, CHECK 0–300 if present)
    - sleep_hours (DECIMAL(3,1), nullable, CHECK 0–24 if present)
    - sleep_quality (INT, nullable, CHECK 1–5 if present)
    - energy (INT, nullable, CHECK 1–5 if present)
    - mood (INT, nullable, CHECK 1–5 if present)
    - notes (TEXT, nullable)
    - created_at (TIMESTAMPTZ, default now())
    - updated_at (TIMESTAMPTZ, default now())
    """
    cur = db_conn.cursor()

    # Verify table exists
    cur.execute("""
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_name = 'daily_metrics'
        )
    """)
    assert cur.fetchone()[0], "daily_metrics table not found"

    # Check columns and types
    cur.execute("""
        SELECT column_name, data_type, is_nullable, column_default
        FROM information_schema.columns
        WHERE table_name = 'daily_metrics'
        ORDER BY ordinal_position
    """)
    columns = {row[0]: {"type": row[1], "nullable": row[2], "default": row[3]} for row in cur.fetchall()}

    # Verify all required columns exist
    required_columns = [
        "id", "user_id", "metric_date", "resting_hr", "hrv",
        "sleep_hours", "sleep_quality", "energy", "mood", "notes",
        "created_at", "updated_at"
    ]
    for col in required_columns:
        assert col in columns, f"Column {col} missing from daily_metrics"

    # Verify nullability of NOT NULL columns
    assert columns["user_id"]["nullable"] == "NO", "user_id should be NOT NULL"
    assert columns["metric_date"]["nullable"] == "NO", "metric_date should be NOT NULL"

    # Verify nullable columns
    nullable_cols = ["resting_hr", "hrv", "sleep_hours", "sleep_quality", "energy", "mood", "notes"]
    for col in nullable_cols:
        assert columns[col]["nullable"] == "YES", f"{col} should be nullable"

    # Verify id has gen_random_uuid() default
    assert "gen_random_uuid" in (columns["id"]["default"] or ""), "id should default to gen_random_uuid()"

    # Verify created_at and updated_at have now() default
    assert "now()" in (columns["created_at"]["default"] or ""), "created_at should default to now()"
    assert "now()" in (columns["updated_at"]["default"] or ""), "updated_at should default to now()"


def test_daily_metrics_table__unique_constraint_user_date(db_conn):
    """
    AC: Unique constraint on (user_id, metric_date) — one row per user per day.
    """
    cur = db_conn.cursor()

    # Check for unique constraint
    cur.execute("""
        SELECT constraint_name
        FROM information_schema.table_constraints
        WHERE table_name = 'daily_metrics' AND constraint_type = 'UNIQUE'
    """)
    constraints = [row[0] for row in cur.fetchall()]
    assert any("user_date" in c or "daily_metrics" in c for c in constraints), \
        "Unique constraint on (user_id, metric_date) not found"


def test_daily_metrics_table__unique_constraint_enforced(db_conn):
    """
    AC: Unique constraint is enforced — inserting duplicate (user_id, metric_date) fails.
    """
    cur = db_conn.cursor()
    alice_id = get_alice_id(db_conn)
    assert alice_id, "Alice not found in users table"

    # Clean up any leftover test data from this test
    test_date_base = (date.today() - timedelta(days=1000)).isoformat()
    # Offset by hash of test name to ensure uniqueness across runs
    test_offset = hash("unique_constraint_enforced") % 500
    test_date = (date.today() - timedelta(days=1000 + test_offset)).isoformat()

    # Clean up any existing row for this date
    cur.execute("DELETE FROM daily_metrics WHERE user_id = %s AND metric_date = %s",
                (str(alice_id), test_date))
    db_conn.commit()

    # Insert first row (should succeed)
    cur.execute("""
        INSERT INTO daily_metrics (user_id, metric_date, resting_hr, energy, mood)
        VALUES (%s, %s, %s, %s, %s)
    """, (str(alice_id), test_date, 55, 4, 4))
    db_conn.commit()

    # Try to insert duplicate (should fail)
    try:
        cur.execute("""
            INSERT INTO daily_metrics (user_id, metric_date, resting_hr, energy, mood)
            VALUES (%s, %s, %s, %s, %s)
        """, (str(alice_id), test_date, 56, 3, 3))
        db_conn.commit()
        pytest.fail("Should have raised IntegrityError for duplicate (user_id, metric_date)")
    except psycopg2.IntegrityError as e:
        db_conn.rollback()
        assert "unique" in str(e).lower() or "constraint" in str(e).lower(), \
            f"Expected unique constraint violation, got: {e}"


def test_daily_metrics_table__check_constraint_resting_hr(db_conn):
    """
    AC: CHECK constraint on resting_hr: 20–200 if present.
    """
    cur = db_conn.cursor()
    alice_id = get_alice_id(db_conn)
    assert alice_id, "Alice not found"

    today = date.today().isoformat()

    # Try to insert resting_hr below 20 (should fail)
    try:
        cur.execute("""
            INSERT INTO daily_metrics (user_id, metric_date, resting_hr)
            VALUES (%s, %s, %s)
        """, (str(alice_id), today, 10))
        db_conn.commit()
        pytest.fail("Should have raised IntegrityError for resting_hr < 20")
    except psycopg2.IntegrityError as e:
        db_conn.rollback()
        assert "check" in str(e).lower() or "constraint" in str(e).lower(), \
            f"Expected check constraint violation, got: {e}"


def test_daily_metrics_table__check_constraint_hrv(db_conn):
    """
    AC: CHECK constraint on hrv: 0–300 if present.
    """
    cur = db_conn.cursor()
    alice_id = get_alice_id(db_conn)
    assert alice_id, "Alice not found"

    today = date.today().isoformat()

    # Try to insert hrv > 300 (should fail)
    try:
        cur.execute("""
            INSERT INTO daily_metrics (user_id, metric_date, hrv)
            VALUES (%s, %s, %s)
        """, (str(alice_id), today, 350))
        db_conn.commit()
        pytest.fail("Should have raised IntegrityError for hrv > 300")
    except psycopg2.IntegrityError as e:
        db_conn.rollback()
        assert "check" in str(e).lower() or "constraint" in str(e).lower(), \
            f"Expected check constraint violation, got: {e}"


def test_daily_metrics_table__check_constraint_sleep_quality(db_conn):
    """
    AC: CHECK constraint on sleep_quality: 1–5 if present.
    """
    cur = db_conn.cursor()
    alice_id = get_alice_id(db_conn)
    assert alice_id, "Alice not found"

    today = date.today().isoformat()

    # Try to insert sleep_quality = 0 (should fail)
    try:
        cur.execute("""
            INSERT INTO daily_metrics (user_id, metric_date, sleep_quality)
            VALUES (%s, %s, %s)
        """, (str(alice_id), today, 0))
        db_conn.commit()
        pytest.fail("Should have raised IntegrityError for sleep_quality < 1")
    except psycopg2.IntegrityError as e:
        db_conn.rollback()
        assert "check" in str(e).lower() or "constraint" in str(e).lower(), \
            f"Expected check constraint violation, got: {e}"


def test_daily_metrics_table__check_constraint_energy(db_conn):
    """
    AC: CHECK constraint on energy: 1–5 if present.
    """
    cur = db_conn.cursor()
    alice_id = get_alice_id(db_conn)
    assert alice_id, "Alice not found"

    today = date.today().isoformat()

    # Try to insert energy = 6 (should fail)
    try:
        cur.execute("""
            INSERT INTO daily_metrics (user_id, metric_date, energy)
            VALUES (%s, %s, %s)
        """, (str(alice_id), today, 6))
        db_conn.commit()
        pytest.fail("Should have raised IntegrityError for energy > 5")
    except psycopg2.IntegrityError as e:
        db_conn.rollback()
        assert "check" in str(e).lower() or "constraint" in str(e).lower(), \
            f"Expected check constraint violation, got: {e}"


def test_daily_metrics_table__check_constraint_mood(db_conn):
    """
    AC: CHECK constraint on mood: 1–5 if present.
    """
    cur = db_conn.cursor()
    alice_id = get_alice_id(db_conn)
    assert alice_id, "Alice not found"

    today = date.today().isoformat()

    # Try to insert mood = 6 (should fail)
    try:
        cur.execute("""
            INSERT INTO daily_metrics (user_id, metric_date, mood)
            VALUES (%s, %s, %s)
        """, (str(alice_id), today, 6))
        db_conn.commit()
        pytest.fail("Should have raised IntegrityError for mood > 5")
    except psycopg2.IntegrityError as e:
        db_conn.rollback()
        assert "check" in str(e).lower() or "constraint" in str(e).lower(), \
            f"Expected check constraint violation, got: {e}"


def test_daily_metrics_table__index_on_user_date(db_conn):
    """
    AC: Index on (user_id, metric_date DESC) for time-series queries.
    """
    cur = db_conn.cursor()

    # Check for index
    cur.execute("""
        SELECT indexname
        FROM pg_indexes
        WHERE tablename = 'daily_metrics'
    """)
    indexes = [row[0] for row in cur.fetchall()]
    assert any("user_date" in idx or "metric_date" in idx for idx in indexes), \
        "Index on (user_id, metric_date) not found"


def test_daily_metrics_table__updated_at_trigger(db_conn):
    """
    AC: updated_at is automatically refreshed on UPDATE via trigger.
    """
    cur = db_conn.cursor()
    alice_id = get_alice_id(db_conn)
    assert alice_id, "Alice not found"

    # Use unique test date far in the past with offset for this test
    test_offset = hash("updated_at_trigger") % 500
    test_date = (date.today() - timedelta(days=1100 + test_offset)).isoformat()

    # Clean up any existing row for this date
    cur.execute("DELETE FROM daily_metrics WHERE user_id = %s AND metric_date = %s",
                (str(alice_id), test_date))
    db_conn.commit()

    # Insert a row
    cur.execute("""
        INSERT INTO daily_metrics (user_id, metric_date, energy, notes)
        VALUES (%s, %s, %s, %s)
        RETURNING id, updated_at
    """, (str(alice_id), test_date, 4, "initial"))
    row_id, updated_at_before = cur.fetchone()
    db_conn.commit()

    # Sleep a moment to ensure time has passed
    import time
    time.sleep(0.5)

    # Update the notes
    cur.execute("""
        UPDATE daily_metrics SET notes = %s WHERE id = %s
        RETURNING updated_at
    """, ("updated", str(row_id)))
    updated_at_after = cur.fetchone()[0]
    db_conn.commit()

    # Verify updated_at changed
    assert updated_at_after > updated_at_before, \
        "updated_at should have been refreshed on UPDATE via trigger"


def test_daily_metrics_table__foreign_key_cascade(db_conn):
    """
    AC: Foreign key on user_id with ON DELETE CASCADE — deleting a user removes their daily_metrics.
    """
    cur = db_conn.cursor()

    # Create a test user
    test_user_id = str(uuid.uuid4())
    cur.execute("INSERT INTO users (id, name) VALUES (%s, %s)", (test_user_id, "TestUser"))
    db_conn.commit()

    # Insert a daily_metrics row for the test user
    today = date.today().isoformat()
    cur.execute("""
        INSERT INTO daily_metrics (user_id, metric_date, energy)
        VALUES (%s, %s, %s)
    """, (test_user_id, today, 3))
    db_conn.commit()

    # Verify row exists
    cur.execute("SELECT COUNT(*) FROM daily_metrics WHERE user_id = %s", (test_user_id,))
    count_before = cur.fetchone()[0]
    assert count_before == 1, "daily_metrics row should have been inserted"

    # Delete the user
    cur.execute("DELETE FROM users WHERE id = %s", (test_user_id,))
    db_conn.commit()

    # Verify daily_metrics row was cascade-deleted
    cur.execute("SELECT COUNT(*) FROM daily_metrics WHERE user_id = %s", (test_user_id,))
    count_after = cur.fetchone()[0]
    assert count_after == 0, "daily_metrics row should have been cascade-deleted"


def test_daily_metrics_table__migration_reversible(db_conn):
    """
    AC: Migration is reversible cleanly (downgrade removes table without error).
    Verified by checking that the downgrade command can run without raising.
    """
    pytest.skip("manual — requires running alembic downgrade -1 from the command line")


def test_daily_metrics_table__alice_seed_data_exists(db_conn):
    """
    AC: Seed script adds 14 days of sample daily_metrics for Alice,
    with realistic varying values.
    """
    cur = db_conn.cursor()
    alice_id = get_alice_id(db_conn)
    assert alice_id, "Alice not found in users table"

    # Check that Alice has at least 14 daily_metrics rows (from seed; may have more from other tests)
    cur.execute("""
        SELECT COUNT(*) FROM daily_metrics WHERE user_id = %s
    """, (str(alice_id),))
    count = cur.fetchone()[0]
    assert count >= 14, f"Expected at least 14 daily_metrics rows for Alice, got {count}"


def test_daily_metrics_table__alice_seed_data_non_null_fields(db_conn):
    """
    AC: Alice seed data has realistic varying values — each row has at least some non-null fields.
    """
    cur = db_conn.cursor()
    alice_id = get_alice_id(db_conn)
    assert alice_id, "Alice not found"

    # Fetch all seed rows
    cur.execute("""
        SELECT id, resting_hr, hrv, sleep_hours, sleep_quality, energy, mood, notes
        FROM daily_metrics WHERE user_id = %s ORDER BY metric_date
    """, (str(alice_id),))
    rows = cur.fetchall()
    assert len(rows) >= 1, "No seed data found for Alice"

    # Verify each row has at least some non-null fields
    for row in rows:
        non_null_count = sum(1 for field in row[1:] if field is not None)
        assert non_null_count > 0, f"Row {row[0]} has all NULL fields"


def test_daily_metrics_table__alice_seed_data_ranges(db_conn):
    """
    AC: Seed data has realistic values (rhr 50–60, hrv 40–80, sleep 6.5–8.5, quality/energy/mood 2–5).
    """
    cur = db_conn.cursor()
    alice_id = get_alice_id(db_conn)
    assert alice_id, "Alice not found"

    # Fetch all seed rows
    cur.execute("""
        SELECT resting_hr, hrv, sleep_hours, sleep_quality, energy, mood
        FROM daily_metrics WHERE user_id = %s
    """, (str(alice_id),))
    rows = cur.fetchall()
    assert len(rows) >= 1, "No seed data found for Alice"

    # Check ranges for non-null values
    for resting_hr, hrv, sleep_hours, sleep_quality, energy, mood in rows:
        if resting_hr is not None:
            assert 50 <= resting_hr <= 60, f"resting_hr {resting_hr} outside expected range 50–60"
        if hrv is not None:
            assert 40 <= hrv <= 80, f"hrv {hrv} outside expected range 40–80"
        if sleep_hours is not None:
            assert 6.5 <= float(sleep_hours) <= 8.5, f"sleep_hours {sleep_hours} outside expected range 6.5–8.5"
        if sleep_quality is not None:
            assert 2 <= sleep_quality <= 5, f"sleep_quality {sleep_quality} outside expected range 2–5"
        if energy is not None:
            assert 2 <= energy <= 5, f"energy {energy} outside expected range 2–5"
        if mood is not None:
            assert 2 <= mood <= 5, f"mood {mood} outside expected range 2–5"


def test_daily_metrics_table__schema_documented(db_conn):
    """
    AC: Schema is documented.
    """
    pytest.skip("manual — schema documentation verification requires reviewing code comments and migration file")
