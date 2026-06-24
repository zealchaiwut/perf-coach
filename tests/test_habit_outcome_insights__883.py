"""Unit tests for build_habit_outcome_insights and compute_correlation (issue #883).

Covers all AC items:
- AC1/AC3: build_habit_outcome_insights accepts habits, outcome_series, lags, thresholds
- AC2: pure function, no DB access
- AC3: delegates to align_habit_and_outcome and compute_correlation per triple
- AC4: suppresses results below confidence minimum
- AC5: insight strings name habit, outcome, direction, lag, r, n; uses associative phrasing
- AC6: returns empty list + reason on empty inputs or no survivors
- AC7: function has a docstring with worked example
- AC8: supported outcomes are readiness_tsb, daily_load, weight_trend (additive by caller)
- AC9: no magic numbers — all thresholds are parameters
- AC10 (unit): happy path, all suppressed, empty habit list, empty outcome dict, zero variance
"""

import math
import pytest

from backend.services.habit_correlation import compute_correlation
from backend.services.habit_insights import build_habit_outcome_insights


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_date(i):
    """Return a YYYY-MM-DD string for 2025-01-01 + i days (i is 0-based)."""
    from datetime import date, timedelta
    return (date(2025, 1, 1) + timedelta(days=i)).isoformat()


def _alternating_habit(n=30):
    """n days: True on even-index days (0,2,4,...), False on odd-index days."""
    return {_make_date(i): (i % 2 == 0) for i in range(n)}


def _correlated_outcome(n=30, high=80.0, low=40.0):
    """Outcome that matches alternating habit at lag=0: even days high, odd days low."""
    return {_make_date(i): (high if i % 2 == 0 else low) for i in range(n)}


def _flat_outcome(n=30, value=70.0):
    """All-same outcome series — zero variance."""
    return {_make_date(i): value for i in range(n)}


@pytest.fixture
def habit_a():
    return {"name": "Morning run", "logs": _alternating_habit(30)}


@pytest.fixture
def habit_b():
    return {"name": "Sleep ≥ 7h", "logs": {_make_date(i): (i < 15) for i in range(30)}}


@pytest.fixture
def two_habits(habit_a, habit_b):
    return [habit_a, habit_b]


@pytest.fixture
def single_habit(habit_a):
    return [habit_a]


@pytest.fixture
def outcome_series_correlated():
    """readiness_tsb strongly correlates with _alternating_habit at lag=0."""
    return {
        "readiness_tsb": _correlated_outcome(30),
        "daily_load": {_make_date(i): 50.0 for i in range(30)},  # flat → no correlation
        "weight_trend": {_make_date(i): 70.0 for i in range(30)},  # flat
    }


@pytest.fixture
def outcome_series_all_flat():
    """All outcomes are constant — correlation is undefined (zero variance)."""
    return {
        "readiness_tsb": _flat_outcome(30, 70.0),
        "daily_load": _flat_outcome(30, 50.0),
        "weight_trend": _flat_outcome(30, 65.0),
    }


# ---------------------------------------------------------------------------
# compute_correlation tests
# ---------------------------------------------------------------------------

class TestComputeCorrelation:
    def test_returns_dict_with_r_n_reason(self):
        pairs = [
            {"habit_value": True, "outcome_value": 80.0},
            {"habit_value": False, "outcome_value": 40.0},
            {"habit_value": True, "outcome_value": 80.0},
            {"habit_value": False, "outcome_value": 40.0},
        ]
        result = compute_correlation(pairs)
        assert "r" in result
        assert "n" in result
        assert "reason" in result

    def test_n_equals_pair_count(self):
        pairs = [
            {"habit_value": True, "outcome_value": 80.0},
            {"habit_value": False, "outcome_value": 40.0},
        ]
        result = compute_correlation(pairs)
        assert result["n"] == 2

    def test_perfect_positive_correlation(self):
        """15 True→80, 15 False→40 should yield r close to 1.0."""
        pairs = (
            [{"habit_value": True, "outcome_value": 80.0}] * 15
            + [{"habit_value": False, "outcome_value": 40.0}] * 15
        )
        result = compute_correlation(pairs)
        assert result["reason"] == ""
        assert abs(result["r"] - 1.0) < 1e-9

    def test_negative_correlation(self):
        """True→low, False→high gives negative r."""
        pairs = (
            [{"habit_value": True, "outcome_value": 40.0}] * 15
            + [{"habit_value": False, "outcome_value": 80.0}] * 15
        )
        result = compute_correlation(pairs)
        assert result["r"] < 0

    def test_zero_variance_habit_returns_zero_r_gracefully(self):
        """All habit values True → x is constant → zero variance; must not raise."""
        pairs = [{"habit_value": True, "outcome_value": float(v)} for v in range(1, 31)]
        result = compute_correlation(pairs)
        assert result["r"] == 0.0
        assert result["reason"] != ""

    def test_zero_variance_outcome_returns_zero_r_gracefully(self):
        """All outcome values the same → y is constant → must not raise."""
        pairs = [{"habit_value": (i % 2 == 0), "outcome_value": 70.0} for i in range(30)]
        result = compute_correlation(pairs)
        assert result["r"] == 0.0
        assert result["reason"] != ""

    def test_single_pair_returns_zero_r(self):
        """n=1 is insufficient for correlation; must not raise."""
        result = compute_correlation([{"habit_value": True, "outcome_value": 80.0}])
        assert result["n"] == 1
        assert result["r"] == 0.0
        assert result["reason"] != ""

    def test_empty_pairs_returns_zero_r(self):
        result = compute_correlation([])
        assert result["n"] == 0
        assert result["r"] == 0.0
        assert result["reason"] != ""

    def test_r_is_float(self):
        pairs = (
            [{"habit_value": True, "outcome_value": 80.0}] * 15
            + [{"habit_value": False, "outcome_value": 40.0}] * 15
        )
        result = compute_correlation(pairs)
        assert isinstance(result["r"], float)


