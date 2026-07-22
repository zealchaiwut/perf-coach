"""add_training_preferences_and_proposals

Revision ID: fbd9a848c17f
Revises: a384a3b4727d
Create Date: 2026-07-20
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from helpers import table_exists, index_exists

revision: str = "fbd9a848c17f"
down_revision: Union[str, Sequence[str], None] = "a384a3b4727d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not table_exists("training_preferences"):
        op.create_table(
            "training_preferences",
            sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("effective_from", sa.Date(), nullable=False),
            sa.Column("payload", postgresql.JSONB(), nullable=False),
            sa.Column("source", sa.String(32), nullable=False),
            sa.Column("origin_gap_code", sa.String(80), nullable=True),
            sa.Column("origin_proposal_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("user_id", "version", name="uq_training_preferences_user_version"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.CheckConstraint(
                "source IN ('user', 'user_import', 'coach_proposal', 'carried_forward')",
                name="ck_training_preferences_source",
            ),
        )
        op.create_index(
            "ix_training_preferences_user_version",
            "training_preferences",
            ["user_id", "version"],
        )

    if not table_exists("preference_proposals"):
        op.create_table(
            "preference_proposals",
            sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("gap_code", sa.String(80), nullable=False),
            sa.Column("finding_ref", sa.String(128), nullable=True),
            sa.Column("delta", postgresql.JSONB(), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'proposed'")),
            sa.Column("proposed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("review_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("review_outcome", sa.String(32), nullable=True),
            sa.Column("dismissed_severity", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.CheckConstraint(
                "status IN ('proposed', 'accepted', 'declined', 'expired', 'reverted')",
                name="ck_preference_proposals_status",
            ),
            sa.CheckConstraint(
                "review_outcome IS NULL OR review_outcome IN "
                "('gap_closed', 'gap_persists', 'reverted')",
                name="ck_preference_proposals_review_outcome",
            ),
        )
        op.create_index(
            "ix_preference_proposals_user_status",
            "preference_proposals",
            ["user_id", "status"],
        )

    if not table_exists("user_custom_presets"):
        op.create_table(
            "user_custom_presets",
            sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("code", sa.String(80), nullable=False),
            sa.Column("payload", postgresql.JSONB(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("user_id", "code", name="uq_user_custom_presets_user_code"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        )

    if not table_exists("preference_import_audits"):
        op.create_table(
            "preference_import_audits",
            sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("raw_json", postgresql.JSONB(), nullable=False),
            sa.Column("prefs_version", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        )


def downgrade() -> None:
    for t in (
        "preference_import_audits",
        "user_custom_presets",
        "preference_proposals",
        "training_preferences",
    ):
        if table_exists(t):
            op.drop_table(t)
