"""Regression: an autofill habit must not double-count its stored
workout_autofill rows against the live recomputed workout values.

Bug: GET /api/habits/week summed logs_by_habit (which includes the
source='workout_autofill' rows the autofill writer persisted) AND the
freshly computed_logs from workouts — counting the same minutes twice
(e.g. zone-2 showed 172 instead of ~100).
"""
import datetime as _dt
from types import SimpleNamespace

from backend.main import _aggregate_weekly_progress


def _log(d, value, source):
    return SimpleNamespace(log_date=_dt.date.fromisoformat(d), value=value, source=source)


def test_stored_autofill_rows_not_double_counted():
    # Autofill persisted 100 zone-2 min on Tue (drives the daily grid),
    # and the live computed_logs also reports 100 for Tue.
    manual_rows = [_log("2026-06-23", 100, "workout_autofill")]
    computed = [{"date": "2026-06-23", "value": 100.0, "source": "workout.zone2_minutes"}]

    out = _aggregate_weekly_progress(manual_rows, computed, 210)
    assert out["current_value"] == 100.0  # not 200


def test_true_manual_entry_still_counts_with_computed():
    # A genuine manual entry (source='manual') is a separate contribution.
    manual_rows = [_log("2026-06-22", 30, "manual")]
    computed = [{"date": "2026-06-23", "value": 100.0, "source": "workout.zone2_minutes"}]

    out = _aggregate_weekly_progress(manual_rows, computed, 210)
    assert out["current_value"] == 130.0


def test_manual_override_replaces_computed():
    manual_rows = [_log("2026-06-23", 80, "manual_override")]
    computed = [{"date": "2026-06-23", "value": 100.0, "source": "workout.zone2_minutes"}]

    out = _aggregate_weekly_progress(manual_rows, computed, 210)
    assert out["current_value"] == 80.0
