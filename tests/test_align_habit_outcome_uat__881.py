"""UAT tests for align_habit_and_outcome integration (issue #881).

These tests verify the function's behavior when a thin caller fetches
real or representative data and passes it in.
"""

import pytest
from backend.services.habit_outcome_alignment import align_habit_and_outcome


# ---------------------------------------------------------------------------
# UAT Step 1: Zero lag exact-match pairing
# ---------------------------------------------------------------------------

def test_uat_step_1_zero_lag_exact_match():
    """UAT Step 1: Supply habit_logs Mon-Fri, outcome_series Mon-Sat, lag=0.

    Expected: Five pairs returned, each matching a weekday habit to the
    same-day outcome; Saturday outcome unused; debug shows 5 habit days in,
    6 outcome days in, 5 pairs after drop; reason is empty.
    """
    habit_logs = {
        "2025-06-02": True,   # Monday
        "2025-06-03": False,  # Tuesday
        "2025-06-04": True,   # Wednesday
        "2025-06-05": False,  # Thursday
        "2025-06-06": True,   # Friday
    }
    outcome_series = {
        "2025-06-02": 80.0,   # Monday
        "2025-06-03": 75.0,   # Tuesday
        "2025-06-04": 85.0,   # Wednesday
        "2025-06-05": 70.0,   # Thursday
        "2025-06-06": 90.0,   # Friday
        "2025-06-07": 95.0,   # Saturday
    }

    pairs, debug = align_habit_and_outcome(habit_logs, outcome_series, lag_days=0)

    # Five pairs returned
    assert len(pairs) == 5, "Should have 5 pairs for 5 matching habit/outcome dates"

    # Each pair matches habit date to same-day outcome date
    for pair in pairs:
        assert pair["habit_date"] == pair["outcome_date"], \
            "With lag=0, habit_date should equal outcome_date"
        assert pair["habit_value"] in [True, False], "habit_value must be boolean"
        assert isinstance(pair["outcome_value"], (int, float)), "outcome_value must be numeric"

    # Saturday outcome is not used (no habit on Saturday)
    outcome_dates = {p["outcome_date"] for p in pairs}
    assert "2025-06-07" not in outcome_dates, "Saturday outcome should not be paired (no Saturday habit)"

    # Debug object correct
    assert debug["total_habit_days"] == 5
    assert debug["total_outcome_days"] == 6
    assert debug["lag_days"] == 0
    assert debug["pairs_after_drop"] == 5
    assert debug["reason"] == "", "Reason should be empty for valid input with pairs"


# ---------------------------------------------------------------------------
# UAT Step 2: Positive lag (lag_days=1) shifted pairing
# ---------------------------------------------------------------------------

def test_uat_step_2_lag_one_shifted_pairing():
    """UAT Step 2: Same inputs as step 1, but lag_days=1.

    Expected: Each habit day matched to the following calendar day's outcome;
    Friday habit matched to Saturday outcome; debug shows correct input counts
    and pair count after dropping; reason is empty.
    """
    habit_logs = {
        "2025-06-02": True,   # Monday
        "2025-06-03": False,  # Tuesday
        "2025-06-04": True,   # Wednesday
        "2025-06-05": False,  # Thursday
        "2025-06-06": True,   # Friday
    }
    outcome_series = {
        "2025-06-02": 80.0,   # Monday
        "2025-06-03": 75.0,   # Tuesday
        "2025-06-04": 85.0,   # Wednesday
        "2025-06-05": 70.0,   # Thursday
        "2025-06-06": 90.0,   # Friday
        "2025-06-07": 95.0,   # Saturday
    }

    pairs, debug = align_habit_and_outcome(habit_logs, outcome_series, lag_days=1)

    # All 5 habit days have a +1-day outcome in the series
    assert len(pairs) == 5, "All 5 habits should find a +1-day outcome"

    # Verify the shift: each habit_date + 1 day = outcome_date
    by_habit = {p["habit_date"]: p for p in pairs}
    assert by_habit["2025-06-02"]["outcome_date"] == "2025-06-03", "Monday → Tuesday"
    assert by_habit["2025-06-04"]["outcome_date"] == "2025-06-05", "Wednesday → Thursday"
    assert by_habit["2025-06-06"]["outcome_date"] == "2025-06-07", "Friday → Saturday"

    # Debug object correct
    assert debug["total_habit_days"] == 5
    assert debug["total_outcome_days"] == 6
    assert debug["lag_days"] == 1
    assert debug["pairs_after_drop"] == 5, "All habits find their +1-day outcome"
    assert debug["reason"] == "", "Reason should be empty for valid input with pairs"


# ---------------------------------------------------------------------------
# UAT Step 3: Empty habit_logs
# ---------------------------------------------------------------------------

def test_uat_step_3_empty_habit_logs():
    """UAT Step 3: Empty habit_logs dict, populated outcome_series.

    Expected: Empty pairs list; debug reason is non-empty and mentions
    missing habit logs; no exception raised.
    """
    habit_logs = {}
    outcome_series = {
        "2025-06-02": 80.0,
        "2025-06-03": 75.0,
        "2025-06-04": 85.0,
        "2025-06-05": 70.0,
        "2025-06-06": 90.0,
        "2025-06-07": 95.0,
    }

    pairs, debug = align_habit_and_outcome(habit_logs, outcome_series, lag_days=0)

    # Empty pairs list
    assert pairs == [], "Empty habit_logs should produce no pairs"

    # Reason is non-empty and mentions missing habit logs
    assert debug["reason"] != "", "Reason should be non-empty for missing habit data"
    assert "habit" in debug["reason"].lower(), "Reason should mention habit"

    # No exception was raised (test passed)
    assert True


