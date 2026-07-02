"""Unit tests for build_nudges pure function (issue #886).

Each test is anchored to one Acceptance Criterion or UAT test step.
All tests are pure — no DB access, no network calls.

AC inventory:
  AC1  pure function — no I/O, no side effects
  AC2  accepts adherence_breakdowns and slipping_habits
  AC3  returns dict with 'nudges' (list) and 'debug' (dict)
  AC4  nudge count capped at MAXIMUM_NUDGES
  AC5  None or empty inputs -> {nudges:[], debug:{reason: ...}}
  AC6  weekday-pattern nudges from adherence_breakdowns
  AC7  slipping nudges use plain-language percentage words
  AC8  neutral, non-judgmental tone (no shame/blame/urgency)
  AC9  docstring with two worked examples
  AC10 all logic paths covered by unit tests
  AC11 math in words ("fifty percent", not "50%")
"""

from __future__ import annotations

import re
import pytest

from backend.services.habit_nudges import MAXIMUM_NUDGES, build_nudges


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _breakdowns_with_friday_dip(habit_name="Morning Run"):
    """Adherence breakdown where Friday is materially below the weekly average."""
    return {
        habit_name: {
            "weekday_pct": {
                0: 85.0,   # Monday
                1: 82.0,   # Tuesday
                2: 88.0,   # Wednesday
                3: 80.0,   # Thursday
                4: 15.0,   # Friday — way below average
                5: 90.0,   # Saturday
                6: 84.0,   # Sunday
            },
            "overall_avg": 74.9,
        }
    }


def _slipping_habit(name="Meditation", prev=90.0, current=50.0):
    return {"name": name, "prev_percent": prev, "current_percent": current}


def _slipping_list(*items):
    return list(items)


# ---------------------------------------------------------------------------
# AC2+AC3: import and basic shape
# ---------------------------------------------------------------------------

class TestImportAndShape:
    def test_importable(self):
        """build_nudges and MAXIMUM_NUDGES are importable."""
        from backend.services.habit_nudges import build_nudges, MAXIMUM_NUDGES  # noqa: F401

    def test_returns_dict_with_two_keys(self):
        """AC3: result is a dict with exactly 'nudges' and 'debug' keys."""
        result = build_nudges({}, [])
        assert isinstance(result, dict)
        assert "nudges" in result
        assert "debug" in result

    def test_nudges_is_list(self):
        """AC3: 'nudges' value is a list."""
        result = build_nudges({}, [])
        assert isinstance(result["nudges"], list)

    def test_debug_is_dict(self):
        """AC3: 'debug' value is a dict."""
        result = build_nudges({}, [])
        assert isinstance(result["debug"], dict)


# ---------------------------------------------------------------------------
# AC5: empty / None inputs
# ---------------------------------------------------------------------------

class TestEmptyAndNoneInputs:
    def test_both_empty_returns_empty_nudges(self):
        """UAT 1: build_nudges({}, []) returns nudges=[]."""
        result = build_nudges({}, [])
        assert result["nudges"] == []

    def test_both_empty_has_descriptive_reason(self):
        """UAT 1: debug.reason must mention 'no adherence data provided'."""
        result = build_nudges({}, [])
        assert result["debug"].get("reason") == "no adherence data provided"

    def test_none_inputs_returns_empty_nudges(self):
        """UAT 2: build_nudges(None, None) returns nudges=[]."""
        result = build_nudges(None, None)
        assert result["nudges"] == []

    def test_none_inputs_has_reason(self):
        """UAT 2: debug.reason must be 'inputs were None'."""
        result = build_nudges(None, None)
        assert result["debug"].get("reason") == "inputs were None"

    def test_empty_breakdowns_nonempty_slipping(self):
        """Empty breakdowns with slipping habits still works."""
        result = build_nudges({}, [_slipping_habit()])
        # slipping habit should still produce a nudge
        assert isinstance(result["nudges"], list)

    def test_nonempty_breakdowns_empty_slipping(self):
        """Non-empty breakdowns with empty slipping list still works."""
        result = build_nudges(_breakdowns_with_friday_dip(), [])
        assert isinstance(result["nudges"], list)


# ---------------------------------------------------------------------------
# AC6 + AC11: weekday-pattern nudges
# ---------------------------------------------------------------------------

