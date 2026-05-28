from alembic import op
from sqlalchemy import inspect


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


def fk_exists(table: str, name: str) -> bool:
    bind = op.get_bind()
    if not inspect(bind).has_table(table):
        return False
    return any(fk["name"] == name for fk in inspect(bind).get_foreign_keys(table))