# ---------------------------------------------------------------------------
# UAT Step 4: Empty outcome_series
# ---------------------------------------------------------------------------

def test_uat_step_4_empty_outcome_series():
    """UAT Step 4: Populated habit_logs, empty outcome_series dict.

    Expected: Empty pairs list; debug reason is non-empty and mentions
    missing outcome series; no exception raised.
    """
    habit_logs = {
        "2025-06-02": True,
        "2025-06-03": False,
        "2025-06-04": True,
        "2025-06-05": False,
        "2025-06-06": True,
    }
    outcome_series = {}

    pairs, debug = align_habit_and_outcome(habit_logs, outcome_series, lag_days=0)

    # Empty pairs list
    assert pairs == [], "Empty outcome_series should produce no pairs"

    # Reason is non-empty and mentions missing outcome data
    assert debug["reason"] != "", "Reason should be non-empty for missing outcome data"
    assert "outcome" in debug["reason"].lower(), "Reason should mention outcome"

    # No exception was raised (test passed)
    assert True


# ---------------------------------------------------------------------------
# UAT Step 5: No overlapping dates after lag applied
# ---------------------------------------------------------------------------

def test_uat_step_5_no_overlap_after_lag():
    """UAT Step 5: habit_logs from week 1, outcome_series from week 3, lag=1.

    Expected: Zero pairs because no shifted outcome date falls within week 1
    plus one day; debug shows correct input counts, zero pairs after drop,
    non-empty reason string.
    """
    # Week 1 habits
    habit_logs = {
        "2025-06-02": True,   # Monday week 1
        "2025-06-03": False,  # Tuesday week 1
        "2025-06-04": True,   # Wednesday week 1
        "2025-06-05": False,  # Thursday week 1
        "2025-06-06": True,   # Friday week 1
    }

    # Week 3 outcomes (10+ days after week 1)
    outcome_series = {
        "2025-06-16": 80.0,   # Monday week 3
        "2025-06-17": 75.0,   # Tuesday week 3
        "2025-06-18": 85.0,   # Wednesday week 3
        "2025-06-19": 70.0,   # Thursday week 3
        "2025-06-20": 90.0,   # Friday week 3
    }

    pairs, debug = align_habit_and_outcome(habit_logs, outcome_series, lag_days=1)

    # Zero pairs because week 1 + lag 1 does not overlap with week 3
    assert pairs == [], "No pairs when date ranges don't overlap after lag"

    # Debug shows correct input counts but zero pairs after drop
    assert debug["total_habit_days"] == 5, "Should count 5 input habit days"
    assert debug["total_outcome_days"] == 5, "Should count 5 input outcome days"
    assert debug["pairs_after_drop"] == 0, "No shifted outcomes fall in outcome_series"

    # Reason is non-empty
    assert debug["reason"] != "", "Reason should explain why no pairs were found"
    assert "no outcome" in debug["reason"].lower() or "no overlap" in debug["reason"].lower(), \
        "Reason should mention missing outcomes or non-overlapping dates"


# ---------------------------------------------------------------------------
# UAT Step 6: Integration with real data fetching
# ---------------------------------------------------------------------------

def test_uat_step_6_thin_caller_integration():
    """UAT Step 6: A thin caller fetches real habit logs and outcome series
    from memory/mock data, passes them to align_habit_and_outcome, and logs debug.

    Expected: Pair count matches expected manual confirmation; function contains
    no database references.

    This test simulates a thin caller pattern: fetch the data, call the pure
    function, and verify the result.
    """
    # Simulate a thin caller that fetches habit logs for a user.
    # In real usage, this would query the database for habit completion records.
    habit_logs = {
        "2025-06-02": True,   # Monday
        "2025-06-03": False,  # Tuesday
        "2025-06-04": True,   # Wednesday
        "2025-06-05": False,  # Thursday
        "2025-06-06": True,   # Friday
    }

    # Simulate a thin caller that fetches an outcome series (e.g., readiness scores).
    # In real usage, this would query the database for daily readiness values.
    outcome_series = {
        "2025-06-03": 75.0,   # Tuesday (Monday's next day)
        "2025-06-05": 70.0,   # Thursday (Wednesday's next day)
        "2025-06-07": 95.0,   # Saturday (Friday's next day)
    }

    # Call the pure function with lag=1
    pairs, debug = align_habit_and_outcome(habit_logs, outcome_series, lag_days=1)

    # The pair count should match a manual check:
    # - Monday habit (True) → Tuesday outcome (75.0) ✓
    # - Wednesday habit (True) → Thursday outcome (70.0) ✓
    # - Friday habit (True) → Saturday outcome (95.0) ✓
    # So 3 pairs expected.
    expected_pair_count = 3
    assert len(pairs) == expected_pair_count, \
        f"Expected {expected_pair_count} pairs but got {len(pairs)}"

    # Verify that the debug object is present and meaningful
    assert debug["total_habit_days"] == 5, "Should report 5 habit days"
    assert debug["total_outcome_days"] == 3, "Should report 3 outcome days"
    assert debug["pairs_after_drop"] == 3, "Should report 3 pairs after drop"
    assert debug["lag_days"] == 1, "Should report lag=1 used"

    # The function itself has no database calls, file I/O, or network calls.
    # (This is verified by code review, not by the test; we just verify the result.)
    assert all("habit_date" in p and "outcome_date" in p for p in pairs), \
        "All pairs should have both habit_date and outcome_date"
