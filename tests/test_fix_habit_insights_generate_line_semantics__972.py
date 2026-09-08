"""Tests for issue #972: Fix semantic mismatch in habit_insights._generate_line.

Acceptance criteria:
- AC1: _generate_line must NOT produce "on track" phrasing (which implies
       progress-vs-target), because correlation insights are associative, not
       goal-tracking.
- AC2: Output must use correlation/associative language (e.g. "associated with").
- AC3: correlation_line_builder is added to coaching_voice.py as the canonical
       builder for correlation-style insights.
- AC4: correlation_line_builder output never contains "on track".
- AC5: correlation_line_builder output contains "associated with".
- AC6: All four direction cases (same-day positive, same-day negative,
       lagged positive, lagged negative) produce semantically correct copy.
- AC7: _generate_line delegates to correlation_line_builder (not praise_line_builder).
"""

from __future__ import annotations

import pytest

from backend.services.habit_insights import _generate_line
import backend.services.coaching_voice as coaching_voice


# ---------------------------------------------------------------------------
# AC1: _generate_line must NOT say "on track"
# ---------------------------------------------------------------------------


class TestNoOnTrackPhrasing:
    def test_same_day_positive_no_on_track(self):
        line = _generate_line("Morning Run", "energy", 0.6, lag_days=0)
        assert "on track" not in line.lower(), (
            f"'on track' is progress-tracking language, not correlation: {line!r}"
        )

    def test_same_day_negative_no_on_track(self):
        line = _generate_line("Night Screen", "sleep_quality", -0.5, lag_days=0)
        assert "on track" not in line.lower()

    def test_lagged_positive_no_on_track(self):
        line = _generate_line("Morning Run", "hrv", 0.4, lag_days=1)
        assert "on track" not in line.lower()

    def test_lagged_negative_no_on_track(self):
        line = _generate_line("Alcohol", "mood", -0.3, lag_days=2)
        assert "on track" not in line.lower()


# ---------------------------------------------------------------------------
# AC2: Output uses associative language ("associated with")
# ---------------------------------------------------------------------------


class TestAssociativeLanguage:
    def test_same_day_positive_uses_associated_with(self):
        line = _generate_line("Morning Run", "energy", 0.6, lag_days=0)
        assert "associated with" in line.lower(), (
            f"Correlation insight must use associative language: {line!r}"
        )

    def test_same_day_negative_uses_associated_with(self):
        line = _generate_line("Night Screen", "sleep_quality", -0.5, lag_days=0)
        assert "associated with" in line.lower()

    def test_lagged_positive_uses_associated_with(self):
        line = _generate_line("Morning Run", "hrv", 0.4, lag_days=1)
        assert "associated with" in line.lower()

    def test_lagged_negative_uses_associated_with(self):
        line = _generate_line("Alcohol", "mood", -0.3, lag_days=2)
        assert "associated with" in line.lower()


# ---------------------------------------------------------------------------
# AC3 / AC4 / AC5: correlation_line_builder exists in coaching_voice
# ---------------------------------------------------------------------------


