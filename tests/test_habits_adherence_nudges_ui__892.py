"""Tests for issue #892: Habits page adherence and nudges UI.

Acceptance criteria verified:
- AC1: Endpoint returns expected shape with habits list and building flag
- AC2: met_count/scheduled_count correctly represent this week's adherence
- AC3: best_day and worst_day are present per habit (name string or null)
- AC4: Declining habit trend is flagged with trend="declining"
- AC6: Building state returned when history is below minimum threshold
- AC12: No judgmental or guilt-inducing language in any nudge text
"""
from __future__ import annotations

import datetime

import pytest

from backend.services.habit_adherence import (
    compute_habit_adherence,
    FORBIDDEN_NUDGE_WORDS,
    MIN_HISTORY_DAYS,
)


TODAY = datetime.date(2026, 6, 24)  # Tuesday


# ─── Helpers ─────────────────────────────────────────────────────────────────

class _FakeHabit:
    """Minimal stand-in for a Habit ORM row."""
    def __init__(
        self,
        schedule_type="daily",
        schedule_target=None,
        habit_type="binary",
        target_value=None,
        name="Test Habit",
    ):
        self.schedule_type = schedule_type
        self.schedule_target = schedule_target
        self.habit_type = habit_type
        self.target_value = target_value
        self.name = name


class _FakeLog:
    """Minimal stand-in for a HabitLog ORM row."""
    def __init__(self, log_date: datetime.date, value=1):
        self.log_date = log_date
        self.value = value


def _daily_logs(today: datetime.date, days_back: int, skip_days: set[int] | None = None):
    """Return FakeLog list for `days_back` days, optionally skipping indices."""
    skip_days = skip_days or set()
    logs = []
    for i in range(days_back):
        d = today - datetime.timedelta(days=i)
        if i not in skip_days:
            logs.append(_FakeLog(d))
    return logs


# ─── AC1: Response shape ─────────────────────────────────────────────────────

class TestResponseShape:
    """compute_habit_adherence must always return all required keys."""

    REQUIRED_KEYS = {
        "habit_id",
        "habit_name",
        "met_count",
        "scheduled_count",
        "adherence_percent",
        "best_day",
        "worst_day",
        "trend",
        "nudge",
        "building",
    }

    def test_all_keys_present_with_full_history(self):
        """AC1: full history returns all required keys."""
        habit = _FakeHabit()
        logs = _daily_logs(TODAY, 28)
        result = compute_habit_adherence(habit, logs, today=TODAY, habit_id="abc")
        missing = self.REQUIRED_KEYS - result.keys()
        assert not missing, f"Missing keys: {missing}"

    def test_all_keys_present_with_no_logs(self):
        """AC1: zero logs returns all required keys (building state)."""
        habit = _FakeHabit()
        result = compute_habit_adherence(habit, [], today=TODAY, habit_id="abc")
        missing = self.REQUIRED_KEYS - result.keys()
        assert not missing, f"Missing keys: {missing}"

    def test_habit_id_preserved(self):
        """AC1: habit_id is passed through unchanged."""
        habit = _FakeHabit()
        result = compute_habit_adherence(habit, [], today=TODAY, habit_id="my-id-123")
        assert result["habit_id"] == "my-id-123"

    def test_habit_name_preserved(self):
        """AC1: habit_name matches the habit's name."""
        habit = _FakeHabit(name="Morning Run")
        result = compute_habit_adherence(habit, [], today=TODAY, habit_id="x")
        assert result["habit_name"] == "Morning Run"

    def test_adherence_percent_is_number(self):
        """AC1: adherence_percent is a numeric value."""
        habit = _FakeHabit()
        logs = _daily_logs(TODAY, 14)
        result = compute_habit_adherence(habit, logs, today=TODAY, habit_id="x")
        assert isinstance(result["adherence_percent"], (int, float))

    def test_trend_is_valid_string(self):
        """AC1: trend is one of 'stable' or 'declining'."""
        habit = _FakeHabit()
        logs = _daily_logs(TODAY, 14)
        result = compute_habit_adherence(habit, logs, today=TODAY, habit_id="x")
        assert result["trend"] in ("stable", "declining")

    def test_building_is_bool(self):
        """AC1: building is a boolean."""
        habit = _FakeHabit()
        result = compute_habit_adherence(habit, [], today=TODAY, habit_id="x")
        assert isinstance(result["building"], bool)