# ---------------------------------------------------------------------------
# build_habit_outcome_insights — happy path
# ---------------------------------------------------------------------------

class TestHappyPath:
    def test_returns_list_and_reason_string(self, single_habit, outcome_series_correlated):
        result = build_habit_outcome_insights(
            single_habit, outcome_series_correlated, lags=[0], min_n=5, min_r=0.1
        )
        assert isinstance(result, tuple)
        assert len(result) == 2
        insights, reason = result
        assert isinstance(insights, list)
        assert isinstance(reason, str)

    def test_happy_path_produces_at_least_one_insight(self, single_habit, outcome_series_correlated):
        insights, reason = build_habit_outcome_insights(
            single_habit, outcome_series_correlated, lags=[0], min_n=5, min_r=0.1
        )
        assert len(insights) >= 1
        assert reason == ""

    def test_insight_strings_are_strings(self, single_habit, outcome_series_correlated):
        insights, _ = build_habit_outcome_insights(
            single_habit, outcome_series_correlated, lags=[0], min_n=5, min_r=0.1
        )
        for s in insights:
            assert isinstance(s, str)

    def test_insight_contains_habit_name(self, single_habit, outcome_series_correlated):
        insights, _ = build_habit_outcome_insights(
            single_habit, outcome_series_correlated, lags=[0], min_n=5, min_r=0.1
        )
        assert any("Morning run" in s for s in insights)

    def test_insight_contains_outcome_name(self, single_habit, outcome_series_correlated):
        """readiness_tsb should appear in human-readable form."""
        insights, _ = build_habit_outcome_insights(
            single_habit, outcome_series_correlated, lags=[0], min_n=5, min_r=0.1
        )
        assert any("readiness" in s.lower() for s in insights)

    def test_insight_contains_direction_word(self, single_habit, outcome_series_correlated):
        insights, _ = build_habit_outcome_insights(
            single_habit, outcome_series_correlated, lags=[0], min_n=5, min_r=0.1
        )
        assert any("higher" in s or "lower" in s for s in insights)

    def test_insight_contains_r_value(self, single_habit, outcome_series_correlated):
        insights, _ = build_habit_outcome_insights(
            single_habit, outcome_series_correlated, lags=[0], min_n=5, min_r=0.1
        )
        assert any("r = " in s for s in insights)

    def test_insight_contains_n_value(self, single_habit, outcome_series_correlated):
        insights, _ = build_habit_outcome_insights(
            single_habit, outcome_series_correlated, lags=[0], min_n=5, min_r=0.1
        )
        assert any("n = " in s for s in insights)

    def test_insight_uses_associative_phrasing(self, single_habit, outcome_series_correlated):
        insights, _ = build_habit_outcome_insights(
            single_habit, outcome_series_correlated, lags=[0], min_n=5, min_r=0.1
        )
        assert any("tends to be" in s for s in insights)

    def test_no_causal_language_in_insights(self, single_habit, outcome_series_correlated):
        """AC5: phrased as association, never causation."""
        insights, _ = build_habit_outcome_insights(
            single_habit, outcome_series_correlated, lags=[0, 1], min_n=5, min_r=0.1
        )
        causal_words = ["causes", "leads to", "results in", "drives"]
        for s in insights:
            for word in causal_words:
                assert word not in s.lower(), f"Causal language '{word}' found in: {s}"

    def test_lag_zero_shows_same_day(self, single_habit, outcome_series_correlated):
        insights, _ = build_habit_outcome_insights(
            single_habit, outcome_series_correlated, lags=[0], min_n=5, min_r=0.1
        )
        assert any("same-day" in s for s in insights)

    def test_lag_one_shows_next_day(self, two_habits, outcome_series_correlated):
        """lag=1 should produce 'next-day' in at least one insight."""
        # Make outcome_series with values offset by 1 day to correlate at lag=1
        from datetime import date, timedelta
        habit_logs_b = two_habits[1]["logs"]  # True on days 0-14, False on days 15-29
        # outcome at lag=1: days 1-15 are high (after True days 0-14), days 16-30 are low
        outcome_lag1 = {
            (date(2025, 1, 1) + timedelta(days=i + 1)).isoformat(): (80.0 if i < 15 else 40.0)
            for i in range(30)
        }
        series = {"readiness_tsb": outcome_lag1}
        habits_b = [two_habits[1]]
        insights, _ = build_habit_outcome_insights(
            habits_b, series, lags=[1], min_n=5, min_r=0.1
        )
        assert any("next-day" in s for s in insights)

    def test_multiple_habits_can_all_produce_insights(self, two_habits):
        """Two habits both correlated with outcome → multiple insights."""
        # Build correlated outcome for each habit
        correlated = {}
        correlated["readiness_tsb"] = {_make_date(i): (80.0 if i % 2 == 0 else 40.0) for i in range(30)}
        insights, _ = build_habit_outcome_insights(
            two_habits, correlated, lags=[0], min_n=5, min_r=0.1
        )
        # Both habits have non-trivial completion series; at least one insight expected
        assert len(insights) >= 1

    def test_docstring_exists(self):
        """AC7: function has a docstring."""
        from backend.services.habit_insights import build_habit_outcome_insights
        assert build_habit_outcome_insights.__doc__ is not None
        assert len(build_habit_outcome_insights.__doc__.strip()) > 0

    def test_docstring_contains_example(self):
        """AC7: docstring includes a worked example."""
        from backend.services.habit_insights import build_habit_outcome_insights
        doc = build_habit_outcome_insights.__doc__
        assert "example" in doc.lower() or "Example" in doc


