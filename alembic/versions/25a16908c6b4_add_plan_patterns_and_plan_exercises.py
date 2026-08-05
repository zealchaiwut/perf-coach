"""add_plan_patterns_and_plan_exercises

Revision ID: 25a16908c6b4
Revises: 63d019bb0d5b
Create Date: 2026-08-04 08:51:34.433245

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from helpers import table_exists


revision: str = "25a16908c6b4"
down_revision: Union[str, Sequence[str], None] = "63d019bb0d5b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not table_exists("plan_patterns"):
        op.create_table(
            "plan_patterns",
            sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
            sa.Column("kind", sa.String(20), nullable=False),
            sa.Column("subtype", sa.String(40), nullable=False),
            sa.Column("duration_min_lo", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("duration_min_hi", sa.Integer(), nullable=False, server_default="120"),
            sa.Column("name", sa.String(120), nullable=False),
            sa.Column("priority", sa.Integer(), nullable=False, server_default="10"),
            sa.Column("recipe", postgresql.JSONB(), nullable=False),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.CheckConstraint("kind IN ('run', 'strength')", name="ck_plan_patterns_kind"),
        )
        op.create_index("ix_plan_patterns_kind_subtype", "plan_patterns", ["kind", "subtype"])
        op.create_index("ix_plan_patterns_active", "plan_patterns", ["active"])

    if not table_exists("plan_exercises"):
        op.create_table(
            "plan_exercises",
            sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("groups", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
            sa.Column("focus_tags", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
            sa.Column("body_parts", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
            sa.Column("tss_weight", sa.Float(), nullable=False, server_default="1.0"),
            sa.Column("default_sets", sa.Integer(), nullable=True),
            sa.Column("default_reps", sa.String(40), nullable=True),
            sa.Column("default_load", sa.String(80), nullable=True),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.UniqueConstraint("name", name="uq_plan_exercises_name"),
        )
        op.create_index("ix_plan_exercises_active", "plan_exercises", ["active"])

    # Seed defaults (idempotent by name / kind+subtype+name).
    from backend.services.plan_pattern_seeds import all_default_patterns, default_exercises
    import json

    conn = op.get_bind()
    for p in all_default_patterns():
        exists = conn.execute(
            sa.text(
                "SELECT 1 FROM plan_patterns WHERE kind=:k AND subtype=:s AND name=:n LIMIT 1"
            ),
            {"k": p["kind"], "s": p["subtype"], "n": p["name"]},
        ).fetchone()
        if exists:
            continue
        conn.execute(
            sa.text(
                "INSERT INTO plan_patterns "
                "(kind, subtype, duration_min_lo, duration_min_hi, name, priority, recipe, active) "
                "VALUES (:kind, :subtype, :lo, :hi, :name, :priority, CAST(:recipe AS jsonb), true)"
            ),
            {
                "kind": p["kind"],
                "subtype": p["subtype"],
                "lo": p["duration_min_lo"],
                "hi": p["duration_min_hi"],
                "name": p["name"],
                "priority": p["priority"],
                "recipe": json.dumps(p["recipe"]),
            },
        )
    for e in default_exercises():
        exists = conn.execute(
            sa.text("SELECT 1 FROM plan_exercises WHERE name=:n LIMIT 1"),
            {"n": e["name"]},
        ).fetchone()
        if exists:
            continue
        conn.execute(
            sa.text(
                "INSERT INTO plan_exercises "
                "(name, groups, focus_tags, body_parts, tss_weight, default_sets, default_reps, default_load, active) "
                "VALUES (:name, CAST(:groups AS jsonb), CAST(:focus AS jsonb), CAST(:parts AS jsonb), "
                ":tw, :sets, :reps, :load, true)"
            ),
            {
                "name": e["name"],
                "groups": json.dumps(e["groups"]),
                "focus": json.dumps(e["focus_tags"]),
                "parts": json.dumps(e["body_parts"]),
                "tw": e["tss_weight"],
                "sets": e["default_sets"],
                "reps": e["default_reps"],
                "load": e["default_load"],
            },
        )


def downgrade() -> None:
    if table_exists("plan_exercises"):
        op.drop_table("plan_exercises")
    if table_exists("plan_patterns"):
        op.drop_table("plan_patterns")
