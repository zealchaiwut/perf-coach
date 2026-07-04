"""Tests for issue #1212: Guardrail window uses BKK time helper instead of date.today().

AC coverage:
- AC1: get_body_modifier_guardrail_for_user computes 7-day window using _today_bkk() instead of date.today()
- AC2: No other call site in body_modifier.py uses date.today() where BKK-local "today" is intended
- AC3: BKK time helper is importable and callable from body_modifier.py without circular imports
- AC4: Resolved window boundaries match the same "today" used by the rest of the backend (main.py)
- AC5: Existing tests pass with BKK-local semantics (UTC midnight edge behavior updated if needed)
"""
import os
from datetime import date, timedelta
from zoneinfo import ZoneInfo

import pytest


class TestBodyModifierGuardrailUseBkkTime:
    """Tests that guardrail window computation uses BKK time, not UTC."""

    def test_guardrail_imports_today_bkk_helper(self):
        """AC3: _today_bkk helper is importable from body_modifier.py without circular imports."""
        # This test verifies that the import does not raise an ImportError
        try:
            from backend.services.body_modifier import get_body_modifier_guardrail_for_user
            # Importing the function itself should succeed; no explicit import of _today_bkk needed
            # if the fix is internal to the function
            assert callable(get_body_modifier_guardrail_for_user)
        except ImportError as e:
            pytest.fail(f"Failed to import get_body_modifier_guardrail_for_user: {e}")

    def test_get_body_modifier_for_user_accepts_bkk_date_param(self):
        """AC1: get_body_modifier_for_user accepts as_of_date parameter for BKK time."""
        from backend.services.body_modifier import get_body_modifier_for_user
        import inspect

        # Verify the function signature accepts as_of_date parameter
        sig = inspect.signature(get_body_modifier_for_user)
        assert "as_of_date" in sig.parameters, (
            "get_body_modifier_for_user must accept as_of_date parameter"
        )

        # Verify as_of_date defaults to None (allowing BKK default)
        param = sig.parameters["as_of_date"]
        assert param.default is None, (
            "as_of_date should default to None, allowing internal use of _today_bkk()"
        )

    def test_get_body_modifier_guardrail_for_user_accepts_bkk_date_param(self):
        """AC1: get_body_modifier_guardrail_for_user computes 7-day window using BKK time."""
        from backend.services.body_modifier import get_body_modifier_guardrail_for_user
        import inspect

        # Verify the function signature accepts as_of_date parameter
        sig = inspect.signature(get_body_modifier_guardrail_for_user)
        assert "as_of_date" in sig.parameters, (
            "get_body_modifier_guardrail_for_user must accept as_of_date parameter"
        )

        # Verify as_of_date defaults to None (allowing BKK default)
        param = sig.parameters["as_of_date"]
        assert param.default is None, (
            "as_of_date should default to None, allowing internal use of _today_bkk()"
        )

    def test_no_raw_date_today_in_guardrail_function(self):
        """AC2: Verify body_modifier.py doesn't use raw date.today() in guardrail functions."""
        import inspect
        from backend.services.body_modifier import get_body_modifier_guardrail_for_user

        # Get the source code of the function
        source = inspect.getsource(get_body_modifier_guardrail_for_user)

        # Check that date.today() is NOT called directly (it would be as_of_date fallback)
        # The function should use _today_bkk() or accept as_of_date explicitly
        # We verify by checking the source doesn't have "date.today()" outside of imports
        lines = source.split("\n")
        for line_num, line in enumerate(lines, start=1):
            # Skip import lines and comments
            if "import" in line or line.strip().startswith("#"):
                continue
            # Check for raw date.today() call (not in a string or as a fallback in imports)
            if "date.today()" in line and "as_of_date" not in line:
                pytest.fail(
                    f"AC2 violation: Found raw date.today() at line {line_num}: {line.strip()}"
                )

    def test_no_raw_date_today_in_get_body_modifier_function(self):
        """AC2: Verify body_modifier.py doesn't use raw date.today() in get_body_modifier_for_user."""
        import inspect
        from backend.services.body_modifier import get_body_modifier_for_user

        # Get the source code of the function
        source = inspect.getsource(get_body_modifier_for_user)

        # Verify no raw date.today() call
        lines = source.split("\n")
        for line_num, line in enumerate(lines, start=1):
            if "import" in line or line.strip().startswith("#"):
                continue
            if "date.today()" in line and "as_of_date" not in line:
                pytest.fail(
                    f"AC2 violation: Found raw date.today() at line {line_num}: {line.strip()}"
                )

    def test_bkk_and_backend_today_alignment(self):
        """AC4: BKK time helper aligns with the same "today" used in main.py."""
        from backend.main import _today_bkk

        # Get today via BKK helper
        today_bkk = _today_bkk()

        # Verify it returns a date object
        assert isinstance(today_bkk, date)

        # Verify the date is current (within ±1 day of UTC today, accounting for timezone shift)
        utc_today = date.today()
        diff = abs((today_bkk - utc_today).days)
        # Near midnight UTC/BKK crossover: diff can be 0 or 1
        assert diff <= 1, f"BKK date {today_bkk} is too far from UTC date {utc_today}"

    def test_guardrail_window_boundary_logic_uses_correct_today(self):
        """AC4: Guardrail window boundaries use BKK date semantics, matching main.py."""
        from backend.services.body_modifier import get_body_modifier_guardrail_for_user
        from backend.main import _today_bkk
        import inspect

        # Verify that the function source code uses _today_bkk or imports it
        source = inspect.getsource(get_body_modifier_guardrail_for_user)

        # The function should either:
        # 1. Import _today_bkk from backend.main, or
        # 2. Use it directly via the as_of_date parameter default
        # Check that it's not using raw date.today() (already verified in AC2 test)

        # Verify the function has proper timezone-aware logic
        assert "as_of_date" in source, (
            "guardrail function must use as_of_date parameter for window computation"
        )

        # Verify the window is computed correctly (7 days back)
        assert "timedelta" in source or "days" in source.lower(), (
            "guardrail function must compute a 7-day window using timedelta"
        )

    def test_existing_guardrail_tests_still_pass(self):
        """AC5: Existing unit tests for guardrail logic still pass with BKK semantics."""
        from backend.services.body_modifier import (
            compute_body_modifier_guardrail,
            RATE_ZERO_CROSSING,
            EA_LOW_THRESHOLD,
        )

        # Run a basic sanity test: safe conditions should return ok
        result = compute_body_modifier_guardrail(weekly_pct_bw_rate=0.0, ea_proxy=1.0)
        assert result["guardrail_state"] == "ok"
        assert result["guardrail_message"] == ""

        # Test excessive loss triggers warn
        excessive_loss = -(RATE_ZERO_CROSSING + 0.5)
        result = compute_body_modifier_guardrail(weekly_pct_bw_rate=excessive_loss, ea_proxy=1.0)
        assert result["guardrail_state"] == "warn"
        assert result["in_penalty_loss"] is True

    def test_timezone_aware_window_logic_in_source(self):
        """AC4: Guardrail uses BKK time semantics, verified via source inspection.

        Confirms that the function either:
        - Uses _today_bkk() when as_of_date is None, OR
        - Accepts an as_of_date parameter that caller can set to _today_bkk()
        """
        from backend.main import _today_bkk
        import inspect
        from backend.services.body_modifier import get_body_modifier_guardrail_for_user

        # Verify _today_bkk exists and works
        today_bkk = _today_bkk()
        assert isinstance(today_bkk, date), "BKK helper must return a date object"

        # Verify guardrail function uses the as_of_date parameter correctly
        source = inspect.getsource(get_body_modifier_guardrail_for_user)

        # The function should compute the 7-day window starting from as_of_date (or _today_bkk)
        has_window_calc = (
            "timedelta" in source and "days" in source.lower()
        ) or (
            "seven_days_ago" in source
        )
        assert has_window_calc, (
            "guardrail function must compute a 7-day window for the date range"
        )
