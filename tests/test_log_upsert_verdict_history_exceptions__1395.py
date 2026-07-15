"""Tests for issue #1395: log exceptions in _upsert_verdict_history instead of bare pass (runs against UAT)"""
import os
import pytest
import logging
from unittest.mock import patch, MagicMock
import sys

# Add the backend module to path so we can import main
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from main import _upsert_verdict_history


@pytest.fixture
def mock_engine():
    """Mock the database engine for testing exception logging."""
    return MagicMock()


@pytest.fixture
def caplog_fixture(caplog):
    """Fixture to capture log output."""
    caplog.set_level(logging.WARNING)
    return caplog


def test_log_upsert_verdict_history_exceptions__logs_exception_on_write_failure(mock_engine, caplog_fixture):
    """AC: _upsert_verdict_history logs exceptions instead of silently swallowing them"""
    # Simulate a database write failure by making Session context manager raise an exception
    with patch("main.engine", mock_engine), \
         patch("main.Session") as mock_session_class, \
         patch("main._log") as mock_logger:

        # Configure the mock to raise an exception when used
        mock_session_instance = MagicMock()
        mock_session_instance.execute.side_effect = ValueError("Database constraint violation")
        mock_session_class.return_value.__enter__.return_value = mock_session_instance

        # Call the function with test data
        _upsert_verdict_history(
            user_id=999,
            verdict_date="2026-07-14",
            verdict_result={"verdict": "READY_FOR_UAT", "modifiers": None, "ctl": 10.5, "atl": 5.0, "tsb": 5.5, "acwr": 2.1},
            readiness_score=75.0
        )

        # Verify that the logger was called with warning level
        mock_logger.warning.assert_called_once()
        call_args = mock_logger.warning.call_args
        assert "verdict_history write failed" in str(call_args)
        assert call_args[1].get("exc_info") is True


def test_log_upsert_verdict_history_exceptions__continues_on_exception(mock_engine, caplog_fixture):
    """AC: _upsert_verdict_history continues execution after logging (doesn't raise)"""
    with patch("main.engine", mock_engine), \
         patch("main.Session") as mock_session_class, \
         patch("main._log"):

        # Configure the mock to raise an exception when used
        mock_session_instance = MagicMock()
        mock_session_instance.execute.side_effect = RuntimeError("Connection timeout")
        mock_session_class.return_value.__enter__.return_value = mock_session_instance

        # This should NOT raise an exception — it should catch and log it
        try:
            _upsert_verdict_history(
                user_id=999,
                verdict_date="2026-07-14",
                verdict_result={"verdict": "NEEDS_FIXES", "modifiers": None, "ctl": 8.0, "atl": 4.5, "tsb": 3.5, "acwr": 1.8},
                readiness_score=60.0
            )
            # If we get here, no exception was raised — test passes
            success = True
        except Exception as e:
            success = False
            pytest.fail(f"Function raised exception instead of catching: {e}")

        assert success, "Function should complete without raising"


def test_log_upsert_verdict_history_exceptions__logs_at_warning_level(mock_engine, caplog_fixture):
    """AC: The exception is logged at warning level (not debug)"""
    with patch("main.engine", mock_engine), \
         patch("main.Session") as mock_session_class, \
         patch("main._log") as mock_logger:

        # Configure the mock to raise an exception when used
        mock_session_instance = MagicMock()
        mock_session_instance.execute.side_effect = IOError("Disk full")
        mock_session_class.return_value.__enter__.return_value = mock_session_instance

        _upsert_verdict_history(
            user_id=999,
            verdict_date="2026-07-14",
            verdict_result={"verdict": "HOLD", "modifiers": None, "ctl": 12.0, "atl": 6.0, "tsb": 6.0, "acwr": 2.0},
            readiness_score=70.0
        )

        # Verify warning level was used
        mock_logger.warning.assert_called_once()
        # Verify it was NOT called with error or debug
        mock_logger.error.assert_not_called()
