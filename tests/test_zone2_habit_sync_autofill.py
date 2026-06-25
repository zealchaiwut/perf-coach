"""Regression: Strava/Stryd sync must trigger habit autofill.

Sync writes runs directly via reconcile.compute_run_metrics (bypassing the
workout CRUD endpoints that normally trigger autofill), so a Zone-2 habit
fed by `workout.zone2_minutes` never updated from synced runs. After the fix,
compute_run_metrics re-runs recompute_autofill_for_week for the weeks its runs
touch.
"""
import uuid
from datetime import date
from unittest.mock import MagicMock, patch

from backend.models import UserPreferences, Workout, WorkoutSplit
import backend.services.reconcile as reconcile

_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000222")


def _run(workout_date, *, avg_hr, duration_seconds, tss=10.0):
    w = MagicMock(spec=Workout)
    w.id = uuid.uuid4()
    w.user_id = _USER_ID
    w.workout_date = workout_date
    w.avg_hr = avg_hr
    w.duration_seconds = duration_seconds
    w.zone2_minutes = None
    w.tss = tss  # non-None so the TSS-estimation branch is skipped
    return w


def _session_with_runs(runs):
    """Mock Session context manager whose .query(Model) dispatches by model."""
    sess = MagicMock()

    def _query(model):
        q = MagicMock()
        if model is UserPreferences:
            q.filter.return_value.first.return_value = None  # use HR-band defaults
        elif model is Workout:
            q.filter.return_value.all.return_value = runs
        elif model is WorkoutSplit:
            q.filter.return_value.all.return_value = []  # no splits → workout-level HR path
        else:
            q.filter.return_value.all.return_value = []
        return q

    sess.query.side_effect = _query
    ctx = MagicMock()
    ctx.__enter__.return_value = sess
    ctx.__exit__.return_value = False
    return ctx


def test_in_band_run_triggers_autofill_for_its_week():
    run = _run(date(2026, 6, 25), avg_hr=140, duration_seconds=3600)  # Thu; band default 130-155
    with patch.object(reconcile, "_Session", return_value=_session_with_runs([run])), \
         patch("backend.services.habit_autofill.recompute_autofill_for_week") as mock_af:
        reconcile.compute_run_metrics(_USER_ID)

    assert run.zone2_minutes == 60  # 3600s / 60, full duration in-band
    mock_af.assert_called_once()
    args = mock_af.call_args.args
    assert args[0] == _USER_ID
    assert args[1] == date(2026, 6, 22)  # Monday of the run's week


def test_no_runs_means_no_autofill():
    with patch.object(reconcile, "_Session", return_value=_session_with_runs([])), \
         patch("backend.services.habit_autofill.recompute_autofill_for_week") as mock_af:
        reconcile.compute_run_metrics(_USER_ID)
    mock_af.assert_not_called()


def test_runs_in_two_weeks_trigger_autofill_per_week():
    r1 = _run(date(2026, 6, 25), avg_hr=140, duration_seconds=1800)  # week of Jun 22
    r2 = _run(date(2026, 6, 17), avg_hr=145, duration_seconds=1800)  # week of Jun 15
    with patch.object(reconcile, "_Session", return_value=_session_with_runs([r1, r2])), \
         patch("backend.services.habit_autofill.recompute_autofill_for_week") as mock_af:
        reconcile.compute_run_metrics(_USER_ID)

    weeks = {c.args[1] for c in mock_af.call_args_list}
    assert weeks == {date(2026, 6, 22), date(2026, 6, 15)}
