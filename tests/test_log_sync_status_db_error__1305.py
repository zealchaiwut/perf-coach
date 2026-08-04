"""
Tests for issue #1305: log (not silence) DB errors in get_sync_status worker fallback.

AC: When the worker_job_runs DB query in get_sync_status raises an exception,
    the exception must be logged as a WARNING (not silently swallowed with `pass`),
    and the endpoint must still return {"status": "idle"} to the caller.
"""
import logging
import pytest
from unittest.mock import patch, MagicMock


def test_db_error_is_logged_as_warning(caplog):
    """AC: exception from worker_job_runs query is logged at WARNING level."""
    import importlib
    import backend.main as main_mod

    fake_user = MagicMock()
    fake_user.id = "test-user-1305"

    # Patch _sync_jobs.snapshot to return None (no in-process job)
    with patch.object(main_mod._sync_jobs, "snapshot", return_value=None):
        # Patch Session to raise on __enter__
        with patch("backend.main.Session") as mock_session_cls:
            mock_session_cls.side_effect = Exception("DB connection failed")

            # Patch job_queue to return None (no pending queue entry)
            with patch("backend.services.job_queue.pending_for_user", return_value=None):
                with caplog.at_level(logging.WARNING, logger="backend.main"):
                    import asyncio
                    response = asyncio.get_event_loop().run_until_complete(
                        main_mod.get_sync_status(user=fake_user)
                    )

    # The warning must have been emitted
    warning_messages = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert any("worker_job_runs" in msg for msg in warning_messages), (
        f"Expected a WARNING mentioning 'worker_job_runs', got: {warning_messages}"
    )


def test_db_error_still_returns_idle(caplog):
    """AC: endpoint returns {'status': 'idle'} even when worker_job_runs query fails."""
    import backend.main as main_mod
    import json

    fake_user = MagicMock()
    fake_user.id = "test-user-1305"

    with patch.object(main_mod._sync_jobs, "snapshot", return_value=None):
        with patch("backend.main.Session") as mock_session_cls:
            mock_session_cls.side_effect = Exception("DB connection failed")

            with patch("backend.services.job_queue.pending_for_user", return_value=None):
                with caplog.at_level(logging.WARNING, logger="backend.main"):
                    import asyncio
                    response = asyncio.get_event_loop().run_until_complete(
                        main_mod.get_sync_status(user=fake_user)
                    )

    body = json.loads(response.body)
    assert body.get("status") == "idle", f"Expected 'idle', got: {body}"
