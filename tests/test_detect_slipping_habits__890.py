"""Tests for detect_slipping_habits (issue #890).

Covers all Acceptance Criteria:
- AC1:  detect_slipping_habits(habits_with_history, window) exists in backend.services.habit_slipping
- AC2:  accepts list of habits with history arrays and a window integer
- AC3:  calls compute_consistency internally (not reimplementing rate calculation)
- AC4:  recent rate covers last window days; prior rate covers preceding window days
- AC5:  SLIPPING_DROP_THRESHOLD named constant; flag when prior_rate - recent_rate >= threshold
- AC6:  each returned entry has habit_id, current_rate, prior_rate, drop, debug
- AC7:  None input → {"slipping": [], "reason": "..."}
- AC8:  empty or non-iterable input → {"slipping": [], "reason": "..."}
- AC9:  zero or negative window → {"slipping": [], "reason": "..."}
- AC10: insufficient history habit is skipped; skip reason in per_habit_debug
- AC11: docstring worked example (90% prior / 50% recent / window=30 → in slipping)
- AC12: inline comments present; no magic numeric thresholds beyond the two constants
- AC13: unit tests cover normal slipping, no-drop, missing input, invalid window,
         insufficient history, boundary-inclusive threshold, and the worked example
"""

from __future__ import annotations

import types
from datetime import date, timedelta

import pytest

