"""Add height_cm column to users table for BMI calculation.

Revision ID: aa1b2c3d4e5f
Revises: a0o1p2q3r4s5
Create Date: 2026-06-15

"""
from alembic import op
import sqlalchemy as sa

from helpers import column_exists

revision = "aa1b2c3d4e5f"
down_revision = "a0o1p2q3r4s5"
branch_labels = None
depends_on = None


def upgrade():
    if not column_exists("users", "height_cm"):
        op.add_column("users", sa.Column("height_cm", sa.Numeric(5, 1), nullable=True))


def downgrade():
    if column_exists("users", "height_cm"):
        op.drop_column("users", "height_cm")
