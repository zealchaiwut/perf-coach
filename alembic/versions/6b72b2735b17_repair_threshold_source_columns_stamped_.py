"""repair threshold source columns (stamped-ahead drift)

Repairs UAT/PRD databases where alembic_version was stamped past
aa1b2c3d4e5f_add_threshold_source_columns without that migration's DDL ever
running — a side effect of the old duplicate-revision-id collision on
aa1b2c3d4e5f (threshold_source vs height_cm). On those DBs the three
user_preferences.*_source columns are declared in models.py but missing from
the schema, which trips the deploy-start schema-drift guard.

This migration re-asserts the three columns idempotently, so:
- stamped-ahead DBs (UAT/PRD) get the missing columns on `alembic upgrade head`
- fresh DBs (which already created them via aa1b2c3d4e5f) no-op via the guards

Revision ID: 6b72b2735b17
Revises: mm3a4b5c6d7e
Create Date: 2026-06-19 11:11:52.272675

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from helpers import column_exists

# revision identifiers, used by Alembic.
revision: str = "6b72b2735b17"
down_revision: Union[str, Sequence[str], None] = "mm3a4b5c6d7e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLUMNS = (
    "ftp_w_source",
    "threshold_hr_source",
    "threshold_pace_seconds_per_km_source",
)


def upgrade() -> None:
    for name in _COLUMNS:
        if not column_exists("user_preferences", name):
            op.add_column(
                "user_preferences",
                sa.Column(name, sa.String(30), nullable=True),
            )


def downgrade() -> None:
    # No-op: these columns are owned by aa1b2c3d4e5f. This revision only
    # backfills them where the stamp ran ahead of the DDL, so it must not drop
    # them on downgrade (that would diverge from models.py).
    pass