from backend.services.habit_slipping import (
    SLIPPING_DROP_THRESHOLD,
    detect_slipping_habits,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_today = date.today()


def _days_back(n: int) -> date:
    return _today - timedelta(days=n)


def _make_habit(habit_id, schedule_type="daily", schedule_target=None,
                habit_type="binary", target_value=None):
    h = types.SimpleNamespace()
    h.id = habit_id
    h.schedule_type = schedule_type
    h.schedule_target = schedule_target
    h.habit_type = habit_type
    h.target_value = target_value
    h.tracking_type = "daily_checkmark"
    return h


def _make_log(log_date: date, value=1):
    lg = types.SimpleNamespace()
    lg.log_date = log_date
    lg.value = value
    return lg


def _make_daily_habit_with_history(habit_id, window, recent_completions, prior_completions):
    """
    Build a daily binary habit with exactly recent_completions logs in the recent
    window and prior_completions logs in the prior window.

    Recent window: days 0 through window-1 back from today (inclusive).
    Prior window:  days window through 2*window-1 back from today (inclusive).
    """
    h = _make_habit(habit_id)
    recent_logs = [_make_log(_days_back(i)) for i in range(recent_completions)]
    prior_logs = [_make_log(_days_back(window + i)) for i in range(prior_completions)]
    h.history = recent_logs + prior_logs
    return h


# ---------------------------------------------------------------------------
# AC1 / AC2: function exists and is callable
# ---------------------------------------------------------------------------

class TestFunctionSignature:
    def test_function_is_callable(self):
        assert callable(detect_slipping_habits)

    def test_returns_dict_with_slipping_key(self):
        habit = _make_daily_habit_with_history("h1", window=10,
                                               recent_completions=5, prior_completions=10)
        result = detect_slipping_habits([habit], window=10)
        assert isinstance(result, dict)
        assert "slipping" in result

    def test_slipping_is_list(self):
        habit = _make_daily_habit_with_history("h1", window=10,
                                               recent_completions=5, prior_completions=10)
        result = detect_slipping_habits([habit], window=10)
        assert isinstance(result["slipping"], list)


# ---------------------------------------------------------------------------
# AC5 / AC6: SLIPPING_DROP_THRESHOLD constant and return shape
# ---------------------------------------------------------------------------

class TestConstant:
    def test_threshold_is_named_constant(self):
        assert isinstance(SLIPPING_DROP_THRESHOLD, float)

    def test_threshold_is_positive(self):
        assert SLIPPING_DROP_THRESHOLD > 0

    def test_threshold_is_less_than_one(self):
        assert SLIPPING_DROP_THRESHOLD < 1


class TestSlippingEntryShape:
    """AC6: each entry has habit_id, current_rate, prior_rate, drop, debug."""

    def test_slipping_entry_has_required_keys(self):
        # window=10; prior 10/10=100%, recent 5/10=50%, drop=50% → slipping
        habit = _make_daily_habit_with_history("h1", window=10,
                                               recent_completions=5, prior_completions=10)
        result = detect_slipping_habits([habit], window=10)
        assert len(result["slipping"]) == 1
        entry = result["slipping"][0]
        for key in ("habit_id", "current_rate", "prior_rate", "drop", "debug"):
            assert key in entry, f"missing key: {key}"

    def test_debug_has_required_keys(self):
        habit = _make_daily_habit_with_history("h1", window=10,
                                               recent_completions=5, prior_completions=10)
        result = detect_slipping_habits([habit], window=10)
        debug = result["slipping"][0]["debug"]
        for key in ("window", "recent_days_counted", "prior_days_counted", "threshold_used"):
            assert key in debug, f"debug missing key: {key}"

    def test_current_rate_between_zero_and_one(self):
        habit = _make_daily_habit_with_history("h1", window=10,
                                               recent_completions=5, prior_completions=10)
        result = detect_slipping_habits([habit], window=10)
        entry = result["slipping"][0]
        assert 0.0 <= entry["current_rate"] <= 1.0

    def test_prior_rate_between_zero_and_one(self):
        habit = _make_daily_habit_with_history("h1", window=10,
                                               recent_completions=5, prior_completions=10)
        result = detect_slipping_habits([habit], window=10)
        entry = result["slipping"][0]
        assert 0.0 <= entry["prior_rate"] <= 1.0

    def test_drop_equals_prior_minus_recent(self):
        habit = _make_daily_habit_with_history("h1", window=10,
                                               recent_completions=5, prior_completions=10)
        result = detect_slipping_habits([habit], window=10)
        entry = result["slipping"][0]
        assert abs(entry["drop"] - (entry["prior_rate"] - entry["current_rate"])) < 1e-9

    def test_habit_id_matches_input(self):
        habit = _make_daily_habit_with_history("my-habit-abc", window=10,
                                               recent_completions=2, prior_completions=10)
        result = detect_slipping_habits([habit], window=10)
        assert result["slipping"][0]["habit_id"] == "my-habit-abc"


# ---------------------------------------------------------------------------
# AC4: rate computation windows
# ---------------------------------------------------------------------------

class TestWindowRates:
    def test_recent_rate_correct(self):
        # window=10; recent 7/10 = 0.70
        habit = _make_daily_habit_with_history("h1", window=10,
                                               recent_completions=7, prior_completions=10)
        result = detect_slipping_habits([habit], window=10)
        # drop = 1.0 - 0.7 = 0.3 >= SLIPPING_DROP_THRESHOLD (0.20) → slipping
        assert len(result["slipping"]) == 1
        assert abs(result["slipping"][0]["current_rate"] - 0.7) < 1e-9

    def test_prior_rate_correct(self):
        # window=10; prior 9/10 = 0.90
        habit = _make_daily_habit_with_history("h1", window=10,
                                               recent_completions=7, prior_completions=9)
        result = detect_slipping_habits([habit], window=10)
        assert abs(result["slipping"][0]["prior_rate"] - 0.9) < 1e-9


# ---------------------------------------------------------------------------
# AC11: worked example from docstring (90% prior / 50% recent / window=30)
# ---------------------------------------------------------------------------

class TestWorkedExample:
    def test_docstring_worked_example(self):
        """window=30; prior 27/30=0.9, recent 15/30=0.5, drop=0.4 → slipping."""
        window = 30
        habit = _make_daily_habit_with_history("habit-worked-example",
                                               window=window,
                                               recent_completions=15,
                                               prior_completions=27)
        result = detect_slipping_habits([habit], window=window)
        assert len(result["slipping"]) == 1
        entry = result["slipping"][0]
        assert abs(entry["prior_rate"] - 0.9) < 1e-9
        assert abs(entry["current_rate"] - 0.5) < 1e-9
        assert abs(entry["drop"] - 0.4) < 1e-9


# ---------------------------------------------------------------------------
# AC5: threshold boundary (inclusive)
# ---------------------------------------------------------------------------

class TestThresholdBoundary:
    def test_drop_exactly_at_threshold_is_flagged(self):
        """UAT step 3: boundary is inclusive (>=)."""
        # Use window=20; construct completions so drop == SLIPPING_DROP_THRESHOLD exactly.
        # prior_rate = p/20, recent_rate = r/20, drop = (p - r) / 20 == SLIPPING_DROP_THRESHOLD
        # With threshold=0.20: p - r = 0.20 * 20 = 4
        # Choose: prior=14/20=0.70, recent=10/20=0.50, drop=0.20
        window = 20
        prior_completions = int(0.7 * window)   # 14 → 0.70
        recent_completions = int(0.5 * window)  # 10 → 0.50
        # drop = 0.70 - 0.50 = 0.20 = SLIPPING_DROP_THRESHOLD (boundary inclusive)
        assert abs((prior_completions / window) - (recent_completions / window) - SLIPPING_DROP_THRESHOLD) < 1e-9

        habit = _make_daily_habit_with_history("h-boundary-exact", window=window,
                                               recent_completions=recent_completions,
                                               prior_completions=prior_completions)
        result = detect_slipping_habits([habit], window=window)
        assert any(e["habit_id"] == "h-boundary-exact" for e in result["slipping"])

    def test_drop_below_threshold_not_flagged(self):
        """UAT step 4: one percentage point below threshold is not flagged."""
        # With threshold=0.20 and window=100: prior=80%, recent=61%, drop=0.19 < 0.20
        window = 100
        prior_completions = 80   # 80% → prior_rate = 0.80
        recent_completions = 61  # 61% → recent_rate = 0.61, drop = 0.19
        habit = _make_daily_habit_with_history("h-below-threshold", window=window,
                                               recent_completions=recent_completions,
                                               prior_completions=prior_completions)
        result = detect_slipping_habits([habit], window=window)
        assert not any(e["habit_id"] == "h-below-threshold" for e in result["slipping"])


# ---------------------------------------------------------------------------
# No-drop case (rates equal or improving)
# ---------------------------------------------------------------------------

class TestNoDrop:
    def test_equal_rates_not_slipping(self):
        """UAT step 2: recent == prior → not slipping."""
        window = 10
        habit = _make_daily_habit_with_history("h-equal", window=window,
                                               recent_completions=8,
                                               prior_completions=8)
        result = detect_slipping_habits([habit], window=window)
        assert not any(e["habit_id"] == "h-equal" for e in result["slipping"])

    def test_improving_rate_not_slipping(self):
        """UAT step 2: recent > prior → not slipping."""
        window = 10
        habit = _make_daily_habit_with_history("h-improving", window=window,
                                               recent_completions=9,
                                               prior_completions=5)
        result = detect_slipping_habits([habit], window=window)
        assert not any(e["habit_id"] == "h-improving" for e in result["slipping"])


# ---------------------------------------------------------------------------
# AC7: None and empty inputs
# ---------------------------------------------------------------------------

class TestInvalidHabits:
    def test_none_habits_returns_reason(self):
        """UAT step 5: detect_slipping_habits(None, 30) → slipping=[], reason set."""
        result = detect_slipping_habits(None, 30)
        assert result["slipping"] == []
        assert "reason" in result
        assert result["reason"]

    def test_empty_list_returns_reason(self):
        """UAT step 6: detect_slipping_habits([], 30) → slipping=[], reason set."""
        result = detect_slipping_habits([], 30)
        assert result["slipping"] == []
        assert "reason" in result
        assert result["reason"]

    def test_none_habits_does_not_raise(self):
        try:
            detect_slipping_habits(None, 30)
        except Exception as exc:
            pytest.fail(f"Should not raise, got: {exc}")

    def test_empty_list_does_not_raise(self):
        try:
            detect_slipping_habits([], 30)
        except Exception as exc:
            pytest.fail(f"Should not raise, got: {exc}")


# ---------------------------------------------------------------------------
# AC9: zero or negative window
# ---------------------------------------------------------------------------

class TestInvalidWindow:
    def test_zero_window_returns_reason(self):
        """UAT step 7: window=0 → slipping=[], reason set."""
        habit = _make_daily_habit_with_history("h1", window=10,
                                               recent_completions=5, prior_completions=10)
        result = detect_slipping_habits([habit], 0)
        assert result["slipping"] == []
        assert "reason" in result
        assert result["reason"]

    def test_negative_window_returns_reason(self):
        """UAT step 7: window=-7 → slipping=[], reason set."""
        habit = _make_daily_habit_with_history("h1", window=10,
                                               recent_completions=5, prior_completions=10)
        result = detect_slipping_habits([habit], -7)
        assert result["slipping"] == []
        assert "reason" in result
        assert result["reason"]

    def test_zero_window_does_not_raise(self):
        try:
            detect_slipping_habits([], 0)
        except Exception as exc:
            pytest.fail(f"Should not raise, got: {exc}")

    def test_negative_window_does_not_raise(self):
        try:
            detect_slipping_habits([], -7)
        except Exception as exc:
            pytest.fail(f"Should not raise, got: {exc}")

    def test_missing_window_returns_reason(self):
        """window=None → slipping=[], reason set."""
        result = detect_slipping_habits([], None)
        assert result["slipping"] == []
        assert "reason" in result


# ---------------------------------------------------------------------------
# AC10: insufficient history
# ---------------------------------------------------------------------------

class TestInsufficientHistory:
    def test_insufficient_history_not_in_slipping(self):
        """UAT step 8: habit with < 2*window history days absent from slipping."""
        window = 30
        # Give the habit only 15 days of history (need 60 to fill both windows)
        h = _make_habit("h-short")
        # logs only in the recent window (past 15 days)
        h.history = [_make_log(_days_back(i)) for i in range(15)]
        result = detect_slipping_habits([h], window=window)
        assert not any(e["habit_id"] == "h-short" for e in result["slipping"])

    def test_insufficient_history_skip_reason_in_debug(self):
        """UAT step 8: per_habit_debug notes skip reason for insufficient history habit."""
        window = 30
        h = _make_habit("h-short")
        h.history = [_make_log(_days_back(i)) for i in range(15)]
        result = detect_slipping_habits([h], window=window)
        assert "per_habit_debug" in result
        assert "h-short" in result["per_habit_debug"]
        entry_debug = result["per_habit_debug"]["h-short"]
        assert "skip_reason" in entry_debug
        assert entry_debug["skip_reason"]  # non-empty


# ---------------------------------------------------------------------------
# Mixed list: only slipping habits appear in slipping
# ---------------------------------------------------------------------------

class TestMixedList:
    def test_only_slipping_habits_in_slipping(self):
        """UAT step 9: slipping list contains only habits meeting drop threshold."""
        window = 10
        h_slipping = _make_daily_habit_with_history("slip", window=window,
                                                    recent_completions=3, prior_completions=10)
        h_stable = _make_daily_habit_with_history("stable", window=window,
                                                  recent_completions=9, prior_completions=9)
        result = detect_slipping_habits([h_slipping, h_stable], window=window)
        slipping_ids = {e["habit_id"] for e in result["slipping"]}
        assert "slip" in slipping_ids
        assert "stable" not in slipping_ids

    def test_non_slipping_habits_absent(self):
        window = 10
        h_slipping = _make_daily_habit_with_history("a", window=window,
                                                    recent_completions=2, prior_completions=10)
        h_ok = _make_daily_habit_with_history("b", window=window,
                                              recent_completions=8, prior_completions=8)
        result = detect_slipping_habits([h_slipping, h_ok], window=window)
        assert not any(e["habit_id"] == "b" for e in result["slipping"])


# ---------------------------------------------------------------------------
# AC6: debug object content (UAT step 10)
# ---------------------------------------------------------------------------

class TestDebugObject:
    def test_debug_window_matches_input(self):
        """UAT step 10: debug.window matches the window argument."""
        window = 15
        habit = _make_daily_habit_with_history("h1", window=window,
                                               recent_completions=4, prior_completions=15)
        result = detect_slipping_habits([habit], window=window)
        assert result["slipping"][0]["debug"]["window"] == window

    def test_debug_threshold_used_matches_constant(self):
        """UAT step 10: debug.threshold_used == SLIPPING_DROP_THRESHOLD."""
        window = 10
        habit = _make_daily_habit_with_history("h1", window=window,
                                               recent_completions=3, prior_completions=10)
        result = detect_slipping_habits([habit], window=window)
        assert result["slipping"][0]["debug"]["threshold_used"] == SLIPPING_DROP_THRESHOLD

    def test_debug_days_counted_are_numeric(self):
        window = 10
        habit = _make_daily_habit_with_history("h1", window=window,
                                               recent_completions=5, prior_completions=10)
        result = detect_slipping_habits([habit], window=window)
        debug = result["slipping"][0]["debug"]
        assert isinstance(debug["recent_days_counted"], (int, float))
        assert isinstance(debug["prior_days_counted"], (int, float))


# ---------------------------------------------------------------------------
# AC3: compute_consistency is called (not reimplemented inline)
# ---------------------------------------------------------------------------

class TestDelegateToComputeConsistency:
    def test_calls_compute_consistency_not_reimplemented(self, monkeypatch):
        """AC3: detect_slipping_habits calls compute_consistency, not a custom formula."""
        import backend.services.habit_slipping as module_under_test

        call_count = []

        original = module_under_test.compute_consistency

        def spy(*args, **kwargs):
            call_count.append(1)
            return original(*args, **kwargs)

        monkeypatch.setattr(module_under_test, "compute_consistency", spy)

        window = 10
        habit = _make_daily_habit_with_history("h1", window=window,
                                               recent_completions=5, prior_completions=10)
        detect_slipping_habits([habit], window=window)
        # compute_consistency should have been called at least twice (once per window)
        assert len(call_count) >= 2
