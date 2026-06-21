"""Tests for align_habit_and_outcome (issue #881).

Covers all AC items that are testable via unit tests:
- AC3: zero lag exact-match pairing
- AC4: positive lag shifted pairing
- AC5: missing days dropped
- AC6/AC7: return structure (pairs list + debug object)
- AC8: empty habit_logs
- AC9: empty outcome_series
- AC13: no overlapping dates after lag applied
- AC13: lag_days larger than gap between last habit day and last outcome day
"""

import pytest
from backend.services.habit_outcome_alignment import align_habit_and_outcome


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MONDAY = "2025-06-02"
TUESDAY = "2025-06-03"
WEDNESDAY = "2025-06-04"
THURSDAY = "2025-06-05"
FRIDAY = "2025-06-06"
SATURDAY = "2025-06-07"


@pytest.fixture
def week_habit_logs():
    """Five weekday habit entries alternating True/False."""
    return {
        MONDAY: True,
        TUESDAY: False,
        WEDNESDAY: True,
        THURSDAY: False,
        FRIDAY: True,
    }


@pytest.fixture
def week_outcome_series():
    """Outcome values Monday through Saturday."""
    return {
        MONDAY: 80.0,
        TUESDAY: 75.0,
        WEDNESDAY: 85.0,
        THURSDAY: 70.0,
        FRIDAY: 90.0,
        SATURDAY: 95.0,
    }


# ---------------------------------------------------------------------------
# AC3 / AC5 / AC6 / AC7: zero lag
# ---------------------------------------------------------------------------

class TestZeroLag:
    def test_returns_two_element_structure(self, week_habit_logs, week_outcome_series):
        result = align_habit_and_outcome(week_habit_logs, week_outcome_series, lag_days=0)
        assert len(result) == 2, "Must return a two-element structure"

    def test_five_pairs_when_lag_zero(self, week_habit_logs, week_outcome_series):
        pairs, debug = align_habit_and_outcome(week_habit_logs, week_outcome_series, lag_days=0)
        # All 5 weekday habit dates have a matching outcome; Saturday outcome unused
        assert len(pairs) == 5

    def test_pair_fields_present(self, week_habit_logs, week_outcome_series):
        pairs, _ = align_habit_and_outcome(week_habit_logs, week_outcome_series, lag_days=0)
        for p in pairs:
            assert "habit_date" in p
            assert "habit_value" in p
            assert "outcome_date" in p
            assert "outcome_value" in p

    def test_pair_dates_are_same_when_lag_zero(self, week_habit_logs, week_outcome_series):
        pairs, _ = align_habit_and_outcome(week_habit_logs, week_outcome_series, lag_days=0)
        for p in pairs:
            assert p["habit_date"] == p["outcome_date"]

    def test_debug_fields_present(self, week_habit_logs, week_outcome_series):
        _, debug = align_habit_and_outcome(week_habit_logs, week_outcome_series, lag_days=0)
        assert "total_habit_days" in debug
        assert "total_outcome_days" in debug
        assert "lag_days" in debug
        assert "pairs_before_drop" in debug
        assert "pairs_after_drop" in debug
        assert "reason" in debug

    def test_debug_counts_zero_lag(self, week_habit_logs, week_outcome_series):
        _, debug = align_habit_and_outcome(week_habit_logs, week_outcome_series, lag_days=0)
        assert debug["total_habit_days"] == 5
        assert debug["total_outcome_days"] == 6
        assert debug["lag_days"] == 0
        assert debug["pairs_after_drop"] == 5
        assert debug["reason"] == ""

    def test_saturday_outcome_not_paired(self, week_habit_logs, week_outcome_series):
        pairs, _ = align_habit_and_outcome(week_habit_logs, week_outcome_series, lag_days=0)
        outcome_dates = {p["outcome_date"] for p in pairs}
        assert SATURDAY not in outcome_dates

    def test_habit_values_preserved(self, week_habit_logs, week_outcome_series):
        pairs, _ = align_habit_and_outcome(week_habit_logs, week_outcome_series, lag_days=0)
        by_date = {p["habit_date"]: p for p in pairs}
        assert by_date[MONDAY]["habit_value"] is True
        assert by_date[TUESDAY]["habit_value"] is False


# ---------------------------------------------------------------------------
# AC4: positive lag
# ---------------------------------------------------------------------------

