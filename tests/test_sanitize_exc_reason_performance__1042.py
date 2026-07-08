"""Tests for issue #1042: Avoid leaking raw exception messages in performance
endpoint error response.

Acceptance Criteria (from issue #1042):
  AC1: The performance endpoint error response never includes raw exception text
       in the `reason` field; the field always contains a fixed generic string
       ("unexpected server error") when state=error.
  AC2: The full exception detail (stack trace / message) continues to be logged
       server-side at the existing log call, unchanged.
  AC3: The `reason` field is never empty or None in an error response — the
       generic fallback string is always present even if the exception message
       itself was empty.
  AC4: No other fields in the error response body are modified by this change
       (shape is preserved).
  AC5: The fix is scoped to the except Exception block in get_athlete_performance;
       no other error-response sites are unintentionally altered.
"""

import json
import re
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

MAIN_PY = Path(__file__).parent.parent / "backend" / "main.py"
_src = MAIN_PY.read_text()

_FAKE_UUID = "12345678-1234-5678-1234-567812345678"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_fake_user():
    from backend.models import User
    fake_user = MagicMock(spec=User)
    fake_user.id = uuid.UUID(_FAKE_UUID)
    fake_user.name = "testuser"
    return fake_user


def _get_except_block_lines():
    """Return source lines of the except Exception block inside get_athlete_performance."""
    lines = _src.splitlines()
    in_func = False
    in_except = False
    collected = []
    for line in lines:
        if "def get_athlete_performance" in line:
            in_func = True
        if in_func and re.match(r"\s+except Exception", line):
            in_except = True
        if in_except:
            collected.append(line)
            if len(collected) > 3 and re.match(r"(def |class |@)", line.strip()):
                collected.pop()
                break
    return "\n".join(collected)


def _invoke_performance_with_exception(exc_to_raise):
    """Invoke get_athlete_performance with a patched internal call that raises exc_to_raise."""
    from backend.main import get_athlete_performance

    fake_user = _make_fake_user()

    with patch("backend.main.Session") as mock_session_cls, \
         patch("backend.main._summary_cache_get", return_value=None), \
         patch("backend.main._check_needs_thresholds", side_effect=exc_to_raise), \
         patch("backend.main._performance_log") as mock_log:

        mock_session = MagicMock()
        mock_session_cls.return_value.__enter__.return_value = mock_session
        mock_session.get.return_value = fake_user
        mock_session.query.return_value.filter.return_value.first.return_value = None
        mock_session.query.return_value.filter.return_value.order_by.return_value.all.return_value = []

        response = get_athlete_performance(_FAKE_UUID, user=fake_user)
        return response, mock_log


# ---------------------------------------------------------------------------
# AC1: Raw exception text must not appear in the reason field
# ---------------------------------------------------------------------------

class TestAC1NoRawExceptionInReason:
    def test_reason_is_generic_string_not_raw_exception(self):
        """AC1: reason must be 'unexpected server error', not the exception's str()."""
        raw_msg = "SQLAlchemy error: relation 'workouts' does not exist"
        response, _ = _invoke_performance_with_exception(Exception(raw_msg))

        body = json.loads(response.body)
        assert body.get("reason") != raw_msg, (
            "AC1 FAIL: Raw exception message leaked into reason field."
        )
        assert body.get("reason") == "unexpected server error", (
            f"AC1 FAIL: reason should be 'unexpected server error', got: {body.get('reason')!r}"
        )

    def test_sensitive_sql_details_not_in_reason(self):
        """AC1: SQL/connection details must not appear in the reason field."""
        raw_msg = (
            "psycopg2.errors.UndefinedTable: table 'daily_metrics' not found; "
            "host=db-secret.neon.tech password=hunter2"
        )
        response, _ = _invoke_performance_with_exception(Exception(raw_msg))

        body = json.loads(response.body)
        reason = body.get("reason", "")
        assert "daily_metrics" not in reason, "AC1 FAIL: Table name leaked into reason."
        assert "hunter2" not in reason, "AC1 FAIL: Password leaked into reason."
        assert reason == "unexpected server error"

    def test_source_code_has_no_str_exc_in_except_block(self):
        """AC1/AC5: str(exc) must not appear in the except Exception block."""
        except_block = _get_except_block_lines()
        assert except_block, "Could not locate except Exception block in get_athlete_performance"
        assert "str(exc)" not in except_block, (
            "AC1 FAIL: str(exc) is still present in the except block — it leaks raw exception text."
        )

    def test_source_code_has_generic_reason_literal(self):
        """AC1: A static generic reason string must be present in the except block."""
        except_block = _get_except_block_lines()
        assert (
            '"unexpected server error"' in except_block
            or "'unexpected server error'" in except_block
        ), (
            "AC1 FAIL: Static reason literal 'unexpected server error' not found in except block."
        )


# ---------------------------------------------------------------------------
# AC2: Server-side logging must still capture the full exception
# ---------------------------------------------------------------------------