class TestWeekdayPatternNudges:
    def test_friday_dip_emits_nudge_mentioning_fridays(self):
        """UAT 3: a Friday dip produces a nudge that mentions 'Fridays'."""
        result = build_nudges(_breakdowns_with_friday_dip(), [])
        nudge_text = " ".join(result["nudges"])
        assert "friday" in nudge_text.lower()

    def test_weekday_nudge_contains_habit_name(self):
        """UAT 3: the weekday nudge references the habit name."""
        result = build_nudges(_breakdowns_with_friday_dip("Morning Run"), [])
        nudge_text = " ".join(result["nudges"])
        assert "morning run" in nudge_text.lower()

    def test_no_raw_numbers_in_weekday_nudge(self):
        """AC11: no bare digits (like 15, 74) appear in nudge strings."""
        result = build_nudges(_breakdowns_with_friday_dip(), [])
        for nudge in result["nudges"]:
            assert not re.search(r"\b\d+\b", nudge), (
                f"Raw number found in nudge: {nudge!r}"
            )

    def test_no_percentage_sign_in_weekday_nudge(self):
        """AC11: no '%' character appears in nudge strings."""
        result = build_nudges(_breakdowns_with_friday_dip(), [])
        for nudge in result["nudges"]:
            assert "%" not in nudge, f"Percent sign found in nudge: {nudge!r}"

    def test_debug_records_friday_signal(self):
        """UAT 3: debug records the Friday-dip signal."""
        result = build_nudges(_breakdowns_with_friday_dip(), [])
        debug_str = str(result["debug"]).lower()
        assert "friday" in debug_str or "weekday" in debug_str

    def test_no_weekday_nudge_when_all_days_equal(self):
        """No weekday nudge when adherence is uniform across all days."""
        flat = {
            "Even Habit": {
                "weekday_pct": {i: 75.0 for i in range(7)},
                "overall_avg": 75.0,
            }
        }
        result = build_nudges(flat, [])
        nudge_text = " ".join(result["nudges"])
        # No weekday should appear
        for day in ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]:
            assert day not in nudge_text.lower()

    def test_exactly_one_nudge_for_single_friday_dip(self):
        """UAT 3: exactly one nudge for a single habit with one dip day."""
        result = build_nudges(_breakdowns_with_friday_dip(), [])
        assert len(result["nudges"]) == 1


# ---------------------------------------------------------------------------
# AC7 + AC11: slipping-habit nudges
# ---------------------------------------------------------------------------

class TestSlippingNudges:
    def test_slipping_nudge_contains_ninety_and_fifty(self):
        """UAT 4: a 90→50 slip uses 'ninety' and 'fifty'."""
        result = build_nudges({}, [_slipping_habit(prev=90.0, current=50.0)])
        nudge_text = " ".join(result["nudges"])
        assert "ninety" in nudge_text.lower()
        assert "fifty" in nudge_text.lower()

    def test_slipping_nudge_no_raw_numbers(self):
        """AC11: no bare digits in slipping nudge strings."""
        result = build_nudges({}, [_slipping_habit(prev=90.0, current=50.0)])
        for nudge in result["nudges"]:
            assert not re.search(r"\b\d+\b", nudge), (
                f"Raw number found in nudge: {nudge!r}"
            )

    def test_slipping_nudge_no_percentage_sign(self):
        """AC11: no '%' character in slipping nudges."""
        result = build_nudges({}, [_slipping_habit(prev=90.0, current=50.0)])
        for nudge in result["nudges"]:
            assert "%" not in nudge

    def test_slipping_nudge_contains_habit_name(self):
        """Slipping nudge must name the habit."""
        result = build_nudges({}, [_slipping_habit("Meditation")])
        nudge_text = " ".join(result["nudges"])
        assert "meditation" in nudge_text.lower()

    def test_debug_records_slipping_signal(self):
        """UAT 4: debug records the before/after values for the slipping habit."""
        result = build_nudges({}, [_slipping_habit(prev=90.0, current=50.0)])
        debug_str = str(result["debug"]).lower()
        assert "slip" in debug_str or "prev" in debug_str or "current" in debug_str

    def test_exactly_one_nudge_for_single_slipping_habit(self):
        """UAT 4: one slipping habit → exactly one nudge."""
        result = build_nudges({}, [_slipping_habit()])
        assert len(result["nudges"]) == 1


# ---------------------------------------------------------------------------
# AC4: MAXIMUM_NUDGES cap
# ---------------------------------------------------------------------------

class TestMaximumNudgesCap:
    def _over_cap_inputs(self):
        """Return inputs that would generate more candidates than MAXIMUM_NUDGES."""
        n = MAXIMUM_NUDGES + 5
        # Each habit gets a severe Friday dip
        breakdowns = {}
        for i in range(n):
            breakdowns[f"Habit{i}"] = {
                "weekday_pct": {
                    0: 80.0, 1: 82.0, 2: 85.0, 3: 78.0,
                    4: 5.0,  # severe Friday dip
                    5: 88.0, 6: 84.0,
                },
                "overall_avg": 71.7,
            }
        slipping = [_slipping_habit(name=f"SlipHabit{i}") for i in range(n)]
        return breakdowns, slipping

    def test_never_exceeds_maximum_nudges(self):
        """UAT 5: len(nudges) never exceeds MAXIMUM_NUDGES."""
        breakdowns, slipping = self._over_cap_inputs()
        result = build_nudges(breakdowns, slipping)
        assert len(result["nudges"]) <= MAXIMUM_NUDGES

    def test_exactly_maximum_when_over_cap(self):
        """UAT 5: exactly MAXIMUM_NUDGES nudges when inputs generate more."""
        breakdowns, slipping = self._over_cap_inputs()
        result = build_nudges(breakdowns, slipping)
        assert len(result["nudges"]) == MAXIMUM_NUDGES

    def test_debug_records_omitted_nudges(self):
        """UAT 5: debug lists which nudges were omitted when cap is reached."""
        breakdowns, slipping = self._over_cap_inputs()
        result = build_nudges(breakdowns, slipping)
        debug_str = str(result["debug"]).lower()
        assert "omit" in debug_str or "cap" in debug_str or "truncat" in debug_str

    def test_maximum_nudges_is_named_constant(self):
        """AC4: MAXIMUM_NUDGES is a module-level constant (not a magic number)."""
        assert isinstance(MAXIMUM_NUDGES, int)
        assert MAXIMUM_NUDGES > 0


