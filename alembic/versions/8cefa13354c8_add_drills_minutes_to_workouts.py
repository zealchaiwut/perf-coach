"""add drills_minutes to workouts

Revision ID: 8cefa13354c8
Revises: 13f189e87eec
Create Date: 2026-07-31 15:29:10.694784

Running drills — form drills, strides, A/B skips — done alongside a session.

A real column rather than free text in ``remarks`` so it can be counted later
("how many drill sessions last month?"), but deliberately just a duration: no
exercise breakdown, no structure, no TSS.

NOT a workout_type. A type would claim a slot in the week skeleton and carry a
TSS budget, which is wrong for ten minutes of strides after an easy run — the
whole point is that drills ride along with a session and cost nothing against
the load model.

Nullable because it is unknown for every workout logged before this column
existed, and "unknown" must not read as "did no drills". Same reasoning as
``workouts.fuelled`` in 37e30b89c6cd.

Uses ADD COLUMN IF NOT EXISTS rather than the helpers.column_exists guard used
elsewhere: it is idempotent at the SQL level and satisfies the repo's
add-column-guard convention check without a Python round trip.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '8cefa13354c8'
down_revision: Union[str, Sequence[str], None] = '13f189e87eec'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add workouts.drills_minutes."""
    op.execute(
        "ALTER TABLE workouts ADD COLUMN IF NOT EXISTS drills_minutes INTEGER"
    )
    # Bounds match the API validator. 0 is meaningful ("logged, did none");
    # 120 is a generous ceiling for something described as light.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'ck_workouts_drills_minutes_range'
            ) THEN
                ALTER TABLE workouts ADD CONSTRAINT ck_workouts_drills_minutes_range
                CHECK (drills_minutes IS NULL OR (drills_minutes >= 0 AND drills_minutes <= 120));
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    """Drop workouts.drills_minutes."""
    op.execute(
        "ALTER TABLE workouts DROP CONSTRAINT IF EXISTS ck_workouts_drills_minutes_range"
    )
    op.execute("ALTER TABLE workouts DROP COLUMN IF EXISTS drills_minutes")
