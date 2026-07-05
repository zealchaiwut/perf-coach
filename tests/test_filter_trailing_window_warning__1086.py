"""Tests for issue #1086: _filter_trailing_window emits warning on bad workout_date.

Acceptance Criteria covered:
  AC1: WARNING emitted when one or more runs have unparseable/null workout_date,
       using message format "dropping %d run(s) from trailing window: unparseable workout_date".
  AC2: No warning when all runs have valid parseable dates.
  AC3: Filtering behavior unchanged — bad-date runs still excluded from result.
  AC4: Cutoff-excluded runs (valid date but before cutoff) produce no warning.
  AC5: Drop count in warning reflects only bad-date exclusions, not cutoff exclusions.
"""

import logging

import pytest

from backend.services.running_performance import _filter_trailing_window


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(workout_date, run_id="r1"):
    return {"run_id": run_id, "workout_date": workout_date}


# ---------------------------------------------------------------------------
# AC1 — WARNING emitted for unparseable/null workout_date
# ---------------------------------------------------------------------------

class TestWarningEmittedForBadDatesAC1:
    """AC1: WARNING logged when one or more runs have unparseable or null workout_date."""

    def test_warning_emitted_for_null_workout_date(self, caplog):
        items = [
            _run("2026-01-10", "r1"),
            _run(None, "r2"),
        ]
        with caplog.at_level(logging.WARNING,
                             logger="backend.services.running_performance"):
            _filter_trailing_window(items, window_days=90)

        warning_msgs = [
            r.getMessage()
            for r in caplog.records
            if r.levelno == logging.WARNING
            and "trailing window" in r.getMessage()
        ]
        assert warning_msgs, (
            "Expected a WARNING about 'trailing window' when a run has null workout_date. "
            f"Records: {[(r.levelname, r.getMessage()) for r in caplog.records]}"
        )

    def test_warning_emitted_for_malformed_workout_date(self, caplog):
        items = [
            _run("2026-01-10", "r1"),
            _run("not-a-date", "r2"),
        ]
        with caplog.at_level(logging.WARNING,
                             logger="backend.services.running_performance"):
            _filter_trailing_window(items, window_days=90)

        warning_msgs = [
            r.getMessage()
            for r in caplog.records
            if r.levelno == logging.WARNING
            and "trailing window" in r.getMessage()
        ]
        assert warning_msgs, (
            "Expected a WARNING about 'trailing window' when a run has a malformed workout_date."
        )

    def test_warning_message_format_matches_spec(self, caplog):
        """Message must match 'dropping %d run(s) from trailing window: unparseable workout_date'."""
        items = [
            _run("2026-01-10", "r1"),
            _run(None, "r2"),
            _run("bad", "r3"),
        ]
        with caplog.at_level(logging.WARNING,
                             logger="backend.services.running_performance"):
            _filter_trailing_window(items, window_days=90)

        warning_msgs = [
            r.getMessage()
            for r in caplog.records
            if r.levelno == logging.WARNING
        ]
        assert any(
            "unparseable workout_date" in msg and "trailing window" in msg
            for msg in warning_msgs
        ), (
            f"Warning message must contain 'trailing window' and 'unparseable workout_date'. "
            f"Got: {warning_msgs}"
        )

    def test_warning_emitted_for_empty_string_workout_date(self, caplog):
        items = [
            _run("2026-01-10", "r1"),
            _run("", "r2"),
        ]
        with caplog.at_level(logging.WARNING,
                             logger="backend.services.running_performance"):
            _filter_trailing_window(items, window_days=90)

        warning_msgs = [
            r.getMessage()
            for r in caplog.records
            if r.levelno == logging.WARNING
            and "trailing window" in r.getMessage()
        ]
        assert warning_msgs, (
            "Expected WARNING for an empty-string workout_date."
        )


# ---------------------------------------------------------------------------
# AC2 — No warning when all dates are valid
# ---------------------------------------------------------------------------

class TestNoWarningForValidDatesAC2:
    """AC2: No warning is emitted when all runs have valid parseable workout_date."""

    def test_no_warning_all_valid_dates(self, caplog):
        items = [
            _run("2026-01-01", "r1"),
            _run("2026-01-10", "r2"),
            _run("2026-01-20", "r3"),
        ]
        with caplog.at_level(logging.WARNING,
                             logger="backend.services.running_performance"):
            _filter_trailing_window(items, window_days=90)

        trailing_warnings = [
            r for r in caplog.records
            if r.levelno >= logging.WARNING
            and "trailing window" in r.getMessage()
        ]
        assert not trailing_warnings, (
            f"Expected no 'trailing window' warnings when all dates are valid. "
            f"Got: {[r.getMessage() for r in trailing_warnings]}"
        )

    def test_no_warning_single_valid_item(self, caplog):
        items = [_run("2026-01-15", "r1")]
        with caplog.at_level(logging.WARNING,
                             logger="backend.services.running_performance"):
            _filter_trailing_window(items, window_days=30)

        trailing_warnings = [
            r for r in caplog.records
            if r.levelno >= logging.WARNING
            and "trailing window" in r.getMessage()
        ]
        assert not trailing_warnings, "No warning expected for a single valid-date item."


# ---------------------------------------------------------------------------
# AC3 — Filtering behavior unchanged
# ---------------------------------------------------------------------------

