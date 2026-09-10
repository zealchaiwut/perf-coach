from alembic import op
from sqlalchemy import inspect, text


def table_exists(name: str) -> bool:
    bind = op.get_bind()
    return inspect(bind).has_table(name)


def column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    if not inspect(bind).has_table(table):
        return False
    return any(c["name"] == column for c in inspect(bind).get_columns(table))


def index_exists(table: str, name: str) -> bool:
    bind = op.get_bind()
    if not inspect(bind).has_table(table):
        return False
    return any(i["name"] == name for i in inspect(bind).get_indexes(table))


def valid_index_exists(table: str, name: str) -> bool:
    """Return True only when the named index exists AND is valid (indisvalid=True).

    CREATE INDEX CONCURRENTLY can leave an INVALID index on failure; the plain
    index_exists() guard would see it and skip re-creation, permanently leaving
    a broken index. This helper checks pg_index.indisvalid so INVALID indexes
    are treated as absent and the CONCURRENTLY build is retried.
    """
    bind = op.get_bind()
    row = bind.execute(
        text(
            "SELECT pg_index.indisvalid "
            "FROM pg_class "
            "JOIN pg_index ON pg_class.oid = pg_index.indexrelid "
            "WHERE pg_class.relname = :name "
            "AND pg_class.relkind = 'i'"
        ),
        {"name": name},
    ).fetchone()
    if row is None:
        return False
    return bool(row[0])


def fk_exists(table: str, name: str) -> bool:
    bind = op.get_bind()
    if not inspect(bind).has_table(table):
        return False
    return any(fk["name"] == name for fk in inspect(bind).get_foreign_keys(table))
