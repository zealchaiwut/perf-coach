"""add_fuel_settings_and_fuel_entries_tables

Revision ID: d4009bf7086a
Revises: a2f7ab0f10a1
Create Date: 2026-07-10 09:45:34.108113

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from helpers import table_exists


# revision identifiers, used by Alembic.
revision: str = 'd4009bf7086a'
down_revision: Union[str, Sequence[str], None] = 'a2f7ab0f10a1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create fuel_settings and fuel_entries tables (idempotent)."""
    if not table_exists("fuel_settings"):
        op.create_table(
            "fuel_settings",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                server_default=sa.text("gen_random_uuid()"),
                nullable=False,
            ),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("weight_kg", sa.Numeric(5, 2), nullable=False),
            sa.Column("lean_mass_kg", sa.Numeric(5, 2), nullable=True),
            sa.Column("base_kcal", sa.Integer(), nullable=False),
            sa.Column("maintenance_source", sa.Text(), nullable=False, server_default=sa.text("'estimated'")),
            sa.Column("deficit_kcal", sa.Integer(), nullable=False, server_default=sa.text("300")),
            sa.Column("protein_g_per_kg", sa.Numeric(4, 2), nullable=False, server_default=sa.text("2.0")),
            sa.Column("fat_g", sa.Integer(), nullable=False, server_default=sa.text("70")),
            sa.Column("ea_floor", sa.Numeric(5, 2), nullable=False, server_default=sa.text("30.0")),
            sa.Column("run_kcal_per_kg_per_km", sa.Numeric(4, 2), nullable=False, server_default=sa.text("1.0")),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(
                ["user_id"], ["users.id"], ondelete="CASCADE", name="fuel_settings_user_id_fkey",
            ),
            sa.UniqueConstraint("user_id", name="uq_fuel_settings_user_id"),
            sa.CheckConstraint(
                "maintenance_source IN ('estimated', 'measured')",
                name="ck_fuel_settings_maintenance_source",
            ),
            sa.CheckConstraint("deficit_kcal >= 0 AND deficit_kcal <= 750", name="ck_fuel_settings_deficit_kcal"),
            sa.CheckConstraint(
                "protein_g_per_kg >= 0.25 AND protein_g_per_kg <= 2.5",
                name="ck_fuel_settings_protein_g_per_kg",
            ),
            sa.CheckConstraint("fat_g > 0", name="ck_fuel_settings_fat_g"),
            sa.CheckConstraint("ea_floor > 0", name="ck_fuel_settings_ea_floor"),
            sa.CheckConstraint("run_kcal_per_kg_per_km > 0", name="ck_fuel_settings_run_kcal_per_kg_per_km"),
        )

    if not table_exists("fuel_entries"):
        op.create_table(
            "fuel_entries",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                server_default=sa.text("gen_random_uuid()"),
                nullable=False,
            ),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("entry_date", sa.Date(), nullable=False),
            sa.Column("meat_g", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("rice_g", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("eggs", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("fruit_g", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("oil_tsp", sa.Numeric(4, 1), nullable=False, server_default=sa.text("0")),
            sa.Column("other_kcal", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("other_protein_g", sa.Numeric(6, 1), nullable=False, server_default=sa.text("0")),
            sa.Column("other_carbs_g", sa.Numeric(6, 1), nullable=False, server_default=sa.text("0")),
            sa.Column("other_fat_g", sa.Numeric(6, 1), nullable=False, server_default=sa.text("0")),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(
                ["user_id"], ["users.id"], ondelete="CASCADE", name="fuel_entries_user_id_fkey",
            ),
            sa.UniqueConstraint("user_id", "entry_date", name="uq_fuel_entries_user_date"),
            sa.CheckConstraint("meat_g >= 0", name="ck_fuel_entries_meat_g"),
            sa.CheckConstraint("rice_g >= 0", name="ck_fuel_entries_rice_g"),
            sa.CheckConstraint("eggs >= 0", name="ck_fuel_entries_eggs"),
            sa.CheckConstraint("fruit_g >= 0", name="ck_fuel_entries_fruit_g"),
            sa.CheckConstraint("oil_tsp >= 0", name="ck_fuel_entries_oil_tsp"),
            sa.CheckConstraint("other_kcal >= 0", name="ck_fuel_entries_other_kcal"),
            sa.CheckConstraint("other_protein_g >= 0", name="ck_fuel_entries_other_protein_g"),
            sa.CheckConstraint("other_carbs_g >= 0", name="ck_fuel_entries_other_carbs_g"),
            sa.CheckConstraint("other_fat_g >= 0", name="ck_fuel_entries_other_fat_g"),
        )
        op.create_index(
            "ix_fuel_entries_user_date",
            "fuel_entries",
            ["user_id", sa.text("entry_date DESC")],
        )


def downgrade() -> None:
    """Drop fuel_entries and fuel_settings tables."""
    if table_exists("fuel_entries"):
        op.drop_index("ix_fuel_entries_user_date", table_name="fuel_entries")
        op.drop_table("fuel_entries")
    if table_exists("fuel_settings"):
        op.drop_table("fuel_settings")
