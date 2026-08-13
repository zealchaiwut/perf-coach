"""Tests for issue #1026: Sanitize error reason in performance endpoint error response.

Acceptance Criteria:
  AC1: The except Exception block in get_athlete_performance returns a JSON error
       response with a static, generic reason string ("unexpected server error")
       instead of str(exc).
  AC2: The full exception detail is still logged server-side via
       _performance_log.exception(...) so observability is unaffected.
  AC3: No raw exception message, SQLAlchemy error text, table names, column names,
       or connection details are present in any error response body.
  AC4: The response structure (status code, JSON shape) of the error response is
       otherwise unchanged — only the reason value is sanitized.
"""

import ast
import re
import textwrap
import unittest.mock as mock
from pathlib import Path

import pytest

MAIN_PY = Path(__file__).parent.parent / "backend" / "main.py"
_src = MAIN_PY.read_text()


# ---------------------------------------------------------------------------
# AC1 / AC3: Static source-level check — str(exc) must not appear in the
#            except block's JSONResponse content for get_athlete_performance
# ---------------------------------------------------------------------------

class TestSanitizedErrorReasonSourceCode:
    """AC1, AC3: The reason field in the error branch must not use str(exc)."""

    def _get_except_block_lines(self):
        """Return the lines of the except Exception block inside get_athlete_performance."""
        lines = _src.splitlines()
        in_func = False
        in_except = False
        collected = []
        for i, line in enumerate(lines):
            if "def get_athlete_performance" in line:
                in_func = True
            if in_func and re.match(r"\s+except Exception", line):
                in_except = True
            if in_except:
                collected.append(line)
                # Stop at the next top-level definition or decorator after collecting
                # at least a few lines
                if len(collected) > 3 and re.match(r"(def |class |@)", line.strip()):
                    collected.pop()
                    break
        return "\n".join(collected)

    def test_str_exc_not_used_as_reason_in_except_block(self):
        """AC1: str(exc) must not appear as the reason value in the error JSONResponse."""
        except_block = self._get_except_block_lines()
        assert except_block, "Could not find except Exception block in get_athlete_performance"
        assert "str(exc)" not in except_block, (
            "AC1 FAIL: str(exc) is still used as reason in the error response. "
            "Replace with a static string like 'unexpected server error'."
        )

    def test_generic_reason_string_present_in_except_block(self):
        """AC1: A generic/static reason string must be present in the except block."""
        except_block = self._get_except_block_lines()
        assert except_block, "Could not find except Exception block in get_athlete_performance"
        # Accept any literal string that doesn't reference the exception variable
        has_generic_reason = (
            '"unexpected server error"' in except_block
            or "'unexpected server error'" in except_block
        )
        assert has_generic_reason, (
            "AC1 FAIL: No generic reason string found in except block. "
            "Expected 'unexpected server error' (or similar) as a static literal."
        )

    def test_exception_logging_still_present_in_except_block(self):
        """AC2: _performance_log.exception(...) must still be called in the except block."""
        except_block = self._get_except_block_lines()
        assert "_performance_log.exception" in except_block, (
            "AC2 FAIL: _performance_log.exception() call is missing from the except block. "
            "Server-side observability must be preserved."
        )


# ---------------------------------------------------------------------------
# AC1 / AC3 / AC4: Runtime unit test — patch an internal call to raise,
#                  confirm the error response is sanitized
# ---------------------------------------------------------------------------

_FAKE_UUID = "12345678-1234-5678-1234-567812345678"


class TestPerformanceErrorResponseSanitized:
    """AC1, AC3, AC4: Runtime test confirming the error response is sanitized."""

    def _make_fake_user(self):
        import uuid
        from unittest.mock import MagicMock
        from backend.models import User
        fake_user = MagicMock(spec=User)
        fake_user.id = uuid.UUID(_FAKE_UUID)
        fake_user.name = "testuser"
        return fake_user

    def test_error_response_reason_is_generic(self):
        """AC1/AC3: When an unexpected exception occurs, reason must be a static string."""
        import json
        import uuid
        from unittest.mock import patch, MagicMock
        from fastapi.responses import JSONResponse
        from backend.main import get_athlete_performance

        fake_user = self._make_fake_user()

        sensitive_message = (
            "SQLSTATE[42P01]: relation 'strava_activities' does not exist — "
            "password=superSecret host=db.neon.tech column=athlete_id"
        )

        # Patch Session so we bypass DB access, then patch _check_needs_thresholds
        # to raise after the DB block (it's called after the Session context exits).
        with patch("backend.main.Session") as mock_session_cls, \
             patch("backend.main._summary_cache_get", return_value=None), \
             patch("backend.main._summary_cache_get_latest", return_value=None), \
             patch("backend.main._check_needs_thresholds", side_effect=Exception(sensitive_message)), \
             patch("backend.main._performance_log") as mock_log:

            # Make Session(engine).__enter__ return a mock that provides needed attrs
            mock_session = MagicMock()
            mock_session_cls.return_value.__enter__.return_value = mock_session
            mock_session.get.return_value = fake_user
            mock_session.query.return_value.filter.return_value.first.return_value = None
            mock_session.query.return_value.filter.return_value.order_by.return_value.all.return_value = []

            response = get_athlete_performance(_FAKE_UUID, user=fake_user)

        assert isinstance(response, JSONResponse), "Expected a JSONResponse"
        assert response.status_code == 500, f"Expected 500, got {response.status_code}"

        body = json.loads(response.body)

        # AC3: raw exception message must not appear in the response body
        body_str = json.dumps(body)
        assert sensitive_message not in body_str, (
            "AC3 FAIL: Raw exception message leaked into the response body."
        )
        assert "strava_activities" not in body_str, (
            "AC3 FAIL: Table name 'strava_activities' leaked into the response body."
        )
        assert "superSecret" not in body_str, (
            "AC3 FAIL: Sensitive connection detail leaked into the response body."
        )

        # AC1: reason must be the generic string
        assert body.get("reason") == "unexpected server error", (
            f"AC1 FAIL: Expected reason='unexpected server error', got: {body.get('reason')!r}"
        )

        # AC4: structure (state, status code) must be unchanged
        assert body.get("state") == "error", (
            f"AC4 FAIL: Expected state='error', got: {body.get('state')!r}"
        )
        assert "endurance" in body, "AC4 FAIL: 'endurance' key missing from error response"
        assert "speed" in body, "AC4 FAIL: 'speed' key missing from error response"
        assert "generated_at" in body, "AC4 FAIL: 'generated_at' key missing from error response"

    def test_exception_is_logged_server_side(self):
        """AC2: The full exception must still be logged via _performance_log.exception."""
        from unittest.mock import patch, MagicMock
        from backend.main import get_athlete_performance

        fake_user = self._make_fake_user()

        with patch("backend.main.Session") as mock_session_cls, \
             patch("backend.main._summary_cache_get", return_value=None), \
             patch("backend.main._summary_cache_get_latest", return_value=None), \
             patch("backend.main._check_needs_thresholds", side_effect=Exception("boom")), \
             patch("backend.main._performance_log") as mock_log:

            mock_session = MagicMock()
            mock_session_cls.return_value.__enter__.return_value = mock_session
            mock_session.get.return_value = fake_user
            mock_session.query.return_value.filter.return_value.first.return_value = None
            mock_session.query.return_value.filter.return_value.order_by.return_value.all.return_value = []

            get_athlete_performance(_FAKE_UUID, user=fake_user)

        mock_log.exception.assert_called(), (
            "AC2 FAIL: _performance_log.exception() was not called after the exception."
        )
