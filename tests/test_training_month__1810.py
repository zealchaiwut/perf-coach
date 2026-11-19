from datetime import date

from backend.db import engine
from backend.services.training_month import grid_range, training_month
from sqlalchemy.orm import Session


def test_grid_range_covers_full_weeks():
    start, end = grid_range(date(2026, 11, 15))
    assert start.weekday() == 0
    assert end.weekday() == 6
    assert start <= date(2026, 11, 1) <= end


def test_training_month_week_starts_are_mondays():
    with Session(engine) as session:
        payload = training_month(session, _any_user_id(session), date(2026, 11, 1), today=date(2026, 11, 18))
    for week in payload["weeks"]:
        ws = date.fromisoformat(week["week_start"])
        assert ws.weekday() == 0
        assert len(week["days"]) == 7
        assert "rollup" in week


def _any_user_id(session):
    from backend.models import User

    row = session.query(User).first()
    assert row is not None, "need at least one user in DB for integration test"
    return row.id