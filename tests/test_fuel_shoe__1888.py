"""P6-14 (#1888) — fuel log and shoe tag on runs."""
from __future__ import annotations

import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

from backend.models import AthleteShoe, Workout
from backend.services.athlete_shoes import fuel_logging_required, recompute_shoe_stats


def test_fuel_required_for_90_min_and_races():
    w = Workout(workout_type="run", duration_seconds=89 * 60)
    assert fuel_logging_required(w) is False
    w.duration_seconds = 90 * 60
    assert fuel_logging_required(w) is True
    assert fuel_logging_required(w, is_race=True) is True


def test_shoe_km_recompute():
    uid = uuid.uuid4()
    session = MagicMock()
    shoe = AthleteShoe(user_id=uid, name="Race flat")
    shoe.id = uuid.uuid4()
    w1 = Workout(
        user_id=uid,
        workout_date=date(2026, 11, 1),
        name="Long",
        workout_type="run",
        distance_km=32,
        duration_seconds=3 * 3600,
        shoe_id=shoe.id,
    )
    w2 = Workout(
        user_id=uid,
        workout_date=date(2026, 11, 8),
        name="Easy",
        workout_type="run",
        distance_km=10,
        duration_seconds=3600,
        shoe_id=shoe.id,
    )

    def query(model):
        q = MagicMock()
        if model is Workout:
            q.filter.return_value.all.return_value = [w1, w2]
        if model is AthleteShoe:
            pass
        return q

    session.get.return_value = shoe
    session.query.side_effect = query
    recompute_shoe_stats(session, uid, shoe.id)
    assert float(shoe.total_km) == 42.0
    assert float(shoe.longest_run_km) == 32.0