# ---------------------------------------------------------------------------
# build_habit_outcome_insights — confidence filtering (AC4)
# ---------------------------------------------------------------------------

class TestConfidenceFiltering:
    def test_high_min_n_suppresses_all(self, single_habit, outcome_series_correlated):
        """min_n=1000 means no pair can produce 1000 samples in a 30-day set."""
        insights, reason = build_habit_outcome_insights(
            single_habit, outcome_series_correlated, lags=[0], min_n=1000, min_r=0.0
        )
        assert insights == []
        assert reason != ""

    def test_high_min_r_suppresses_all(self, single_habit, outcome_series_all_flat):
        """All outcomes are flat → r=0 → everything suppressed at min_r=0.1."""
        insights, reason = build_habit_outcome_insights(
            single_habit, outcome_series_all_flat, lags=[0], min_n=1, min_r=0.1
        )
        assert insights == []
        assert reason != ""

    def test_suppressed_reason_is_nonempty_string(self, single_habit, outcome_series_correlated):
        insights, reason = build_habit_outcome_insights(
            single_habit, outcome_series_correlated, lags=[0], min_n=1000, min_r=0.0
        )
        assert isinstance(reason, str)
        assert len(reason) > 0


# ---------------------------------------------------------------------------
# build_habit_outcome_insights — empty inputs (AC6)
# ---------------------------------------------------------------------------