class TestAC2ServerSideLogging:
    def test_exception_is_logged_server_side(self):
        """AC2: _performance_log.exception() must be called, preserving server observability."""
        response, mock_log = _invoke_performance_with_exception(Exception("internal detail"))
        mock_log.exception.assert_called(), (
            "AC2 FAIL: _performance_log.exception() was not called — "
            "server-side observability is broken."
        )

    def test_log_call_present_in_source(self):
        """AC2: _performance_log.exception() must appear in the except block source."""
        except_block = _get_except_block_lines()
        assert "_performance_log.exception" in except_block, (
            "AC2 FAIL: _performance_log.exception() call is absent from the except block."
        )


# ---------------------------------------------------------------------------
# AC3: reason is never empty or None — even when exception message is empty
# ---------------------------------------------------------------------------

class TestAC3ReasonNeverEmpty:
    def test_reason_not_empty_when_exception_message_is_empty(self):
        """AC3: Empty exception message must still produce the non-empty generic string."""
        response, _ = _invoke_performance_with_exception(Exception(""))

        body = json.loads(response.body)
        reason = body.get("reason")
        assert reason, "AC3 FAIL: reason is falsy (empty or None) for empty exception message."
        assert reason == "unexpected server error", (
            f"AC3 FAIL: Expected 'unexpected server error', got: {reason!r}"
        )

    def test_reason_not_none_when_exception_message_is_empty(self):
        """AC3: reason must not be None when exception message is empty."""
        response, _ = _invoke_performance_with_exception(Exception(""))

        body = json.loads(response.body)
        assert body.get("reason") is not None, (
            "AC3 FAIL: reason is None for an empty-message exception."
        )

    def test_reason_not_empty_when_exception_message_is_whitespace(self):
        """AC3: Whitespace-only exception message must not result in empty reason."""
        response, _ = _invoke_performance_with_exception(Exception("   "))

        body = json.loads(response.body)
        reason = body.get("reason", "")
        assert reason.strip(), "AC3 FAIL: reason is blank for a whitespace-only exception message."


# ---------------------------------------------------------------------------
# AC4: Response shape is preserved — no fields added or removed
# ---------------------------------------------------------------------------

class TestAC4ResponseShapePreserved:
    def test_error_response_has_required_top_level_keys(self):
        """AC4: state, endurance, speed, generated_at must all be present in error response."""
        response, _ = _invoke_performance_with_exception(Exception("boom"))

        assert response.status_code == 500, f"Expected HTTP 500, got {response.status_code}"
        body = json.loads(response.body)

        for key in ("state", "endurance", "speed", "generated_at", "reason"):
            assert key in body, f"AC4 FAIL: key '{key}' missing from error response body."

    def test_error_state_field_value(self):
        """AC4: state must be 'error' in the error response."""
        response, _ = _invoke_performance_with_exception(Exception("boom"))

        body = json.loads(response.body)
        assert body.get("state") == "error", (
            f"AC4 FAIL: state should be 'error', got: {body.get('state')!r}"
        )

    def test_endurance_and_speed_are_null_in_error_response(self):
        """AC4: endurance and speed must be null (None) when state=error."""
        response, _ = _invoke_performance_with_exception(Exception("boom"))

        body = json.loads(response.body)
        assert body.get("endurance") is None, (
            "AC4 FAIL: endurance should be null in error response."
        )
        assert body.get("speed") is None, (
            "AC4 FAIL: speed should be null in error response."
        )


# ---------------------------------------------------------------------------
# AC5: Scoping — other error-response sites not unintentionally altered
# ---------------------------------------------------------------------------

class TestAC5FixScoped:
    def test_only_get_athlete_performance_except_block_uses_generic_reason(self):
        """AC5: The static reason string must appear inside get_athlete_performance, not scattered.

        This test ensures the fix is localized and didn't accidentally insert the
        generic reason string into unrelated endpoints.
        """
        # Find all occurrences of 'unexpected server error' in main.py
        occurrences = [
            (i + 1, line)
            for i, line in enumerate(_src.splitlines())
            if "unexpected server error" in line
        ]
        # Confirm at least one occurrence exists (the fix)
        assert occurrences, "AC5 FAIL: 'unexpected server error' literal not found in main.py"

        # Each occurrence must be near get_athlete_performance, not in an unrelated
        # function.  We collect function names by scanning backwards from each hit.
        lines = _src.splitlines()
        for lineno, _ in occurrences:
            # Walk back to find the enclosing def
            enclosing_def = None
            for i in range(lineno - 1, -1, -1):
                m = re.match(r"(def |async def )(\w+)", lines[i])
                if m:
                    enclosing_def = m.group(2)
                    break
            # It's acceptable if the string also appears in a helper (like
            # _build_performance_response's docstring), but it must not show up
            # in a completely unrelated function.
            unrelated = enclosing_def and enclosing_def not in (
                "get_athlete_performance",
                "_build_performance_response",
            )
            # We only flag if it's not a docstring/comment line — check for `reason=`
            is_reason_assignment = "reason=" in lines[lineno - 1]
            if is_reason_assignment and unrelated:
                pytest.fail(
                    f"AC5 FAIL: 'unexpected server error' reason assignment found in "
                    f"unrelated function '{enclosing_def}' at line {lineno}."
                )