# ─── AC2: Weekly adherence counts ────────────────────────────────────────────

class TestWeeklyAdherence:
    """met_count and scheduled_count must reflect the 7-day window."""

    def test_perfect_week_met_count_equals_seven(self):
        """AC2: 7 logs in last 7 days → met_count=7, scheduled_count=7."""
        habit = _FakeHabit(schedule_type="daily")
        logs = _daily_logs(TODAY, 7)
        result = compute_habit_adherence(habit, logs, today=TODAY, habit_id="x")
        assert result["met_count"] == 7
        assert result["scheduled_count"] == 7

    def test_perfect_week_adherence_is_100(self):
        """AC2: 7/7 → adherence_percent=100."""
        habit = _FakeHabit(schedule_type="daily")
        logs = _daily_logs(TODAY, 7)
        result = compute_habit_adherence(habit, logs, today=TODAY, habit_id="x")
        assert result["adherence_percent"] == pytest.approx(100.0, abs=0.1)

    def test_five_of_seven_days_met(self):
        """AC2: 5/7 → met_count=5, scheduled_count=7, ~71%."""
        habit = _FakeHabit(schedule_type="daily")
        # Skip 2 days (indices 0 and 3 relative to today)
        logs = _daily_logs(TODAY, 7, skip_days={0, 3})
        result = compute_habit_adherence(habit, logs, today=TODAY, habit_id="x")
        assert result["met_count"] == 5
        assert result["scheduled_count"] == 7
        assert result["adherence_percent"] == pytest.approx(100 * 5 / 7, abs=0.1)

    def test_zero_logs_this_week_met_count_zero(self):
        """AC2: no logs this week → met_count=0."""
        habit = _FakeHabit(schedule_type="daily")
        # Logs from 14–8 days ago only (prior period, not current week)
        logs = [_FakeLog(TODAY - datetime.timedelta(days=d)) for d in range(8, 15)]
        result = compute_habit_adherence(habit, logs, today=TODAY, habit_id="x")
        assert result["met_count"] == 0
        assert result["scheduled_count"] == 7

    def test_extra_logs_outside_window_not_counted(self):
        """AC2: logs older than 7 days do not count toward met_count."""
        habit = _FakeHabit(schedule_type="daily")
        current_week = _daily_logs(TODAY, 7)
        old_logs = [_FakeLog(TODAY - datetime.timedelta(days=d)) for d in range(8, 22)]
        result = compute_habit_adherence(habit, current_week + old_logs, today=TODAY, habit_id="x")
        assert result["met_count"] == 7


# ─── AC3: Best-day and worst-day ─────────────────────────────────────────────

class TestBestWorstDay:
    """best_day / worst_day must be a day-of-week name string or null."""

    DAY_NAMES = {"Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"}

    def test_best_day_is_name_or_none(self):
        """AC3: best_day is a recognizable day name or None."""
        habit = _FakeHabit()
        logs = _daily_logs(TODAY, 28)
        result = compute_habit_adherence(habit, logs, today=TODAY, habit_id="x")
        assert result["best_day"] is None or result["best_day"] in self.DAY_NAMES

    def test_worst_day_is_name_or_none(self):
        """AC3: worst_day is a recognizable day name or None."""
        habit = _FakeHabit()
        logs = _daily_logs(TODAY, 28)
        result = compute_habit_adherence(habit, logs, today=TODAY, habit_id="x")
        assert result["worst_day"] is None or result["worst_day"] in self.DAY_NAMES

    def test_no_logs_best_worst_day_is_none(self):
        """AC3: with no logs, both indicators are null."""
        habit = _FakeHabit()
        result = compute_habit_adherence(habit, [], today=TODAY, habit_id="x")
        assert result["best_day"] is None
        assert result["worst_day"] is None

    def test_best_day_reflects_most_completed_day(self):
        """AC3: the day most frequently logged is returned as best_day."""
        # Monday (weekday=0) always logged over 4 weeks, other days only 1 week
        habit = _FakeHabit(schedule_type="daily")
        logs = []
        for week in range(4):
            monday = TODAY - datetime.timedelta(days=TODAY.weekday() + week * 7)
            logs.append(_FakeLog(monday))  # Monday every week
        # Only 1 log on each of Wednesday and Friday (once)
        wednesday = TODAY - datetime.timedelta(days=TODAY.weekday() - 2 + 7)
        friday = TODAY - datetime.timedelta(days=TODAY.weekday() - 4 + 7)
        logs.append(_FakeLog(wednesday))
        logs.append(_FakeLog(friday))
        result = compute_habit_adherence(habit, logs, today=TODAY, habit_id="x")
        assert result["best_day"] == "Monday"


