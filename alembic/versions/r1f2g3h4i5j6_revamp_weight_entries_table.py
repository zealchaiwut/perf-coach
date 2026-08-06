"""Weight tracking: individual weigh-in records, separate from daily_metrics. \
Multiple entries per day allowed if entry_time differs. \
Older weight data in daily_metrics.weight_kg should be migrated in a future \
ticket — not this one (data exists, don't break it).

Revision ID: r1f2g3h4i5j6
Revises: q0e1f2a3b4c5
Create Date: 2026-06-08

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy import inspect

from helpers import table_exists, column_exists, index_exists, fk_exists

revision = "r1f2g3h4i5j6"
down_revision = "q0e1f2a3b4c5"
branch_labels = None
depends_on = None


def _unique_constraint_exists(table: str, name: str) -> bool:
    bind = op.get_bind()
    result = bind.execute(sa.text(
        "SELECT COUNT(*) FROM information_schema.table_constraints "
        "WHERE table_schema = 'public' AND table_name = :t "
        "AND constraint_name = :n AND constraint_type = 'UNIQUE'"
    ), {"t": table, "n": name}).scalar()
    return result > 0


def _check_constraint_exists(table: str, name: str) -> bool:
    bind = op.get_bind()
    result = bind.execute(sa.text(
        "SELECT COUNT(*) FROM information_schema.table_constraints "
        "WHERE table_schema = 'public' AND table_name = :t "
        "AND constraint_name = :n AND constraint_type = 'CHECK'"
    ), {"t": table, "n": name}).scalar()
    return result > 0


def upgrade():
    if not table_exists("weight_entries"):
        op.create_table(
            "weight_entries",
            sa.Column(
                "id",
                UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column(
                "user_id",
                UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="CASCADE", name="fk_weight_entries_user_id"),
                nullable=False,
            ),
            sa.Column("entry_date", sa.Date(), nullable=False),
            sa.Column("entry_time", sa.Time(), nullable=True),
            sa.Column("weight_kg", sa.Numeric(5, 2), nullable=False),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column(
                "source",
                sa.String(20),
                nullable=False,
                server_default=sa.text("'manual'"),
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=True,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=True,
            ),
            sa.CheckConstraint(
                "source IN ('manual', 'imported', 'backfill')",
                name="ck_weight_entries_source_values",
            ),
        )
        op.execute(sa.text(
            "ALTER TABLE weight_entries ADD CONSTRAINT uq_weight_entries_user_date_time "
            "UNIQUE NULLS NOT DISTINCT (user_id, entry_date, entry_time)"
        ))
        if not index_exists("weight_entries", "ix_weight_entries_user_entry_date"):
            op.create_index(
                "ix_weight_entries_user_entry_date",
                "weight_entries",
                ["user_id", "entry_date"],
            )
        return

    # ── Rename recorded_date → entry_date ────────────────────────────────────
    if column_exists("weight_entries", "recorded_date") and not column_exists("weight_entries", "entry_date"):
        op.alter_column("weight_entries", "recorded_date", new_column_name="entry_date")

    # ── Add missing columns ───────────────────────────────────────────────────
    if not column_exists("weight_entries", "entry_time"):
        op.add_column("weight_entries", sa.Column("entry_time", sa.Time(), nullable=True))

    if not column_exists("weight_entries", "notes"):
        op.add_column("weight_entries", sa.Column("notes", sa.Text(), nullable=True))

    if not column_exists("weight_entries", "source"):
        op.add_column(
            "weight_entries",
            sa.Column(
                "source",
                sa.String(20),
                nullable=False,
                server_default=sa.text("'manual'"),
            ),
        )

    if not column_exists("weight_entries", "updated_at"):
        op.add_column(
            "weight_entries",
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=True,
            ),
        )

    # ── Upgrade FK to have ON DELETE CASCADE ─────────────────────────────────
    if not fk_exists("weight_entries", "fk_weight_entries_user_id"):
        # Drop the auto-named FK created by the initial migration (no CASCADE)
        if fk_exists("weight_entries", "weight_entries_user_id_fkey"):
            op.drop_constraint(
                "weight_entries_user_id_fkey", "weight_entries", type_="foreignkey"
            )
        op.create_foreign_key(
            "fk_weight_entries_user_id",
            "weight_entries",
            "users",
            ["user_id"],
            ["id"],
            ondelete="CASCADE",
        )

    # ── Replace old unique constraint with NULLS NOT DISTINCT variant ─────────
    if _unique_constraint_exists("weight_entries", "uq_weight_entries_user_date"):
        op.drop_constraint("uq_weight_entries_user_date", "weight_entries", type_="unique")

    if not _unique_constraint_exists("weight_entries", "uq_weight_entries_user_date_time"):
        op.execute(sa.text(
            "ALTER TABLE weight_entries ADD CONSTRAINT uq_weight_entries_user_date_time "
            "UNIQUE NULLS NOT DISTINCT (user_id, entry_date, entry_time)"
        ))

    # ── Add index ─────────────────────────────────────────────────────────────
    if not index_exists("weight_entries", "ix_weight_entries_user_entry_date"):
        with op.get_context().autocommit_block():
            op.create_index(
                "ix_weight_entries_user_entry_date",
                "weight_entries",
                ["user_id", "entry_date"],
                postgresql_concurrently=True,
            )

    # ── Add source check constraint ───────────────────────────────────────────
    if not _check_constraint_exists("weight_entries", "ck_weight_entries_source_values"):
        op.create_check_constraint(
            "ck_weight_entries_source_values",
            "weight_entries",
            "source IN ('manual', 'imported', 'backfill')",
        )


def downgrade():
    if not table_exists("weight_entries"):
        return

    # Drop new objects
    if _check_constraint_exists("weight_entries", "ck_weight_entries_source_values"):
        op.drop_constraint("ck_weight_entries_source_values", "weight_entries", type_="check")

    if index_exists("weight_entries", "ix_weight_entries_user_entry_date"):
        op.drop_index("ix_weight_entries_user_entry_date", table_name="weight_entries")

    if _unique_constraint_exists("weight_entries", "uq_weight_entries_user_date_time"):
        op.drop_constraint("uq_weight_entries_user_date_time", "weight_entries", type_="unique")

    # Restore original unique constraint
    if not _unique_constraint_exists("weight_entries", "uq_weight_entries_user_date") and column_exists("weight_entries", "entry_date"):
        op.create_unique_constraint(
            "uq_weight_entries_user_date", "weight_entries", ["user_id", "entry_date"]
        )

    # Downgrade FK — drop named one, restore unnamed FK without CASCADE
    if fk_exists("weight_entries", "fk_weight_entries_user_id"):
        op.drop_constraint("fk_weight_entries_user_id", "weight_entries", type_="foreignkey")
    if not fk_exists("weight_entries", "weight_entries_user_id_fkey"):
        op.create_foreign_key(None, "weight_entries", "users", ["user_id"], ["id"])

    # Drop added columns
    for col in ("source", "notes", "entry_time", "updated_at"):
        if column_exists("weight_entries", col):
            op.drop_column("weight_entries", col)

    # Rename entry_date back to recorded_date
    if column_exists("weight_entries", "entry_date") and not column_exists("weight_entries", "recorded_date"):
        op.alter_column("weight_entries", "entry_date", new_column_name="recorded_date")