class TestCorrelationLineBuilder:
    def test_correlation_line_builder_exists(self):
        assert hasattr(coaching_voice, "correlation_line_builder"), (
            "coaching_voice must export correlation_line_builder"
        )

    def test_correlation_line_builder_callable(self):
        assert callable(coaching_voice.correlation_line_builder)

    def test_no_on_track_positive(self):
        line = coaching_voice.correlation_line_builder(
            habit_name="Morning Run",
            label="Energy",
            context="associated with higher 'Energy' scores on the same day",
        )
        assert "on track" not in line.lower()

    def test_no_on_track_negative(self):
        line = coaching_voice.correlation_line_builder(
            habit_name="Night Screen",
            label="Sleep Quality",
            context="associated with lower 'Sleep Quality' scores on the same day",
        )
        assert "on track" not in line.lower()

    def test_contains_associated_with_positive(self):
        line = coaching_voice.correlation_line_builder(
            habit_name="Morning Run",
            label="Energy",
            context="associated with higher 'Energy' scores on the same day",
        )
        assert "associated with" in line.lower()

    def test_contains_associated_with_negative(self):
        line = coaching_voice.correlation_line_builder(
            habit_name="Night Screen",
            label="Sleep Quality",
            context="associated with lower 'Sleep Quality' scores on the same day",
        )
        assert "associated with" in line.lower()

    def test_contains_habit_name(self):
        line = coaching_voice.correlation_line_builder(
            habit_name="Morning Run",
            label="Energy",
            context="associated with higher 'Energy' scores on the same day",
        )
        assert "Morning Run" in line

    def test_deterministic(self):
        """Same inputs always produce the same output."""
        kwargs = dict(
            habit_name="Morning Run",
            label="Energy",
            context="associated with higher 'Energy' scores on the same day",
        )
        assert coaching_voice.correlation_line_builder(**kwargs) == coaching_voice.correlation_line_builder(**kwargs)

    def test_no_exclamation_marks(self):
        line = coaching_voice.correlation_line_builder(
            habit_name="Morning Run",
            label="Energy",
            context="associated with higher 'Energy' scores on the same day",
        )
        assert "!" not in line

    def test_no_emoji(self):
        line = coaching_voice.correlation_line_builder(
            habit_name="Morning Run",
            label="Energy",
            context="associated with higher 'Energy' scores on the same day",
        )
        for ch in line:
            code = ord(ch)
            assert code < 0x1F600 or code > 0x1F64F, f"emoji found in line: {line!r}"


# ---------------------------------------------------------------------------
# AC6: All four direction cases produce correct copy
# ---------------------------------------------------------------------------


class TestDirectionCases:
    def test_same_day_positive_says_higher(self):
        line = _generate_line("Morning Run", "energy", 0.5, lag_days=0)
        assert "higher" in line.lower()

    def test_same_day_negative_says_lower(self):
        line = _generate_line("Night Screen", "sleep_quality", -0.4, lag_days=0)
        assert "lower" in line.lower()

    def test_lagged_positive_says_higher(self):
        line = _generate_line("Morning Run", "hrv", 0.4, lag_days=1)
        assert "higher" in line.lower()

    def test_lagged_negative_says_lower(self):
        line = _generate_line("Alcohol", "mood", -0.3, lag_days=2)
        assert "lower" in line.lower()

    def test_same_day_mentions_same_day(self):
        line = _generate_line("Morning Run", "energy", 0.5, lag_days=0)
        assert "same day" in line.lower()

    def test_lag_1_mentions_1_day_later(self):
        line = _generate_line("Morning Run", "energy", 0.5, lag_days=1)
        assert "1 day later" in line

    def test_lag_2_mentions_2_days_later(self):
        line = _generate_line("Morning Run", "energy", 0.5, lag_days=2)
        assert "2 days later" in line


# ---------------------------------------------------------------------------
# AC7: _generate_line uses correlation_line_builder (not praise_line_builder)
# ---------------------------------------------------------------------------


class TestDelegationToCorrelationBuilder:
    def test_generate_line_uses_correlation_builder(self, monkeypatch):
        """_generate_line must call correlation_line_builder, not praise_line_builder."""
        praise_calls = []
        correlation_calls = []

        monkeypatch.setattr(
            coaching_voice,
            "praise_line_builder",
            lambda *a, **kw: praise_calls.append((a, kw)) or "praise",
        )
        monkeypatch.setattr(
            coaching_voice,
            "correlation_line_builder",
            lambda *a, **kw: correlation_calls.append((a, kw)) or "correlation",
        )

        _generate_line("Morning Run", "energy", 0.5, lag_days=0)

        assert len(correlation_calls) == 1, (
            "_generate_line must call correlation_line_builder exactly once"
        )
        assert len(praise_calls) == 0, (
            "_generate_line must not call praise_line_builder (wrong semantic)"
        )
