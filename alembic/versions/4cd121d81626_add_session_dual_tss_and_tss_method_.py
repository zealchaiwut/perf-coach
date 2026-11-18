"""add session dual tss and tss_method_default

Revision ID: 4cd121d81626
Revises: ee582be657e7
Create Date: 2026-11-18 23:22:44.122300

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from helpers import column_exists

# revision identifiers, used by Alembic.
revision: str = "4cd121d81626"
down_revision: Union[str, Sequence[str], None] = "ee582be657e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not column_exists("workouts", "tss_power"):
        op.add_column("workouts", sa.Column("tss_power", sa.Float(), nullable=True))
    if not column_exists("workouts", "tss_stryd"):
        op.add_column("workouts", sa.Column("tss_stryd", sa.Float(), nullable=True))
    if not column_exists("workouts", "tss_method_override"):
        op.add_column(
            "workouts",
            sa.Column("tss_method_override", sa.String(20), nullable=True),
        )
    if not column_exists("user_preferences", "tss_method_default"):
        op.add_column(
            "user_preferences",
            sa.Column(
                "tss_method_default",
                sa.String(20),
                nullable=False,
                server_default="power",
            ),
        )

    bind = op.get_bind()
    # Power-method storage mirrors today's counted value for runs (default=power).
    bind.execute(
        sa.text(
            """
            UPDATE workouts
            SET tss_power = tss
            WHERE tss IS NOT NULL
              AND workout_type ILIKE 'run%'
            """
        )
    )
    bind.execute(
        sa.text(
            """
            UPDATE workouts w
            SET tss_stryd = sa.tss
            FROM stryd_activities sa
            WHERE w.stryd_activity_pk = sa.id
              AND sa.tss IS NOT NULL
            """
        )
    )


def downgrade() -> None:
    if column_exists("user_preferences", "tss_method_default"):
        op.drop_column("user_preferences", "tss_method_default")
    if column_exists("workouts", "tss_method_override"):
        op.drop_column("workouts", "tss_method_override")
    if column_exists("workouts", "tss_stryd"):
        op.drop_column("workouts", "tss_stryd")
    if column_exists("workouts", "tss_power"):
        op.drop_column("workouts", "tss_power")