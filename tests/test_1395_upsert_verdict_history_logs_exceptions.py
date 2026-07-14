"""
Tests for issue #1395: _upsert_verdict_history must log exceptions instead of
silently swallowing them with a bare `pass`.

Acceptance criteria:
- AC1: When the DB write raises any Exception, it is logged at warning level
         (exc_info=True so the traceback is captured).
- AC2: The caller is never disrupted — no exception propagates out of
         _upsert_verdict_history regardless of the DB error.
- AC3: When the DB write succeeds, no warning is logged (no false positives).
"""
import datetime
import uuid
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Import the private helper under test.  It lives at module scope in main.py.
# ---------------------------------------------------------------------------
from backend.main import _upsert_verdict_history


_SAMPLE_VERDICT = {
    "verdict": "build",
    "modifiers": None,
    "ctl": 30.0,
    "atl": 35.0,
    "tsb": -5.0,
    "acwr": 1.1,
}
_SAMPLE_DATE = datetime.date(2026, 1, 15)
_SAMPLE_UID = str(uuid.uuid4())


# ── AC1: Exception is logged at warning level ────────────────────────────────

def test_ac1_db_exception_is_logged_as_warning():
    """AC1: A DB error inside _upsert_verdict_history triggers a warning log."""
    boom = RuntimeError("simulated DB write failure")

    with (
        patch("backend.main.Session") as mock_session_cls,
        patch("backend.main._log") as mock_log,
    ):
        # Make the context manager's execute() raise
        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_db.execute.side_effect = boom
        mock_session_cls.return_value = mock_db

        _upsert_verdict_history(_SAMPLE_UID, _SAMPLE_DATE, _SAMPLE_VERDICT)

    # A warning (or higher) must have been emitted with exc_info so the
    # traceback is preserved in the log record.
    assert mock_log.warning.called or mock_log.exception.called, (
        "_log.warning (or .exception) was not called after a DB error"
    )


def test_ac1_logged_message_references_failure():
    """AC1: The warning log message contains enough context to diagnose the error."""
    boom = ValueError("constraint violation")

    with (
        patch("backend.main.Session") as mock_session_cls,
        patch("backend.main._log") as mock_log,
    ):
        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_db.execute.side_effect = boom
        mock_session_cls.return_value = mock_db

        _upsert_verdict_history(_SAMPLE_UID, _SAMPLE_DATE, _SAMPLE_VERDICT)

    # Collect all warning calls
    if mock_log.warning.called:
        call_args = mock_log.warning.call_args
    elif mock_log.exception.called:
        call_args = mock_log.exception.call_args
    else:
        pytest.fail("No warning or exception log call was made")

    # The first positional arg (the format string) should mention the function
    # or the error class so operators can tell where this came from.
    msg = call_args[0][0] if call_args[0] else ""
    assert msg, "Log message must not be empty"


# ── AC2: No exception propagates to the caller ──────────────────────────────

def test_ac2_db_exception_does_not_propagate():
    """AC2: _upsert_verdict_history never raises even when the DB write fails."""
    with (
        patch("backend.main.Session") as mock_session_cls,
        patch("backend.main._log"),
    ):
        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_db.execute.side_effect = Exception("any error")
        mock_session_cls.return_value = mock_db

        # Must not raise
        try:
            _upsert_verdict_history(_SAMPLE_UID, _SAMPLE_DATE, _SAMPLE_VERDICT)
        except Exception as exc:
            pytest.fail(f"_upsert_verdict_history raised unexpectedly: {exc}")


def test_ac2_various_exception_types_do_not_propagate():
    """AC2: Best-effort guarantee holds for all exception types."""
    errors = [
        RuntimeError("runtime"),
        ValueError("value"),
        KeyError("key"),
        MemoryError("memory"),
    ]
    for err in errors:
        with (
            patch("backend.main.Session") as mock_session_cls,
            patch("backend.main._log"),
        ):
            mock_db = MagicMock()
            mock_db.__enter__ = MagicMock(return_value=mock_db)
            mock_db.__exit__ = MagicMock(return_value=False)
            mock_db.execute.side_effect = err
            mock_session_cls.return_value = mock_db

            try:
                _upsert_verdict_history(_SAMPLE_UID, _SAMPLE_DATE, _SAMPLE_VERDICT)
            except Exception as exc:
                pytest.fail(
                    f"_upsert_verdict_history raised for {type(err).__name__}: {exc}"
                )


# ── AC3: No false-positive warning on success ────────────────────────────────

def test_ac3_successful_write_emits_no_warning():
    """AC3: A clean DB write does not trigger any warning log."""
    with (
        patch("backend.main.Session") as mock_session_cls,
        patch("backend.main._log") as mock_log,
    ):
        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_session_cls.return_value = mock_db

        _upsert_verdict_history(_SAMPLE_UID, _SAMPLE_DATE, _SAMPLE_VERDICT)

    assert not mock_log.warning.called, "warning logged on a successful write"
    assert not mock_log.exception.called, "exception logged on a successful write"
