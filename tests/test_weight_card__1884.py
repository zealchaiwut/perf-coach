"""Issue #1884 — weight card rate chip, eat-more, maintenance window (P6-10)."""
from __future__ import annotations

import uuid
from datetime import date, timedelta

from sqlalchemy.orm import Session

from backend.db import engine
from backend.models import Race, User, Workout
from backend.services.body_log_weight_card import (
    easy_run_efficiency_flag,
    maintenance_window,
    rate_chip_state,
    weight_card_payload,
)


def test_rate_chip_states():
    assert rate_chip_state(-0.35) == "in_range"
    assert rate_chip_state(-0.25) == "in_range"
    assert rate_chip_state(-0.1) == "slow"
    assert rate_chip_state(0.2) == "slow"
    assert rate_chip_state(-0.9) == "too_fast"
    assert rate_chip_state(None) == "unknown"


def test_easy_run_efficiency_flag_fixture():
    today = date(2026, 3, 10)
    eff = []
    for i in range(20):
        d = today - timedelta(days=27 - i)
        eff.append((d, 2.0))
    for i in range(7):
        eff.append((today - timedelta(days=6 - i), 1.5))
    assert easy_run_efficiency_flag(eff, today) is True
    eff2 = [(today - timedelta(days=i), 2.0) for i in range(25)]
    assert easy_run_efficiency_flag(eff2, today) is False


def test_maintenance_window_toggles():
    uid = uuid.uuid4()
    race_day = date(2026, 6, 1)
    today_in = race_day - timedelta(days=10)
    today_out = race_day - timedelta(days=30)
    with Session(engine) as session:
        session.add(
            User(id=uid, name=f"maint_{uid.hex[:6]}", password_hash="x", is_active=True)
        )
        session.add(
            Race(
                user_id=uid,
                name="A Race",
                race_date=race_day,
                distance_km=42.2,
                priority="A",
                status="planned",
            )
        )
        session.commit()
        assert maintenance_window(session, uid, today_in)[0] is True
        assert maintenance_window(session, uid, today_out)[0] is False
        session.query(Race).filter(Race.user_id == uid).delete()
        session.query(User).filter(User.id == uid).delete()
        session.commit()


def test_eat_more_from_rate_only():
    uid = uuid.uuid4()
    today = date(2026, 4, 1)
    rows = [(today - timedelta(days=i), 90.0 - i * 0.2) for i in range(14)]
    with Session(engine) as session:
        session.add(User(id=uid, name=f"wc_{uid.hex[:6]}", password_hash="x", is_active=True))
        session.commit()
        payload = weight_card_payload(session, uid, weight_rows=rows, today=today)
        assert payload["rate_chip"] in ("too_fast", "in_range", "slow")
        session.query(User).filter(User.id == uid).delete()
        session.commit()