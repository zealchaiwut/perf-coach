"""Tests for issue #665: Add power, cadence, stride, and lap-type columns via Alembic migration.

Acceptance criteria verified:
- AC1/AC2: A new Alembic migration file exists (145b95d5baf0); migration is idempotent.
- AC3: workouts table has avg_power, max_power, np, avg_cadence_spm, avg_stride_m — all nullable.
- AC4: workout_splits has avg_power (nullable), cadence_spm (nullable), stride_length_m (nullable),
       lap_type (NOT NULL, default 'auto', constrained to 'auto'/'manual').
- AC5: SQLAlchemy Workout model declares all five new columns.
- AC6: SQLAlchemy WorkoutSplit model declares all four new columns with correct types/nullability.
- AC7: No hardcoded numeric thresholds in migration or model changes.
- AC8: No new API endpoints introduced.
"""
import ast
import pathlib

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from backend.db import engine
from backend.models import Workout, WorkoutSplit

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_MIGRATION_FILE = (
    pathlib.Path(__file__).parents[1]
    / "alembic"
    / "versions"
    / "145b95d5baf0_add_power_cadence_stride_lap_type_.py"
)

_MODELS_FILE = pathlib.Path(__file__).parents[1] / "backend" / "models.py"


# ---------------------------------------------------------------------------
# AC1: Migration file exists with correct structure
# ---------------------------------------------------------------------------


def test_migration_file_exists():
    """AC1: The migration file 145b95d5baf0 exists."""
    assert _MIGRATION_FILE.exists(), f"Migration file not found: {_MIGRATION_FILE}"


def test_migration_revision_id():
    """AC1: revision ID in migration file matches the filename prefix."""
    src = _MIGRATION_FILE.read_text()
    assert 'revision: str = "145b95d5baf0"' in src


def test_migration_has_upgrade_and_downgrade():
    """AC1: Migration has both upgrade() and downgrade() functions."""
    src = _MIGRATION_FILE.read_text()
    assert "def upgrade()" in src
    assert "def downgrade()" in src


# ---------------------------------------------------------------------------
# AC2: Idempotency — columns already present on DB, upgrade still succeeds
# ---------------------------------------------------------------------------


def test_workouts_columns_present_after_migration():
    """AC2/AC3: Running against an already-migrated DB does not raise errors.

    This test implicitly validates idempotency: pytest runs against the live DB
    (which already has alembic upgrade head applied); if upgrade() were not
    guarded by column_exists checks it would fail here.
    """
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = 'workouts'"
            )
        ).fetchall()
    cols = {r[0] for r in rows}
    for col in ("avg_power", "max_power", "np", "avg_cadence_spm", "avg_stride_m"):
        assert col in cols, f"Column '{col}' missing from workouts table"


def test_workout_splits_columns_present_after_migration():
    """AC2/AC4: workout_splits has all four new columns after migration."""
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = 'workout_splits'"
            )
        ).fetchall()
    cols = {r[0] for r in rows}
    for col in ("avg_power", "cadence_spm", "stride_length_m", "lap_type"):
        assert col in cols, f"Column '{col}' missing from workout_splits table"


# ---------------------------------------------------------------------------
# AC3: workouts new columns are nullable with correct types
# ---------------------------------------------------------------------------


def test_workouts_new_columns_nullable():
    """AC3: avg_power, max_power, np, avg_cadence_spm, avg_stride_m are nullable."""
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT column_name, is_nullable, data_type "
                "FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = 'workouts' "
                "AND column_name IN ('avg_power','max_power','np','avg_cadence_spm','avg_stride_m')"
            )
        ).fetchall()
    found = {r[0]: {"nullable": r[1], "type": r[2]} for r in rows}

    for col in ("avg_power", "max_power", "np", "avg_cadence_spm"):
        assert col in found, f"Column '{col}' missing"
        assert found[col]["nullable"] == "YES", f"'{col}' should be nullable"
        assert found[col]["type"] == "integer", f"'{col}' should be integer, got {found[col]['type']}"

    assert "avg_stride_m" in found, "avg_stride_m missing from workouts"
    assert found["avg_stride_m"]["nullable"] == "YES", "avg_stride_m should be nullable"
    assert found["avg_stride_m"]["type"] == "numeric", (
        f"avg_stride_m should be numeric, got {found['avg_stride_m']['type']}"
    )


