"""Persistent key-value app settings (the ``app_config`` table).

Extracted out of ``backend/main.py`` so both the webapp and the admin router
(shared between ``backend/main.py`` and ``backend/worker_app.py``) can read/write
config without either importing the other.
"""
from __future__ import annotations

import os
from datetime import datetime as _datetime, timezone as _timezone

from sqlalchemy.dialects.postgresql import insert as _pg_insert
from sqlalchemy.orm import Session

from backend.db import engine
from backend.models import AppConfig

APP_CONFIG_GOOGLE_LOGIN = "google_login_enabled"


def get_app_config(key: str, default: str = "") -> str:
    with Session(engine) as session:
        row = session.get(AppConfig, key)
        return row.value if row else default


def set_app_config(key: str, value: str) -> None:
    with Session(engine) as session:
        stmt = (
            _pg_insert(AppConfig)
            .values(key=key, value=value, updated_at=_datetime.now(tz=_timezone.utc))
            .on_conflict_do_update(
                index_elements=["key"],
                set_={"value": value, "updated_at": _datetime.now(tz=_timezone.utc)},
            )
        )
        session.execute(stmt)
        session.commit()


def google_credentials_present() -> bool:
    return bool(os.getenv("GOOGLE_CLIENT_ID")) and bool(os.getenv("GOOGLE_CLIENT_SECRET"))