# ─── AC4: Declining trend ────────────────────────────────────────────────────

class TestDecliningTrend:
    """A habit with worse current-week adherence vs prior week is trend='declining'."""

    def test_perfect_prior_zero_current_is_declining(self):
        """AC4: 7/7 prior, 0/7 current → trend='declining'."""
        habit = _FakeHabit(schedule_type="daily")
        # Prior period only (days 8–14 ago)
        logs = [_FakeLog(TODAY - datetime.timedelta(days=d)) for d in range(8, 15)]
        result = compute_habit_adherence(habit, logs, today=TODAY, habit_id="x")
        assert result["trend"] == "declining"

    def test_equal_adherence_is_stable(self):
        """AC4: same adherence both weeks → trend='stable'."""
        habit = _FakeHabit(schedule_type="daily")
        # 4/7 current, 4/7 prior
        logs = []
        for d in [0, 1, 2, 3]:
            logs.append(_FakeLog(TODAY - datetime.timedelta(days=d)))
        for d in [8, 9, 10, 11]:
            logs.append(_FakeLog(TODAY - datetime.timedelta(days=d)))
        result = compute_habit_adherence(habit, logs, today=TODAY, habit_id="x")
        assert result["trend"] == "stable"

    def test_improving_adherence_is_stable(self):
        """AC4: better current than prior → trend='stable' (not declining)."""
        habit = _FakeHabit(schedule_type="daily")
        # 0/7 prior, 7/7 current
        logs = _daily_logs(TODAY, 7)
        result = compute_habit_adherence(habit, logs, today=TODAY, habit_id="x")
        assert result["trend"] == "stable"

    def test_no_history_is_stable(self):
        """AC4: no prior history → trend defaults to 'stable'."""
        habit = _FakeHabit(schedule_type="daily")
        result = compute_habit_adherence(habit, [], today=TODAY, habit_id="x")
        assert result["trend"] == "stable"


# ─── AC6: Building empty state ───────────────────────────────────────────────

class TestBuildingState:
    """building=True when history is below minimum threshold."""

    def test_no_logs_returns_building_true(self):
        """AC6: zero logs → building=True."""
        habit = _FakeHabit()
        result = compute_habit_adherence(habit, [], today=TODAY, habit_id="x")
        assert result["building"] is True

    def test_enough_history_returns_building_false(self):
        """AC6: logs >= MIN_HISTORY_DAYS → building=False."""
        habit = _FakeHabit()
        logs = _daily_logs(TODAY, MIN_HISTORY_DAYS)
        result = compute_habit_adherence(habit, logs, today=TODAY, habit_id="x")
        assert result["building"] is False

    def test_below_threshold_returns_building_true(self):
        """AC6: fewer than MIN_HISTORY_DAYS logs → building=True."""
        habit = _FakeHabit()
        # One fewer than the minimum
        logs = _daily_logs(TODAY, MIN_HISTORY_DAYS - 1)
        result = compute_habit_adherence(habit, logs, today=TODAY, habit_id="x")
        assert result["building"] is True

    def test_building_nudge_is_warm_and_forward_looking(self):
        """AC6: building nudge must not be empty and must be warm/forward-looking."""
        habit = _FakeHabit()
        result = compute_habit_adherence(habit, [], today=TODAY, habit_id="x")
        assert result["nudge"]  # non-empty
        nudge = result["nudge"].lower()
        # Must not use forbidden language
        for word in FORBIDDEN_NUDGE_WORDS:
            assert word not in nudge, f"Forbidden word '{word}' in building nudge: {result['nudge']}"