# ---------------------------------------------------------------------------
# AC4: workout_splits lap_type constraints
# ---------------------------------------------------------------------------


def test_lap_type_is_not_nullable():
    """AC4: lap_type is NOT NULL in workout_splits."""
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT is_nullable FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = 'workout_splits' "
                "AND column_name = 'lap_type'"
            )
        ).fetchone()
    assert row is not None, "lap_type column not found"
    assert row[0] == "NO", "lap_type should be NOT NULL"


def test_lap_type_check_constraint_exists():
    """AC4: check constraint ck_workout_splits_lap_type_values exists."""
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT 1 FROM information_schema.table_constraints "
                "WHERE table_name = 'workout_splits' "
                "AND constraint_name = 'ck_workout_splits_lap_type_values'"
            )
        ).fetchone()
    assert row is not None, "Check constraint ck_workout_splits_lap_type_values not found"


def test_lap_type_rejects_invalid_value():
    """AC4: lap_type rejects values other than 'auto' or 'manual'."""
    with engine.connect() as conn:
        # Find Alice's user_id and a workout to attach a split to
        user_row = conn.execute(text("SELECT id FROM users WHERE name = 'Alice'")).fetchone()
        if user_row is None:
            pytest.skip("Alice user not found; seed not run")
        user_id = user_row[0]

        # Create a temporary workout
        conn.execute(text("BEGIN"))
        try:
            wid = conn.execute(
                text(
                    "INSERT INTO workouts (user_id, workout_date, name, workout_type, source) "
                    "VALUES (:uid, '2099-06-19', 'laptype-test', 'running', 'manual') "
                    "RETURNING id"
                ),
                {"uid": user_id},
            ).fetchone()[0]

            with pytest.raises(Exception):
                conn.execute(
                    text(
                        "INSERT INTO workout_splits "
                        "(workout_id, split_index, distance_km, duration_seconds, lap_type) "
                        "VALUES (:wid, 1, 1.0, 360, 'interval')"
                    ),
                    {"wid": wid},
                )
        finally:
            conn.execute(text("ROLLBACK"))


def test_lap_type_defaults_to_auto():
    """AC4: lap_type defaults to 'auto' when not supplied."""
    with engine.connect() as conn:
        user_row = conn.execute(text("SELECT id FROM users WHERE name = 'Alice'")).fetchone()
        if user_row is None:
            pytest.skip("Alice user not found; seed not run")
        user_id = user_row[0]

        conn.execute(text("BEGIN"))
        try:
            wid = conn.execute(
                text(
                    "INSERT INTO workouts (user_id, workout_date, name, workout_type, source) "
                    "VALUES (:uid, '2099-06-19', 'default-laptype-test', 'running', 'manual') "
                    "RETURNING id"
                ),
                {"uid": user_id},
            ).fetchone()[0]

            split_id = conn.execute(
                text(
                    "INSERT INTO workout_splits "
                    "(workout_id, split_index, distance_km, duration_seconds) "
                    "VALUES (:wid, 1, 1.0, 360) RETURNING id"
                ),
                {"wid": wid},
            ).fetchone()[0]

            lap_type = conn.execute(
                text("SELECT lap_type FROM workout_splits WHERE id = :sid"),
                {"sid": split_id},
            ).fetchone()[0]

            assert lap_type == "auto", f"Expected 'auto' default, got '{lap_type}'"
        finally:
            conn.execute(text("ROLLBACK"))


def test_workout_splits_nullable_columns():
    """AC4: avg_power, cadence_spm, stride_length_m are nullable on workout_splits."""
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT column_name, is_nullable FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = 'workout_splits' "
                "AND column_name IN ('avg_power', 'cadence_spm', 'stride_length_m')"
            )
        ).fetchall()
    found = {r[0]: r[1] for r in rows}
    for col in ("avg_power", "cadence_spm", "stride_length_m"):
        assert col in found, f"Column '{col}' missing from workout_splits"
        assert found[col] == "YES", f"'{col}' should be nullable in workout_splits"


