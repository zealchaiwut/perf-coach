"""encrypt_oauth_tokens_at_rest

Encrypt Strava and Google OAuth access/refresh tokens using Fernet (OAUTH_FERNET_KEY).
Existing plaintext rows are backfilled during upgrade. The old plaintext columns are
dropped after the backfill to prevent any residual exposure.

Revision ID: b1be92b4c4ff
Revises: 7921872665c9
Create Date: 2026-08-06 17:37:58.209841

"""
import os
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from cryptography.fernet import Fernet

from helpers import column_exists

revision: str = "b1be92b4c4ff"
down_revision: Union[str, Sequence[str], None] = "7921872665c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_GENERATE_CMD = (
    'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
)


def _get_fernet() -> Fernet:
    key = os.environ.get("OAUTH_FERNET_KEY")
    if not key:
        raise RuntimeError(
            "OAUTH_FERNET_KEY must be set to run this migration. "
            f"Generate a key with: {_GENERATE_CMD} and add it to your .env and Render env vars."
        )
    return Fernet(key.encode())


def upgrade() -> None:
    conn = op.get_bind()

    # ── strava_tokens ──────────────────────────────────────────────────────────
    if not column_exists("strava_tokens", "access_token_encrypted"):
        op.add_column("strava_tokens", sa.Column("access_token_encrypted", sa.Text(), nullable=True))
    if not column_exists("strava_tokens", "refresh_token_encrypted"):
        op.add_column("strava_tokens", sa.Column("refresh_token_encrypted", sa.Text(), nullable=True))

    # Backfill plaintext → encrypted
    strava_rows = conn.execute(
        sa.text(
            "SELECT id, access_token, refresh_token FROM strava_tokens "
            "WHERE access_token_encrypted IS NULL"
        )
    ).fetchall()

    if strava_rows:
        fernet = _get_fernet()
        for row in strava_rows:
            enc_at = fernet.encrypt(row.access_token.encode()).decode()
            enc_rt = fernet.encrypt(row.refresh_token.encode()).decode()
            conn.execute(
                sa.text(
                    "UPDATE strava_tokens "
                    "SET access_token_encrypted = :at, refresh_token_encrypted = :rt "
                    "WHERE id = :id"
                ),
                {"at": enc_at, "rt": enc_rt, "id": str(row.id)},
            )

    # Only enforce NOT NULL after backfill (safe even when table is empty)
    op.alter_column("strava_tokens", "access_token_encrypted", nullable=False)
    op.alter_column("strava_tokens", "refresh_token_encrypted", nullable=False)

    # Drop old plaintext columns
    if column_exists("strava_tokens", "access_token"):
        op.drop_column("strava_tokens", "access_token")
    if column_exists("strava_tokens", "refresh_token"):
        op.drop_column("strava_tokens", "refresh_token")

    # ── google_oauth_credentials ───────────────────────────────────────────────
    if not column_exists("google_oauth_credentials", "access_token_encrypted"):
        op.add_column(
            "google_oauth_credentials",
            sa.Column("access_token_encrypted", sa.Text(), nullable=True),
        )
    if not column_exists("google_oauth_credentials", "refresh_token_encrypted"):
        op.add_column(
            "google_oauth_credentials",
            sa.Column("refresh_token_encrypted", sa.Text(), nullable=True),
        )

    google_rows = conn.execute(
        sa.text(
            "SELECT id, access_token, refresh_token FROM google_oauth_credentials "
            "WHERE access_token_encrypted IS NULL"
        )
    ).fetchall()

    if google_rows:
        fernet = _get_fernet()
        for row in google_rows:
            enc_at = fernet.encrypt(row.access_token.encode()).decode()
            enc_rt = fernet.encrypt(row.refresh_token.encode()).decode() if row.refresh_token else None
            conn.execute(
                sa.text(
                    "UPDATE google_oauth_credentials "
                    "SET access_token_encrypted = :at, refresh_token_encrypted = :rt "
                    "WHERE id = :id"
                ),
                {"at": enc_at, "rt": enc_rt, "id": str(row.id)},
            )

    op.alter_column("google_oauth_credentials", "access_token_encrypted", nullable=False)
    # refresh_token_encrypted stays nullable (Google may omit it on silent refreshes)

    if column_exists("google_oauth_credentials", "access_token"):
        op.drop_column("google_oauth_credentials", "access_token")
    if column_exists("google_oauth_credentials", "refresh_token"):
        op.drop_column("google_oauth_credentials", "refresh_token")


def downgrade() -> None:
    """Restore plaintext columns (decrypt from encrypted values if key is available)."""
    conn = op.get_bind()

    # ── strava_tokens ──────────────────────────────────────────────────────────
    if not column_exists("strava_tokens", "access_token"):
        op.add_column("strava_tokens", sa.Column("access_token", sa.Text(), nullable=True))
    if not column_exists("strava_tokens", "refresh_token"):
        op.add_column("strava_tokens", sa.Column("refresh_token", sa.Text(), nullable=True))

    strava_rows = conn.execute(
        sa.text(
            "SELECT id, access_token_encrypted, refresh_token_encrypted FROM strava_tokens "
            "WHERE access_token IS NULL"
        )
    ).fetchall()

    if strava_rows:
        fernet = _get_fernet()
        for row in strava_rows:
            at = fernet.decrypt(row.access_token_encrypted.encode()).decode()
            rt = fernet.decrypt(row.refresh_token_encrypted.encode()).decode()
            conn.execute(
                sa.text(
                    "UPDATE strava_tokens SET access_token = :at, refresh_token = :rt WHERE id = :id"
                ),
                {"at": at, "rt": rt, "id": str(row.id)},
            )

    op.alter_column("strava_tokens", "access_token", nullable=False)
    op.alter_column("strava_tokens", "refresh_token", nullable=False)

    if column_exists("strava_tokens", "access_token_encrypted"):
        op.drop_column("strava_tokens", "access_token_encrypted")
    if column_exists("strava_tokens", "refresh_token_encrypted"):
        op.drop_column("strava_tokens", "refresh_token_encrypted")

    # ── google_oauth_credentials ───────────────────────────────────────────────
    if not column_exists("google_oauth_credentials", "access_token"):
        op.add_column(
            "google_oauth_credentials", sa.Column("access_token", sa.Text(), nullable=True)
        )
    if not column_exists("google_oauth_credentials", "refresh_token"):
        op.add_column(
            "google_oauth_credentials", sa.Column("refresh_token", sa.Text(), nullable=True)
        )

    google_rows = conn.execute(
        sa.text(
            "SELECT id, access_token_encrypted, refresh_token_encrypted FROM google_oauth_credentials "
            "WHERE access_token IS NULL"
        )
    ).fetchall()

    if google_rows:
        fernet = _get_fernet()
        for row in google_rows:
            at = fernet.decrypt(row.access_token_encrypted.encode()).decode()
            rt = (
                fernet.decrypt(row.refresh_token_encrypted.encode()).decode()
                if row.refresh_token_encrypted
                else None
            )
            conn.execute(
                sa.text(
                    "UPDATE google_oauth_credentials "
                    "SET access_token = :at, refresh_token = :rt WHERE id = :id"
                ),
                {"at": at, "rt": rt, "id": str(row.id)},
            )

    op.alter_column("google_oauth_credentials", "access_token", nullable=False)

    if column_exists("google_oauth_credentials", "access_token_encrypted"):
        op.drop_column("google_oauth_credentials", "access_token_encrypted")
    if column_exists("google_oauth_credentials", "refresh_token_encrypted"):
        op.drop_column("google_oauth_credentials", "refresh_token_encrypted")