# ---------------------------------------------------------------------------
# AC6 + AC7: mixed signals (both nudge types)
# ---------------------------------------------------------------------------

class TestMixedSignals:
    def test_both_nudge_types_under_cap(self):
        """UAT 6: weekday + slipping nudges both appear when total < cap."""
        result = build_nudges(
            _breakdowns_with_friday_dip("Morning Run"),
            [_slipping_habit("Meditation", prev=90.0, current=50.0)],
        )
        nudge_text = " ".join(result["nudges"]).lower()
        assert "friday" in nudge_text
        assert "meditation" in nudge_text
        assert len(result["nudges"]) == 2

    def test_no_raw_numbers_in_mixed_nudges(self):
        """AC11: no bare digits in any nudge when both types appear."""
        result = build_nudges(
            _breakdowns_with_friday_dip(),
            [_slipping_habit()],
        )
        for nudge in result["nudges"]:
            assert not re.search(r"\b\d+\b", nudge)

    def test_no_shame_or_urgency_language(self):
        """AC8: shame/blame/urgency keywords must not appear in nudge strings."""
        bad_words = ["fail", "shame", "lazy", "bad", "disappointing", "urgent", "must", "should"]
        result = build_nudges(
            _breakdowns_with_friday_dip(),
            [_slipping_habit()],
        )
        for nudge in result["nudges"]:
            for word in bad_words:
                assert word not in nudge.lower(), (
                    f"Shame/urgency word '{word}' found in nudge: {nudge!r}"
                )


# ---------------------------------------------------------------------------
# AC1: purity — deterministic, no side effects
# ---------------------------------------------------------------------------

class TestPurity:
    def test_two_identical_calls_return_equal_results(self):
        """UAT 7: identical inputs always produce identical outputs."""
        breakdowns = _breakdowns_with_friday_dip()
        slipping = [_slipping_habit()]
        r1 = build_nudges(breakdowns, slipping)
        r2 = build_nudges(breakdowns, slipping)
        assert r1 == r2

    def test_inputs_not_mutated(self):
        """AC1: function does not mutate input dicts or lists."""
        breakdowns = _breakdowns_with_friday_dip("Running")
        slipping = [_slipping_habit("Yoga")]
        import copy
        b_copy = copy.deepcopy(breakdowns)
        s_copy = copy.deepcopy(slipping)
        build_nudges(breakdowns, slipping)
        assert breakdowns == b_copy
        assert slipping == s_copy


# ---------------------------------------------------------------------------
# AC9: docstring examples
# ---------------------------------------------------------------------------

class TestDocstring:
    def test_docstring_exists(self):
        """AC9: build_nudges has a non-empty docstring."""
        from backend.services.habit_nudges import build_nudges
        assert build_nudges.__doc__ and len(build_nudges.__doc__.strip()) > 50

    def test_docstring_has_two_examples(self):
        """AC9: docstring contains at least two worked examples."""
        from backend.services.habit_nudges import build_nudges
        doc = build_nudges.__doc__
        # Look for 'Example' or code-style blocks as evidence of examples
        example_count = doc.lower().count("example")
        assert example_count >= 2, (
            f"Expected at least 2 worked examples in docstring, found {example_count}"
        )


# ---------------------------------------------------------------------------
# AC7: percentage word conversion
# ---------------------------------------------------------------------------

class TestPercentageWords:
    @pytest.mark.parametrize("prev,current,prev_word,curr_word", [
        (80.0, 40.0, "eighty", "forty"),
        (70.0, 30.0, "seventy", "thirty"),
        (100.0, 60.0, "one hundred", "sixty"),
        (90.0, 10.0, "ninety", "ten"),
    ])
    def test_various_percentages_become_words(self, prev, current, prev_word, curr_word):
        """AC7+AC11: various rounded percentages become plain English words."""
        result = build_nudges({}, [_slipping_habit(prev=prev, current=current)])
        nudge_text = " ".join(result["nudges"]).lower()
        assert prev_word in nudge_text, f"Expected '{prev_word}' in: {nudge_text!r}"
        assert curr_word in nudge_text, f"Expected '{curr_word}' in: {nudge_text!r}"
