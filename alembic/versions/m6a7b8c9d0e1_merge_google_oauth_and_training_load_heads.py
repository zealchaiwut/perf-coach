"""merge google_oauth_credentials and training_load_snapshots heads

Both g0a1b2c3d4e5 (add google_oauth_credentials table) and k4e5f6a7b8c9
(add training_load_snapshots table) branched from f7a8b9c0d1e2 and were never
reconciled, leaving develop with two Alembic heads — which makes
`alembic upgrade head` fail. This is a no-op merge node that joins them back
into a single head.

Revision ID: m6a7b8c9d0e1
Revises: g0a1b2c3d4e5, k4e5f6a7b8c9
Create Date: 2026-06-01

"""

revision = "m6a7b8c9d0e1"
down_revision = ("g0a1b2c3d4e5", "k4e5f6a7b8c9")
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