class TestFilteringBehaviorUnchangedAC3:
    """AC3: Bad-date runs still excluded from result after adding the warning."""

    def test_null_date_run_excluded_from_result(self, caplog):
        good = _run("2026-01-10", "r1")
        bad = _run(None, "r2")
        with caplog.at_level(logging.WARNING,
                             logger="backend.services.running_performance"):
            result = _filter_trailing_window([good, bad], window_days=90)

        ids = [r["run_id"] for r in result]
        assert "r1" in ids, "Valid-date run must be in result."
        assert "r2" not in ids, "Null-date run must be excluded."

    def test_malformed_date_run_excluded_from_result(self, caplog):
        good = _run("2026-01-10", "r1")
        bad = _run("not-a-date", "r2")
        with caplog.at_level(logging.WARNING,
                             logger="backend.services.running_performance"):
            result = _filter_trailing_window([good, bad], window_days=90)

        ids = [r["run_id"] for r in result]
        assert "r1" in ids
        assert "r2" not in ids, "Malformed-date run must still be excluded."

    def test_all_items_returned_when_all_dates_unparseable(self, caplog):
        """When no item has a parseable date, the function returns items unchanged."""
        items = [_run(None, "r1"), _run("bad", "r2")]
        with caplog.at_level(logging.WARNING,
                             logger="backend.services.running_performance"):
            result = _filter_trailing_window(items, window_days=90)

        # Existing behavior: if valid_dates is empty, return items unchanged.
        assert result == items, (
            "When all workout_dates are unparseable, result must be items unchanged."
        )


# ---------------------------------------------------------------------------
# AC4 — Cutoff-excluded runs produce no warning
# ---------------------------------------------------------------------------

class TestCutoffExclusionsProduceNoWarningAC4:
    """AC4: Runs excluded only because they're before the cutoff don't trigger a warning."""

    def test_no_warning_for_cutoff_exclusion(self, caplog):
        # r1 is recent; r2 is 200 days old (outside 90-day window).
        items = [
            _run("2026-01-20", "r1"),
            _run("2025-07-05", "r2"),  # > 90 days before 2026-01-20
        ]
        with caplog.at_level(logging.WARNING,
                             logger="backend.services.running_performance"):
            result = _filter_trailing_window(items, window_days=90)

        trailing_warnings = [
            r for r in caplog.records
            if r.levelno >= logging.WARNING
            and "trailing window" in r.getMessage()
        ]
        assert not trailing_warnings, (
            f"Cutoff exclusions must not emit a trailing-window warning. "
            f"Got: {[r.getMessage() for r in trailing_warnings]}"
        )
        assert any(r["run_id"] == "r1" for r in result)
        assert not any(r["run_id"] == "r2" for r in result)

    def test_no_warning_mixed_cutoff_and_window_valid(self, caplog):
        """Mix of valid-in-window and valid-cutoff-excluded — no warning expected."""
        items = [
            _run("2026-01-20", "r1"),
            _run("2026-01-15", "r2"),
            _run("2025-01-01", "r3"),  # well outside 90-day window
        ]
        with caplog.at_level(logging.WARNING,
                             logger="backend.services.running_performance"):
            _filter_trailing_window(items, window_days=90)

        trailing_warnings = [
            r for r in caplog.records
            if r.levelno >= logging.WARNING
            and "trailing window" in r.getMessage()
        ]
        assert not trailing_warnings


# ---------------------------------------------------------------------------
# AC5 — Drop count in warning matches bad-date count only
# ---------------------------------------------------------------------------

class TestDropCountAccuracyAC5:
    """AC5: Warning count = number of bad-date runs, not total excluded runs."""

    def test_warning_count_matches_bad_date_count(self, caplog):
        items = [
            _run("2026-01-20", "r1"),
            _run(None, "r2"),
            _run("bad-date", "r3"),
            _run("2025-01-01", "r4"),  # valid date but outside 90-day window
        ]
        with caplog.at_level(logging.WARNING,
                             logger="backend.services.running_performance"):
            _filter_trailing_window(items, window_days=90)

        warning_msgs = [
            r.getMessage()
            for r in caplog.records
            if r.levelno == logging.WARNING
            and "trailing window" in r.getMessage()
        ]
        assert warning_msgs, "Expected a warning for the 2 bad-date runs."
        # The count in the message must say 2 (r2 + r3), not 3 (r2 + r3 + r4).
        assert "2" in warning_msgs[0], (
            f"Warning drop count must be 2 (bad-date runs only, not cutoff-excluded). "
            f"Got: {warning_msgs[0]!r}"
        )

    def test_warning_count_three_bad_dates(self, caplog):
        items = [
            _run("2026-01-20", "r1"),
            _run(None, "r2"),
            _run("garbage", "r3"),
            _run("12345", "r4"),
        ]
        with caplog.at_level(logging.WARNING,
                             logger="backend.services.running_performance"):
            _filter_trailing_window(items, window_days=90)

        warning_msgs = [
            r.getMessage()
            for r in caplog.records
            if r.levelno == logging.WARNING
            and "trailing window" in r.getMessage()
        ]
        assert warning_msgs, "Expected a warning for 3 bad-date runs."
        assert "3" in warning_msgs[0], (
            f"Warning drop count must be 3. Got: {warning_msgs[0]!r}"
        )

    def test_warning_count_one_bad_date(self, caplog):
        items = [
            _run("2026-01-20", "r1"),
            _run("2026-01-10", "r2"),
            _run(None, "r3"),
        ]
        with caplog.at_level(logging.WARNING,
                             logger="backend.services.running_performance"):
            _filter_trailing_window(items, window_days=90)

        warning_msgs = [
            r.getMessage()
            for r in caplog.records
            if r.levelno == logging.WARNING
            and "trailing window" in r.getMessage()
        ]
        assert warning_msgs, "Expected a warning for 1 bad-date run."
        assert "1" in warning_msgs[0], (
            f"Warning drop count must be 1. Got: {warning_msgs[0]!r}"
        )
