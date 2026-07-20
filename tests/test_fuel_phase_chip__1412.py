"""Tests for issue #1412: phase chip shown even when auto_periodize is off.

AC: When auto_periodize=False the API payload must return week_phase='base'
regardless of race proximity, so the frontend chip is never shown with
misleading modulation copy while the budget is unmodulated.
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy.orm import Session

from backend.db import engine
from backend.models import FuelSettings, Race, User
from backend.services import fuel


# ── Shared fixture ────────────────────────────────────────────────────────────

@pytest.fixture()
def phase_user():
    uid = uuid.uuid4()
    with Session(engine) as db:
        db.add(User(id=uid, name=f"phasetest_{uid.hex[:8]}", password_hash="x",
                    is_admin=False, is_active=True))
        db.commit()
    yield uid
    with Session(engine) as db:
        db.query(FuelSettings).filter(FuelSettings.user_id == uid).delete()
        db.query(Race).filter(Race.user_id == uid).delete()
        db.query(User).filter(User.id == uid).delete()
        db.commit()


def _add_settings(db, user_id, auto_periodize: bool):
    db.add(FuelSettings(
        user_id=user_id,
        weight_kg=70,
        base_kcal=2400,
        deficit_kcal=300,
        protein_g_per_kg=2.0,
        fat_g=70,
        ea_floor=30,
        run_kcal_per_kg_per_km=1.0,
        auto_periodize=auto_periodize,
    ))
    db.commit()


def _add_race_within_7d(db, user_id):
    db.add(Race(
        user_id=user_id,
        name="Test Race",
        race_date=date.today() + timedelta(days=3),
        distance_km=42.195,
        priority="A",
        status="planned",
    ))
    db.commit()


# ── AC1: today payload suppresses phase when auto_periodize is off ────────────

def test_get_today_payload_auto_periodize_off_returns_base_phase_even_with_race(phase_user):
    """Payload must report week_phase='base' when toggle is off, even with a
    race within 7 days (which would otherwise trigger 'race' phase)."""
    with Session(engine) as db:
        _add_settings(db, phase_user, auto_periodize=False)
        _add_race_within_7d(db, phase_user)
        payload = fuel.get_today_payload(phase_user, date.today(), db=db)

    assert payload["week_phase"] == "base", (
        f"Expected 'base' but got {payload['week_phase']!r} — "
        "chip would show misleading race-week copy while budget is unmodulated"
    )


def test_get_today_payload_auto_periodize_off_effective_deficit_equals_target(phase_user):
    """When toggle is off, effective_deficit_kcal must equal deficit_target."""
    with Session(engine) as db:
        _add_settings(db, phase_user, auto_periodize=False)
        _add_race_within_7d(db, phase_user)
        payload = fuel.get_today_payload(phase_user, date.today(), db=db)

    assert payload["effective_deficit_kcal"] == payload["deficit_target"], (
        "effective_deficit_kcal must equal deficit_target when auto_periodize is off"
    )


# ── AC2: week payload suppresses phase when auto_periodize is off ─────────────

def test_get_week_payload_auto_periodize_off_returns_base_phase_even_with_race(phase_user):
    """Week payload must also report week_phase='base' when toggle is off."""
    week_start = date.today() - timedelta(days=date.today().weekday())
    with Session(engine) as db:
        _add_settings(db, phase_user, auto_periodize=False)
        _add_race_within_7d(db, phase_user)
        payload = fuel.get_week_payload(phase_user, week_start, db=db)

    assert payload["week_phase"] == "base", (
        f"Expected 'base' but got {payload['week_phase']!r} — "
        "week note would show misleading phase copy while budget is unmodulated"
    )


# ── AC3: regression — race phase still reported when auto_periodize is on ─────

def test_get_today_payload_auto_periodize_on_race_in_7d_returns_race_phase(phase_user):
    """When toggle is on and a race is within 7 days, payload must still
    return week_phase='race' (regression guard)."""
    with Session(engine) as db:
        _add_settings(db, phase_user, auto_periodize=True)
        _add_race_within_7d(db, phase_user)
        payload = fuel.get_today_payload(phase_user, date.today(), db=db)

    assert payload["week_phase"] == "race", (
        f"Expected 'race' but got {payload['week_phase']!r} — "
        "auto_periodize=True should still apply phase modulation"
    )
    assert payload["effective_deficit_kcal"] == 0, (
        "Race week with auto_periodize on must zero the deficit (maintenance)"
    )