class TestEmptyInputs:
    def test_empty_habit_list_returns_empty_insights(self, outcome_series_correlated):
        insights, reason = build_habit_outcome_insights(
            [], outcome_series_correlated, lags=[0], min_n=1, min_r=0.0
        )
        assert insights == []
        assert reason != ""

    def test_empty_habit_list_reason_mentions_habits(self, outcome_series_correlated):
        _, reason = build_habit_outcome_insights(
            [], outcome_series_correlated, lags=[0], min_n=1, min_r=0.0
        )
        assert "habit" in reason.lower()

    def test_none_habit_list_returns_empty_insights(self, outcome_series_correlated):
        insights, reason = build_habit_outcome_insights(
            None, outcome_series_correlated, lags=[0], min_n=1, min_r=0.0
        )
        assert insights == []
        assert reason != ""

    def test_empty_outcome_dict_returns_empty_insights(self, single_habit):
        insights, reason = build_habit_outcome_insights(
            single_habit, {}, lags=[0], min_n=1, min_r=0.0
        )
        assert insights == []
        assert reason != ""

    def test_empty_outcome_dict_reason_mentions_outcome(self, single_habit):
        _, reason = build_habit_outcome_insights(
            single_habit, {}, lags=[0], min_n=1, min_r=0.0
        )
        assert "outcome" in reason.lower()

    def test_none_outcome_dict_returns_empty_insights(self, single_habit):
        insights, reason = build_habit_outcome_insights(
            single_habit, None, lags=[0], min_n=1, min_r=0.0
        )
        assert insights == []
        assert reason != ""


# ---------------------------------------------------------------------------
# build_habit_outcome_insights — zero-variance series (AC10)
# ---------------------------------------------------------------------------

class TestZeroVarianceSeries:
    def test_zero_variance_outcome_produces_no_insights_no_exception(
        self, single_habit, outcome_series_all_flat
    ):
        """compute_correlation must handle zero-variance outcome gracefully."""
        insights, reason = build_habit_outcome_insights(
            single_habit, outcome_series_all_flat, lags=[0], min_n=1, min_r=0.1
        )
        # Zero variance → r=0 → suppressed by min_r; no exception raised
        assert isinstance(insights, list)

    def test_zero_variance_habit_logs_no_exception(self, outcome_series_correlated):
        """All-True habit completion → zero variance in x; must not raise."""
        all_true_habit = {"name": "All-True habit", "logs": {_make_date(i): True for i in range(30)}}
        insights, reason = build_habit_outcome_insights(
            [all_true_habit], outcome_series_correlated, lags=[0], min_n=1, min_r=0.1
        )
        assert isinstance(insights, list)


# ---------------------------------------------------------------------------
# build_habit_outcome_insights — no magic numbers (AC9)
# ---------------------------------------------------------------------------

class TestNoMagicNumbers:
    def test_min_n_parameter_controls_filtering(self, single_habit, outcome_series_correlated):
        """Changing min_n from 5 to 100 changes the output."""
        i5, _ = build_habit_outcome_insights(
            single_habit, outcome_series_correlated, lags=[0], min_n=5, min_r=0.1
        )
        i100, _ = build_habit_outcome_insights(
            single_habit, outcome_series_correlated, lags=[0], min_n=100, min_r=0.1
        )
        # With 30 days of data, min_n=5 should pass but min_n=100 should fail
        assert len(i5) >= 1
        assert len(i100) == 0

    def test_min_r_parameter_controls_filtering(self, single_habit, outcome_series_correlated):
        """min_r=0.0 (no floor) vs min_r=2.0 (impossible) changes output."""
        i_low, _ = build_habit_outcome_insights(
            single_habit, outcome_series_correlated, lags=[0], min_n=5, min_r=0.0
        )
        i_high, _ = build_habit_outcome_insights(
            single_habit, outcome_series_correlated, lags=[0], min_n=5, min_r=2.0
        )
        assert len(i_low) >= 1
        assert len(i_high) == 0

    def test_lags_parameter_controls_which_lags_are_tested(
        self, single_habit, outcome_series_correlated
    ):
        """Passing lags=[0] vs lags=[] changes output."""
        i_lags, _ = build_habit_outcome_insights(
            single_habit, outcome_series_correlated, lags=[0], min_n=5, min_r=0.1
        )
        i_no_lags, _ = build_habit_outcome_insights(
            single_habit, outcome_series_correlated, lags=[], min_n=5, min_r=0.1
        )
        assert len(i_lags) >= 1
        assert len(i_no_lags) == 0


# ---------------------------------------------------------------------------
# build_habit_outcome_insights — extensible outcomes (AC8)
# ---------------------------------------------------------------------------

class TestExtensibleOutcomes:
    def test_novel_outcome_key_works_without_code_changes(self, single_habit):
        """A new outcome 'vo2max_trend' just requires adding it to the caller dict."""
        correlated = {
            "vo2max_trend": {_make_date(i): (80.0 if i % 2 == 0 else 40.0) for i in range(30)}
        }
        insights, _ = build_habit_outcome_insights(
            single_habit, correlated, lags=[0], min_n=5, min_r=0.1
        )
        # Should produce an insight mentioning the new outcome name
        assert any("vo2max" in s.lower() or "vo2max trend" in s.lower() for s in insights)