class TestPositiveLag:
    def test_positive_lag_shifts_outcome(self, week_habit_logs, week_outcome_series):
        # lag=1: Monday habit → Tuesday outcome, …, Friday habit → Saturday outcome
        pairs, _ = align_habit_and_outcome(week_habit_logs, week_outcome_series, lag_days=1)
        by_habit = {p["habit_date"]: p for p in pairs}
        assert by_habit[MONDAY]["outcome_date"] == TUESDAY
        assert by_habit[WEDNESDAY]["outcome_date"] == THURSDAY
        assert by_habit[FRIDAY]["outcome_date"] == SATURDAY

    def test_lag_one_produces_five_pairs(self, week_habit_logs, week_outcome_series):
        # All 5 habit days have a +1-day outcome in the series
        pairs, _ = align_habit_and_outcome(week_habit_logs, week_outcome_series, lag_days=1)
        assert len(pairs) == 5

    def test_debug_reason_empty_on_valid_input(self, week_habit_logs, week_outcome_series):
        _, debug = align_habit_and_outcome(week_habit_logs, week_outcome_series, lag_days=1)
        assert debug["reason"] == ""

    def test_debug_lag_recorded(self, week_habit_logs, week_outcome_series):
        _, debug = align_habit_and_outcome(week_habit_logs, week_outcome_series, lag_days=1)
        assert debug["lag_days"] == 1

    def test_docstring_worked_example(self):
        """AC10: docstring example — five habits, only Tue/Thu/Sat outcomes exist.

        The AC10 worked example says three pairs with lag_days=1.  To produce
        exactly three pairs the outcome series must have only Tuesday, Thursday,
        and Saturday (the shifted dates for Monday, Wednesday, and Friday
        respectively).  Tuesday and Thursday habit days are dropped because
        Wednesday and Friday are absent from the outcome series.
        """
        habit_logs = {
            MONDAY: True,
            TUESDAY: False,
            WEDNESDAY: True,
            THURSDAY: False,
            FRIDAY: True,
        }
        # Only the three shifted dates exist, so only Mon/Wed/Fri habits match.
        outcome_series = {
            TUESDAY: 75.0,    # Monday+1
            THURSDAY: 70.0,   # Wednesday+1
            SATURDAY: 95.0,   # Friday+1
        }
        pairs, debug = align_habit_and_outcome(habit_logs, outcome_series, lag_days=1)
        # Monday → Tuesday, Wednesday → Thursday, Friday → Saturday
        assert len(pairs) == 3
        by_habit = {p["habit_date"]: p for p in pairs}
        assert by_habit[MONDAY]["outcome_date"] == TUESDAY
        assert by_habit[WEDNESDAY]["outcome_date"] == THURSDAY
        assert by_habit[FRIDAY]["outcome_date"] == SATURDAY
        assert debug["total_habit_days"] == 5
        assert debug["total_outcome_days"] == 3
        assert debug["pairs_after_drop"] == 3


# ---------------------------------------------------------------------------
# AC8: empty habit_logs
# ---------------------------------------------------------------------------

class TestEmptyHabitLogs:
    def test_none_habit_logs_returns_empty_pairs(self, week_outcome_series):
        pairs, debug = align_habit_and_outcome(None, week_outcome_series, lag_days=0)
        assert pairs == []

    def test_none_habit_logs_reason_non_empty(self, week_outcome_series):
        _, debug = align_habit_and_outcome(None, week_outcome_series, lag_days=0)
        assert debug["reason"] != ""

    def test_empty_dict_habit_logs_returns_empty_pairs(self, week_outcome_series):
        pairs, debug = align_habit_and_outcome({}, week_outcome_series, lag_days=0)
        assert pairs == []

    def test_empty_dict_habit_logs_reason_non_empty(self, week_outcome_series):
        _, debug = align_habit_and_outcome({}, week_outcome_series, lag_days=0)
        assert debug["reason"] != ""

    def test_empty_habit_logs_no_exception(self, week_outcome_series):
        # Must not raise any exception
        result = align_habit_and_outcome(None, week_outcome_series, lag_days=0)
        assert result is not None


# ---------------------------------------------------------------------------
# AC9: empty outcome_series
# ---------------------------------------------------------------------------