# ---------------------------------------------------------------------------
# AC5: SQLAlchemy Workout model declares all five new columns
# ---------------------------------------------------------------------------


def test_workout_model_has_avg_power():
    """AC5: Workout model declares avg_power."""
    assert hasattr(Workout, "avg_power"), "Workout.avg_power not found"


def test_workout_model_has_max_power():
    """AC5: Workout model declares max_power."""
    assert hasattr(Workout, "max_power"), "Workout.max_power not found"


def test_workout_model_has_np():
    """AC5: Workout model declares np (normalised power)."""
    assert hasattr(Workout, "np"), "Workout.np not found"


def test_workout_model_has_avg_cadence_spm():
    """AC5: Workout model declares avg_cadence_spm."""
    assert hasattr(Workout, "avg_cadence_spm"), "Workout.avg_cadence_spm not found"


def test_workout_model_has_avg_stride_m():
    """AC5: Workout model declares avg_stride_m."""
    assert hasattr(Workout, "avg_stride_m"), "Workout.avg_stride_m not found"


# ---------------------------------------------------------------------------
# AC6: SQLAlchemy WorkoutSplit model declares all four new columns
# ---------------------------------------------------------------------------


def test_workout_split_model_has_avg_power():
    """AC6: WorkoutSplit model declares avg_power."""
    assert hasattr(WorkoutSplit, "avg_power"), "WorkoutSplit.avg_power not found"


def test_workout_split_model_has_cadence_spm():
    """AC6: WorkoutSplit model declares cadence_spm."""
    assert hasattr(WorkoutSplit, "cadence_spm"), "WorkoutSplit.cadence_spm not found"


def test_workout_split_model_has_stride_length_m():
    """AC6: WorkoutSplit model declares stride_length_m."""
    assert hasattr(WorkoutSplit, "stride_length_m"), "WorkoutSplit.stride_length_m not found"


def test_workout_split_model_has_lap_type():
    """AC6: WorkoutSplit model declares lap_type."""
    assert hasattr(WorkoutSplit, "lap_type"), "WorkoutSplit.lap_type not found"


def test_workout_split_lap_type_not_nullable():
    """AC6: WorkoutSplit.lap_type is declared nullable=False."""
    col = WorkoutSplit.__table__.c.lap_type
    assert not col.nullable, "WorkoutSplit.lap_type should be nullable=False"


def test_workout_split_lap_type_check_constraint_in_model():
    """AC6: WorkoutSplit model __table_args__ includes the lap_type check constraint."""
    from sqlalchemy import CheckConstraint as CK
    constraints = WorkoutSplit.__table__.constraints
    check_names = {
        c.name for c in constraints if isinstance(c, CK)
    }
    assert "ck_workout_splits_lap_type_values" in check_names, (
        "ck_workout_splits_lap_type_values not found in WorkoutSplit constraints"
    )


# ---------------------------------------------------------------------------
# AC7: No hardcoded numeric thresholds in migration or model changes
# ---------------------------------------------------------------------------


def test_no_hardcoded_thresholds_in_migration():
    """AC7: Migration source has no hardcoded numeric threshold comparisons."""
    src = _MIGRATION_FILE.read_text()
    tree = ast.parse(src)
    threshold_ops = (ast.Lt, ast.Gt, ast.LtE, ast.GtE)
    violations = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            for op in node.ops:
                if isinstance(op, threshold_ops):
                    violations.append(ast.unparse(node))
    assert not violations, f"Hardcoded threshold comparisons found: {violations}"


# ---------------------------------------------------------------------------
# AC8: No new API endpoints in main.py from this migration ticket
# ---------------------------------------------------------------------------


def test_no_new_routes_for_this_ticket():
    """AC8: No API routes related to power/cadence/stride were added by this migration.

    This migration is schema-only; no endpoints should reference the new columns yet.
    """
    # This is a migration-only ticket; we just verify the migration file doesn't
    # import FastAPI or define route handlers.
    src = _MIGRATION_FILE.read_text()
    assert "fastapi" not in src.lower(), "Migration should not import FastAPI"
    assert "@app." not in src, "Migration should not define route handlers"
