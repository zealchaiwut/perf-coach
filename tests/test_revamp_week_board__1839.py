"""Week plan board (P3-5, #1839)."""
from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy.orm import Session

from backend.models import PlannedSession, User
from backend.services.revamp_week_board import effective_plan_source, week_board


def test_effective_plan_source_prefers_column():
    row = PlannedSession(
        user_id=uuid.uuid4(),
        planned_date=date.today(),
        session_type="strength",
        plan_source="coach",
    )
    assert effective_plan_source(row) == "coach"


def test_week_board_rest_placeholder(db_session: Session, user: User):
    today = date.today()
    ws = today - timedelta(days=today.weekday())
    prefs_payload = {"rest_days": [ws.weekday()]}
    from backend.models import TrainingPreference

    row = TrainingPreference(
        user_id=user.id,
        version=1,
        payload=prefs_payload,
        source="user",
        effective_from=ws,
        confirmed_at=None,
    )
    db_session.add(row)
    db_session.commit()

    payload = week_board(user.id, ws, session=db_session, today=today)
    assert len(payload["days"]) == 7
    rest_day = next(d for d in payload["days"] if d["weekday"] == ws.weekday())
    assert rest_day["rest_placeholder"] is True


@pytest.fixture()
def db_session():
    pytest.importorskip("dotenv")
    import os
    from sqlalchemy import create_engine
    from dotenv import dotenv_values

    url = os.environ.get("DATABASE_URL_UAT") or dotenv_values(".env").get("DATABASE_URL_UAT")
    if not url:
        pytest.skip("DATABASE_URL_UAT not set")
    engine = create_engine(url, pool_pre_ping=True)
    with Session(engine) as s:
        yield s


@pytest.fixture()
def user(db_session):
    u = User(name=f"board_{uuid.uuid4().hex[:8]}")
    db_session.add(u)
    db_session.commit()
    db_session.refresh(u)
    yield u
    db_session.delete(u)
    db_session.commit()