class TestEmptyOutcomeSeries:
    def test_none_outcome_returns_empty_pairs(self, week_habit_logs):
        pairs, _ = align_habit_and_outcome(week_habit_logs, None, lag_days=0)
        assert pairs == []

    def test_none_outcome_reason_non_empty(self, week_habit_logs):
        _, debug = align_habit_and_outcome(week_habit_logs, None, lag_days=0)
        assert debug["reason"] != ""

    def test_empty_dict_outcome_returns_empty_pairs(self, week_habit_logs):
        pairs, _ = align_habit_and_outcome(week_habit_logs, {}, lag_days=0)
        assert pairs == []

    def test_empty_dict_outcome_reason_non_empty(self, week_habit_logs):
        _, debug = align_habit_and_outcome(week_habit_logs, {}, lag_days=0)
        assert debug["reason"] != ""

    def test_empty_outcome_no_exception(self, week_habit_logs):
        result = align_habit_and_outcome(week_habit_logs, None, lag_days=0)
        assert result is not None


# ---------------------------------------------------------------------------
# AC13: no overlapping dates after lag applied
# ---------------------------------------------------------------------------

class TestNoOverlapAfterLag:
    WEEK1_MONDAY = "2025-06-02"
    WEEK1_FRIDAY = "2025-06-06"
    WEEK3_MONDAY = "2025-06-16"
    WEEK3_FRIDAY = "2025-06-20"

    def test_no_overlap_produces_zero_pairs(self):
        habit_logs = {
            self.WEEK1_MONDAY: True,
            self.WEEK1_FRIDAY: False,
        }
        outcome_series = {
            self.WEEK3_MONDAY: 80.0,
            self.WEEK3_FRIDAY: 75.0,
        }
        pairs, debug = align_habit_and_outcome(habit_logs, outcome_series, lag_days=1)
        assert pairs == []
        assert debug["pairs_after_drop"] == 0

    def test_no_overlap_reason_non_empty(self):
        habit_logs = {self.WEEK1_MONDAY: True}
        outcome_series = {self.WEEK3_MONDAY: 80.0}
        _, debug = align_habit_and_outcome(habit_logs, outcome_series, lag_days=1)
        assert debug["reason"] != ""

    def test_no_overlap_input_counts_correct(self):
        habit_logs = {self.WEEK1_MONDAY: True, self.WEEK1_FRIDAY: False}
        outcome_series = {self.WEEK3_MONDAY: 80.0, self.WEEK3_FRIDAY: 75.0}
        _, debug = align_habit_and_outcome(habit_logs, outcome_series, lag_days=1)
        assert debug["total_habit_days"] == 2
        assert debug["total_outcome_days"] == 2


# ---------------------------------------------------------------------------
# AC13: lag_days larger than gap between last habit day and last outcome day
# ---------------------------------------------------------------------------

class TestLagLargerThanGap:
    def test_large_lag_produces_zero_pairs(self, week_habit_logs, week_outcome_series):
        # largest possible gap: Friday (last habit) to Saturday (last outcome) = 1 day
        # lag=100 means we need outcomes 100 days after each habit — none exist
        pairs, debug = align_habit_and_outcome(week_habit_logs, week_outcome_series, lag_days=100)
        assert pairs == []
        assert debug["pairs_after_drop"] == 0

    def test_large_lag_reason_non_empty(self, week_habit_logs, week_outcome_series):
        _, debug = align_habit_and_outcome(week_habit_logs, week_outcome_series, lag_days=100)
        assert debug["reason"] != ""

    def test_large_lag_input_counts_still_correct(self, week_habit_logs, week_outcome_series):
        _, debug = align_habit_and_outcome(week_habit_logs, week_outcome_series, lag_days=100)
        assert debug["total_habit_days"] == 5
        assert debug["total_outcome_days"] == 6


# ---------------------------------------------------------------------------
# AC7: debug object completeness
# ---------------------------------------------------------------------------

class TestDebugObjectCompleteness:
    def test_pairs_before_drop_gte_pairs_after_drop(self, week_habit_logs, week_outcome_series):
        _, debug = align_habit_and_outcome(week_habit_logs, week_outcome_series, lag_days=0)
        assert debug["pairs_before_drop"] >= debug["pairs_after_drop"]

    def test_pairs_before_drop_equals_habit_days_when_lag_zero(self, week_habit_logs, week_outcome_series):
        # Before dropping, we attempt one pair per habit day
        _, debug = align_habit_and_outcome(week_habit_logs, week_outcome_series, lag_days=0)
        assert debug["pairs_before_drop"] == 5

    def test_reason_empty_string_on_valid_nonempty_result(self, week_habit_logs, week_outcome_series):
        _, debug = align_habit_and_outcome(week_habit_logs, week_outcome_series, lag_days=0)
        assert isinstance(debug["reason"], str)
        assert debug["reason"] == ""