# ─── AC12: No judgmental language ────────────────────────────────────────────

class TestNudgeTone:
    """No nudge must contain judgmental or guilt-inducing language."""

    _SCENARIOS = [
        ("perfect", _daily_logs(TODAY, 14)),
        ("declining", [_FakeLog(TODAY - datetime.timedelta(days=d)) for d in range(8, 15)]),
        ("zero_history", []),
        ("partial", _daily_logs(TODAY, 7, skip_days={0, 3, 5})),
    ]

    def _check_nudge(self, nudge):
        nudge_lower = nudge.lower()
        for word in FORBIDDEN_NUDGE_WORDS:
            assert word not in nudge_lower, (
                f"Forbidden word '{word}' found in nudge: {nudge!r}"
            )

    def test_nudge_never_contains_forbidden_words_in_any_scenario(self):
        """AC12: all nudge variants must be free of guilt-inducing language."""
        habit = _FakeHabit()
        for label, logs in self._SCENARIOS:
            result = compute_habit_adherence(habit, logs, today=TODAY, habit_id="x")
            self._check_nudge(result["nudge"])

    def test_nudge_is_never_empty_string(self):
        """AC12: nudge is always a non-empty string."""
        habit = _FakeHabit()
        for _, logs in self._SCENARIOS:
            result = compute_habit_adherence(habit, logs, today=TODAY, habit_id="x")
            assert isinstance(result["nudge"], str)
            assert result["nudge"].strip(), "nudge must not be empty"

    def test_forbidden_words_list_is_non_empty(self):
        """AC12: FORBIDDEN_NUDGE_WORDS must be populated (guard against empty set)."""
        assert len(FORBIDDEN_NUDGE_WORDS) >= 5


# ─── AC1: build_adherence_payload (top-level aggregator) ─────────────────────

class TestBuildAdherencePayload:
    """build_adherence_payload wraps per-habit results into the API response shape."""

    def test_imports_cleanly(self):
        """build_adherence_payload must be importable without side-effects."""
        from backend.services.habit_adherence import build_adherence_payload
        assert callable(build_adherence_payload)

    def test_empty_habits_returns_building_true(self):
        """AC6: no habits → top-level building=True."""
        from backend.services.habit_adherence import build_adherence_payload
        result = build_adherence_payload(habits=[], logs_by_habit={}, today=TODAY)
        assert result["building"] is True
        assert result["habits"] == []

    def test_response_top_level_keys(self):
        """AC1: response has building, habits, reason keys."""
        from backend.services.habit_adherence import build_adherence_payload
        result = build_adherence_payload(habits=[], logs_by_habit={}, today=TODAY)
        assert "building" in result
        assert "habits" in result
        assert "reason" in result

    def test_habits_list_populated(self):
        """AC1: each habit produces one entry in the habits list."""
        from backend.services.habit_adherence import build_adherence_payload
        habit = _FakeHabit()
        habit.id = "hab-001"
        habit.name = "Test"
        logs = _daily_logs(TODAY, MIN_HISTORY_DAYS)
        result = build_adherence_payload(
            habits=[habit],
            logs_by_habit={"hab-001": logs},
            today=TODAY,
        )
        assert len(result["habits"]) == 1
        assert result["habits"][0]["habit_id"] == "hab-001"

    def test_top_level_building_false_when_all_habits_have_enough_history(self):
        """AC6: all habits with sufficient history → top-level building=False."""
        from backend.services.habit_adherence import build_adherence_payload
        habit = _FakeHabit()
        habit.id = "h1"
        logs = _daily_logs(TODAY, MIN_HISTORY_DAYS)
        result = build_adherence_payload(
            habits=[habit],
            logs_by_habit={"h1": logs},
            today=TODAY,
        )
        assert result["building"] is False
