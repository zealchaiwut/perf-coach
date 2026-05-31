"""Add CHECK constraint on rpe_1_to_10 in workout_feel to enforce range 1-10 at the database level.

Revision ID: j3d4e5f6a7b8
Revises: i2c3d4e5f6a7
Create Date: 2026-05-31

"""
from alembic import op
from sqlalchemy import text

revision = "j3d4e5f6a7b8"
down_revision = "i2c3d4e5f6a7"
branch_labels = None
depends_on = None

_CONSTRAINT = "ck_workout_feel_rpe_range"
_TABLE = "workout_feel"


def _constraint_exists() -> bool:
    bind = op.get_bind()
    result = bind.execute(
        text(
            "SELECT 1 FROM information_schema.table_constraints "
            "WHERE table_name = :table AND constraint_name = :name"
        ),
        {"table": _TABLE, "name": _CONSTRAINT},
    )
    return result.fetchone() is not None


def upgrade():
    if _constraint_exists():
        return
    op.create_check_constraint(
        _CONSTRAINT,
        _TABLE,
        "rpe_1_to_10 >= 1 AND rpe_1_to_10 <= 10",
    )


def downgrade():
    if not _constraint_exists():
        return
    op.drop_constraint(_CONSTRAINT, _TABLE, type_="check")
