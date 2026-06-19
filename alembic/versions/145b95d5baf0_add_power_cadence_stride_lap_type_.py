"""Add power, cadence, stride, and lap-type columns via idempotent migration.

Adds workout-level and split-level Stryd/run metrics that the per-run metrics
feature and run-view UI require.

workouts: avg_power (int), max_power (int), np (int), avg_cadence_spm (int),
          avg_stride_m (numeric 4,2) — all nullable.

workout_splits: avg_power (int, nullable), cadence_spm (int, nullable),
               stride_length_m (numeric 4,2, nullable),
               lap_type (text, NOT NULL, default 'auto',
                         CHECK IN ('auto', 'manual')).

Idempotent: column_exists guards skip ADD COLUMN on DBs where prior
feature migrations already created the columns; the lap_type NOT NULL
and check-constraint steps are also guarded.

Revision ID: 145b95d5baf0
Revises: 6b72b2735b17
Create Date: 2026-06-19
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

from helpers import column_exists

revision: str = "145b95d5baf0"
down_revision: Union[str, None] = "046b014b2eab"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CK_LAP_TYPE = "ck_workout_splits_lap_type_values"


def _constraint_exists(table: str, name: str) -> bool:
    bind = op.get_bind()
    result = bind.execute(
        text(
            "SELECT 1 FROM information_schema.table_constraints "
            "WHERE table_name = :table AND constraint_name = :name"
        ),
        {"table": table, "name": name},
    )
    return result.fetchone() is not None


def _column_is_nullable(table: str, column: str) -> bool:
    bind = op.get_bind()
    result = bind.execute(
        text(
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_name = :table AND column_name = :col"
        ),
        {"table": table, "col": column},
    )
    row = result.fetchone()
    return row is not None and row[0] == "YES"


def upgrade() -> None:
    # --- workouts ---
    for col_name, col_type in [
        ("avg_power", sa.Integer),
        ("max_power", sa.Integer),
        ("np", sa.Integer),
        ("avg_cadence_spm", sa.Integer),
    ]:
        if not column_exists("workouts", col_name):
            op.add_column("workouts", sa.Column(col_name, col_type, nullable=True))

    if not column_exists("workouts", "avg_stride_m"):
        op.add_column(
            "workouts",
            sa.Column("avg_stride_m", sa.Numeric(4, 2), nullable=True),
        )

    # --- workout_splits (nullable) ---
    for col_name, col_type in [
        ("avg_power", sa.Integer),
        ("cadence_spm", sa.Integer),
    ]:
        if not column_exists("workout_splits", col_name):
            op.add_column(
                "workout_splits", sa.Column(col_name, col_type, nullable=True)
            )

    if not column_exists("workout_splits", "stride_length_m"):
        op.add_column(
            "workout_splits",
            sa.Column("stride_length_m", sa.Numeric(4, 2), nullable=True),
        )

    # --- lap_type: NOT NULL, default 'auto', check constraint ---
    if not column_exists("workout_splits", "lap_type"):
        op.add_column(
            "workout_splits",
            sa.Column(
                "lap_type",
                sa.String(10),
                nullable=False,
                server_default=text("'auto'"),
            ),
        )
    else:
        # Column exists from a prior migration (nullable); backfill then tighten.
        op.execute(
            text(
                "UPDATE workout_splits SET lap_type = 'auto' WHERE lap_type IS NULL"
            )
        )
        if _column_is_nullable("workout_splits", "lap_type"):
            op.alter_column(
                "workout_splits",
                "lap_type",
                existing_type=sa.String(10),
                nullable=False,
                server_default=text("'auto'"),
            )

    if not _constraint_exists("workout_splits", _CK_LAP_TYPE):
        op.create_check_constraint(
            _CK_LAP_TYPE,
            "workout_splits",
            "lap_type IN ('auto', 'manual')",
        )


def downgrade() -> None:
    if _constraint_exists("workout_splits", _CK_LAP_TYPE):
        op.drop_constraint(_CK_LAP_TYPE, "workout_splits", type_="check")

    # Revert lap_type to nullable (only if we tightened it; always safe to relax).
    if column_exists("workout_splits", "lap_type") and not _column_is_nullable(
        "workout_splits", "lap_type"
    ):
        op.alter_column(
            "workout_splits",
            "lap_type",
            existing_type=sa.String(10),
            nullable=True,
        )
    else:
        if column_exists("workout_splits", "lap_type"):
            op.drop_column("workout_splits", "lap_type")

    for col in ("stride_length_m", "cadence_spm", "avg_power"):
        if column_exists("workout_splits", col):
            op.drop_column("workout_splits", col)

    for col in ("avg_stride_m", "avg_cadence_spm", "np", "max_power", "avg_power"):
        if column_exists("workouts", col):
            op.drop_column("workouts", col)
