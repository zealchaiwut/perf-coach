"""Tests for issue #1415: Refresh weekly fuel card after sync-deficit.

AC: After a successful sync-deficit POST, the handler must call both
_fuelLoadToday() and _fuelLoadWeek() so the weekly budget card reflects
the updated deficit without requiring a page reload.
"""
import pathlib
import re

JS = pathlib.Path("frontend/js/fuel.js").read_text()


class TestAC_WeeklyFuelRefreshedAfterSyncDeficit:
    """sync-deficit handler refreshes both today and weekly cards."""

    def test_sync_handler_calls_fuel_load_week(self):
        """fuel.js sync-deficit handler must call _fuelLoadWeek()."""
        assert "_fuelLoadWeek()" in JS, (
            "fuel.js sync-deficit handler must call _fuelLoadWeek() to "
            "refresh the weekly budget card after sync"
        )

    def test_fuel_load_week_called_after_fuel_load_today_in_sync_handler(self):
        """_fuelLoadWeek() must appear after _fuelLoadToday() within the sync handler block."""
        # Locate the sync-deficit handler function body
        match = re.search(
            r"sync-deficit.*?btn\.disabled\s*=\s*false",
            JS,
            re.DOTALL,
        )
        assert match, "Could not locate sync-deficit handler block in fuel.js"
        block = match.group(0)

        today_pos = block.find("_fuelLoadToday()")
        week_pos = block.find("_fuelLoadWeek()")

        assert today_pos != -1, "_fuelLoadToday() not found in sync-deficit handler"
        assert week_pos != -1, "_fuelLoadWeek() not found in sync-deficit handler"
        assert week_pos > today_pos, (
            "_fuelLoadWeek() must be called after _fuelLoadToday() in the sync-deficit handler"
        )
