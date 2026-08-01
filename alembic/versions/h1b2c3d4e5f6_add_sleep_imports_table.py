"""Sleep imports table tracks all sleep data sources before they merge into daily_metrics. Multiple imports can cover the same date from different sources; the latest 'merged' one wins. OCR/Samsung Health/Google Fit are future sources; this sprint only ships the JSON-paste path.

Revision ID: h1b2c3d4e5f6
Revises: e4f5a6b7c8d9
Create Date: 2026-05-31

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB
from helpers import table_exists, index_exists

revision = "h1b2c3d4e5f6"
down_revision = "e4f5a6b7c8d9"
branch_labels = None
depends_on = None


def upgrade():
    if table_exists("sleep_imports"):
        return

    op.create_table(
        "sleep_imports",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source", sa.String(30), nullable=False),
        sa.Column("source_identifier", sa.String(255), nullable=True),
        sa.Column("import_date", sa.Date, nullable=False),
        sa.Column("raw_data", JSONB, nullable=False),
        sa.Column("parsed_data", JSONB, nullable=True),
        sa.Column("import_status", sa.String(20), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.CheckConstraint(
            "source IN ('samsung_health', 'google_fit', 'manual_json', 'ocr_screenshot')",
            name="ck_sleep_imports_source_values",
        ),
        sa.CheckConstraint(
            "import_status IN ('pending', 'parsed', 'merged', 'rejected', 'failed')",
            name="ck_sleep_imports_import_status_values",
        ),
        sa.UniqueConstraint("user_id", "source", "source_identifier", name="uq_sleep_imports_user_source_identifier"),
    )

    if not index_exists("sleep_imports", "ix_sleep_imports_user_import_date"):
        op.create_index(
            "ix_sleep_imports_user_import_date",
            "sleep_imports",
            ["user_id", "import_date"],
        )


def downgrade():
    if not table_exists("sleep_imports"):
        return
    if index_exists("sleep_imports", "ix_sleep_imports_user_import_date"):
        op.drop_index("ix_sleep_imports_user_import_date", table_name="sleep_imports")
    op.drop_table("sleep_imports")
