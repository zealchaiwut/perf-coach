"""add removed_activities tombstone table

Tracks Strava/Stryd activities that the user manually removed from their log so
the background reconcile does NOT recreate the workout on the next sync. Keyed by
the external activity id (durable across re-pulls). Holds a name/date snapshot so
the "Removed" list can be shown without the (now-deleted) workout row, and so the
user can restore it (which clears the tombstone and lets reconcile rebuild it).

Revision ID: 932ba10c0d09
Revises: 6c67cf68fb1e
Create Date: 2026-06-21

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from helpers import table_exists, index_exists


# revision identifiers, used by Alembic.
revision: str = '932ba10c0d09'
down_revision: Union[str, Sequence[str], None] = '6c67cf68fb1e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if table_exists("removed_activities"):
        return

    op.create_table(
        "removed_activities",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE", name="fk_removed_activities_user_id"),
            nullable=False,
        ),
        # 'strava' | 'stryd'
        sa.Column("source", sa.String(10), nullable=False),
        # External activity id as text (strava bigint or stryd string).
        sa.Column("external_id", sa.String(255), nullable=False),
        # Snapshot for the Removed-list display (workout row is hard-deleted).
        sa.Column("workout_name", sa.String(255), nullable=True),
        sa.Column("workout_date", sa.Date(), nullable=True),
        sa.Column(
            "removed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "user_id", "source", "external_id",
            name="uq_removed_activities_user_source_external",
        ),
    )

    if not index_exists("removed_activities", "ix_removed_activities_user"):
        op.execute(
            sa.text(
                "CREATE INDEX ix_removed_activities_user "
                "ON removed_activities (user_id)"
            )
        )


def downgrade() -> None:
    op.drop_table("removed_activities")
