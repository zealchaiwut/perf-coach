"""create mobility_tests

Revision ID: 25e2032a3208
Revises: b12573ca9afa
Create Date: 2026-11-21 22:58:51.985209

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from helpers import index_exists, table_exists


# revision identifiers, used by Alembic.
revision: str = '25e2032a3208'
down_revision: Union[str, Sequence[str], None] = 'b12573ca9afa'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Monthly mobility self-test table (P4-5)."""
    if not table_exists("mobility_tests"):
        op.create_table(
            "mobility_tests",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("user_id", postgresql.UUID(as_uuid=True),
                      sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("test_date", sa.Date(), nullable=False),
            sa.Column("knee_to_wall_left_cm", sa.Numeric(4, 1), nullable=False),
            sa.Column("knee_to_wall_right_cm", sa.Numeric(4, 1), nullable=False),
            sa.Column("sit_and_reach_cm", sa.Numeric(4, 1), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True),
                      server_default=sa.text("now()"), nullable=False),
            sa.CheckConstraint(
                "knee_to_wall_left_cm >= 0 AND knee_to_wall_left_cm <= 30 "
                "AND knee_to_wall_right_cm >= 0 AND knee_to_wall_right_cm <= 30",
                name="ck_mobility_tests_knee_to_wall_range",
            ),
            sa.CheckConstraint(
                "sit_and_reach_cm >= -20 AND sit_and_reach_cm <= 40",
                name="ck_mobility_tests_sit_and_reach_range",
            ),
        )
    if not index_exists("mobility_tests", "ix_mobility_tests_user_date"):
        op.create_index("ix_mobility_tests_user_date", "mobility_tests", ["user_id", "test_date"])


def downgrade() -> None:
    if not table_exists("mobility_tests"):
        return
    if index_exists("mobility_tests", "ix_mobility_tests_user_date"):
        op.drop_index("ix_mobility_tests_user_date", table_name="mobility_tests")
    op.drop_table("mobility_tests")
