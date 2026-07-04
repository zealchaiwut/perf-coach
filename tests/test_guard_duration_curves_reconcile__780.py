"""Tests for issue #780: guard _update_duration_curves with try/except in reconcile_workouts."""
import logging
import uuid
from unittest.mock import MagicMock, patch


from backend.services import sync_jobs
from backend.services.reconcile import reconcile_workouts


def _clear_registry():
    with sync_jobs._lock:
        sync_jobs._registry.clear()


def _make_uid():
    return uuid.uuid4()


def _make_session():
    """Minimal mock session that returns empty result sets."""
    session = MagicMock()
    session.__enter__ = lambda s: s
    session.__exit__ = MagicMock(return_value=False)
    q = MagicMock()
    q.filter.return_value = q
    q.options.return_value = q
    q.all.return_value = []
    session.query.return_value = q
    return session


# AC1 + AC3: _update_duration_curves raising must not propagate out of reconcile_workouts
def test_duration_curve_exception_does_not_propagate():
    """reconcile_workouts must return normally even when _update_duration_curves raises."""
    _clear_registry()
    uid = _make_uid()
    sync_jobs.start(uid, "strava")

    session = _make_session()
    with patch("backend.services.reconcile._Session", return_value=session), \
         patch("backend.services.reconcile.compute_run_metrics"), \
         patch("backend.services.reconcile._update_duration_curves",
               side_effect=RuntimeError("corrupted stream payload")):
        # Must not raise
        reconcile_workouts(uid, uid)


# AC2: exception is logged via logger.exception with user ID
def test_duration_curve_exception_logged_with_user_id(caplog):
    """When _update_duration_curves raises, logger.exception is called with the user ID."""
    _clear_registry()
    uid = _make_uid()
    sync_jobs.start(uid, "strava")

    session = _make_session()
    with caplog.at_level(logging.ERROR, logger="backend.services.reconcile"), \
         patch("backend.services.reconcile._Session", return_value=session), \
         patch("backend.services.reconcile.compute_run_metrics"), \
         patch("backend.services.reconcile._update_duration_curves",
               side_effect=ValueError("bad curve data")):
        reconcile_workouts(uid, uid)

    assert any(str(uid) in record.message for record in caplog.records), (
        f"Expected user ID {uid} in log records, got: {[r.message for r in caplog.records]}"
    )


# AC2: log level must be ERROR (logger.exception emits at ERROR)
def test_duration_curve_exception_logged_at_error_level(caplog):
    """logger.exception produces an ERROR-level record."""
    _clear_registry()
    uid = _make_uid()
    sync_jobs.start(uid, "strava")

    session = _make_session()
    with caplog.at_level(logging.ERROR, logger="backend.services.reconcile"), \
         patch("backend.services.reconcile._Session", return_value=session), \
         patch("backend.services.reconcile.compute_run_metrics"), \
         patch("backend.services.reconcile._update_duration_curves",
               side_effect=RuntimeError("broken")):
        reconcile_workouts(uid, uid)

    error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert error_records, "Expected at least one ERROR-level log record"


# AC3: mark_success can still be called after the exception (reconcile_workouts returns normally)
def test_mark_success_reachable_after_curve_exception():
    """Caller's mark_success is reachable because reconcile_workouts completes without re-raising."""
    _clear_registry()
    uid = _make_uid()
    sync_jobs.start(uid, "strava")

    session = _make_session()
    completed = []
    with patch("backend.services.reconcile._Session", return_value=session), \
         patch("backend.services.reconcile.compute_run_metrics"), \
         patch("backend.services.reconcile._update_duration_curves",
               side_effect=RuntimeError("stream error")):
        reconcile_workouts(uid, uid)
        completed.append(True)
        sync_jobs.mark_success(uid)

    assert completed, "reconcile_workouts raised unexpectedly"
    snap = sync_jobs.snapshot(uid)
    assert snap["status"] == "success"


# AC4: when _update_duration_curves succeeds, it is still called and mark_success reachable
def test_success_path_unchanged_when_no_exception():
    """Normal path: _update_duration_curves is called and reconcile_workouts returns."""
    _clear_registry()
    uid = _make_uid()
    sync_jobs.start(uid, "strava")

    session = _make_session()
    mock_curves = MagicMock()
    with patch("backend.services.reconcile._Session", return_value=session), \
         patch("backend.services.reconcile.compute_run_metrics"), \
         patch("backend.services.reconcile._update_duration_curves", mock_curves):
        reconcile_workouts(uid, uid)
        sync_jobs.mark_success(uid)

    mock_curves.assert_called_once()
    snap = sync_jobs.snapshot(uid)
    assert snap["status"] == "success"
