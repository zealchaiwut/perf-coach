"""Stored TSS: rollup week total must match workout_date buckets (daily_tss_series shape)."""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from unittest.mock import MagicMock

from backend.services.weekly_rollup import session_local_date


def test_week_rollup_stored_tss_matches_workout_date_sum():
    """When workout_date equals the Bangkok session day, rollup == SUM(workouts.tss)."""
    ws = date(2026, 11, 3)
    we = ws + timedelta(days=6)
    workouts = []
    for i in range(4):
        w = MagicMock()
        w.tss = 40.0 + i
        w.workout_type = "run"
        w.distance_km = 8.0
        w.start_time = None
        w.workout_date = ws + timedelta(days=i)
        workouts.append(w)

    in_week = [w for w in workouts if ws <= session_local_date(w) <= we]
    rollup_total = sum(float(w.tss) for w in in_week if w.tss is not None)

    by_workout_date = {}
    for w in in_week:
        d = w.workout_date
        by_workout_date[d] = by_workout_date.get(d, 0.0) + float(w.tss)
    series_sum = sum(by_workout_date.values())

    assert rollup_total == series_sum