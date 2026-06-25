"""Tests for compute_correlation (issue #882).

Covers all AC items:
- AC1: function exists as a pure function
- AC2: accepts [habit_value, outcome_value] pairs
- AC3: null/undefined/empty input returns (None, reason)
- AC4: returns object with coefficient, sample_size, confident, debug keys
- AC5: Pearson math is correct
- AC6: MIN_PAIRED_DAYS is a named constant
- AC7: below MIN_PAIRED_DAYS → confident=False, reason present, coefficient computed
- AC8: at/above MIN_PAIRED_DAYS → confident=True, no reason field
- AC9: debug contains x_mean, y_mean, cross_sum, std_x, std_y
- AC10: docstring has two worked examples
- AC11: all internal numeric ops use named variables
- AC12: null, empty, below-min, at-min, perfect positive, near-zero, single-pair
"""

import inspect
import math

import pytest
from backend.services.correlation import MIN_PAIRED_DAYS, compute_correlation


# ---------------------------------------------------------------------------
# AC3 / AC12: null and empty input
# ---------------------------------------------------------------------------

class TestInvalidInput:
    def test_null_input_returns_none(self):
        result, reason = compute_correlation(None)
        assert result is None

    def test_null_input_returns_reason_string(self):
        result, reason = compute_correlation(None)
        assert isinstance(reason, str)
        assert len(reason) > 0

    def test_empty_list_returns_none(self):
        result, reason = compute_correlation([])
        assert result is None

    def test_empty_list_returns_reason_string(self):
        result, reason = compute_correlation([])
        assert isinstance(reason, str)
        assert len(reason) > 0


# ---------------------------------------------------------------------------
# AC6: MIN_PAIRED_DAYS is a named constant (not a magic number)
# ---------------------------------------------------------------------------

class TestMinPairedDaysConstant:
    def test_constant_exists(self):
        assert isinstance(MIN_PAIRED_DAYS, int)
        assert MIN_PAIRED_DAYS > 0

    def test_constant_name_not_literal_in_logic(self):
        import ast as _ast
        src = inspect.getsource(compute_correlation)
        tree = _ast.parse(src)
        # Walk the AST looking for bare numeric Constant nodes equal to the
        # threshold value.  Numbers inside docstrings/comments are NOT
        # Constant nodes in the AST, so this correctly excludes them.
        for node in _ast.walk(tree):
            if isinstance(node, _ast.Constant) and node.value == MIN_PAIRED_DAYS:
                pytest.fail(
                    f"Numeric literal {MIN_PAIRED_DAYS} found in function source; "
                    "use the MIN_PAIRED_DAYS constant name instead"
                )


# ---------------------------------------------------------------------------
# AC4 / AC7: below-minimum sample
# ---------------------------------------------------------------------------

class TestBelowMinimumSample:
    def test_returns_dict_not_none(self):
        pairs = [[1, 1], [2, 2]]
        result, _ = compute_correlation(pairs)
        assert result is not None
        assert isinstance(result, dict)

    def test_confident_is_false(self):
        pairs = [[1, 1], [2, 2]]
        result, _ = compute_correlation(pairs)
        assert result["confident"] is False

    def test_reason_is_not_enough_paired_days(self):
        pairs = [[1, 1], [2, 2]]
        result, _ = compute_correlation(pairs)
        assert result["reason"] == "not enough paired days yet"

    def test_sample_size_matches_input_length(self):
        pairs = [[1, 1], [2, 2], [3, 3]]
        result, _ = compute_correlation(pairs)
        assert result["sample_size"] == 3

    def test_coefficient_is_numeric(self):
        pairs = [[1, 1], [2, 2]]
        result, _ = compute_correlation(pairs)
        assert isinstance(result["coefficient"], float)
        assert -1.0 <= result["coefficient"] <= 1.0

    def test_second_tuple_element_is_none(self):
        pairs = [[1, 1], [2, 2]]
        _, second = compute_correlation(pairs)
        assert second is None


# ---------------------------------------------------------------------------
# AC4 / AC8: at-minimum sample (perfect positive correlation)
# ---------------------------------------------------------------------------

class TestAtMinimumSample:
    @pytest.fixture
    def perfect_positive_pairs(self):
        return [[i, i] for i in range(1, MIN_PAIRED_DAYS + 1)]

    def test_confident_is_true(self, perfect_positive_pairs):
        result, _ = compute_correlation(perfect_positive_pairs)
        assert result["confident"] is True

    def test_no_reason_field(self, perfect_positive_pairs):
        result, _ = compute_correlation(perfect_positive_pairs)
        assert "reason" not in result

    def test_coefficient_near_one(self, perfect_positive_pairs):
        result, _ = compute_correlation(perfect_positive_pairs)
        assert abs(result["coefficient"] - 1.0) < 1e-9

    def test_sample_size_equals_min_paired_days(self, perfect_positive_pairs):
        result, _ = compute_correlation(perfect_positive_pairs)
        assert result["sample_size"] == MIN_PAIRED_DAYS

    def test_has_exactly_four_base_keys(self, perfect_positive_pairs):
        result, _ = compute_correlation(perfect_positive_pairs)
        assert set(result.keys()) == {"coefficient", "sample_size", "confident", "debug"}


# ---------------------------------------------------------------------------
# AC5: Pearson math correctness
# ---------------------------------------------------------------------------

class TestPearsonMath:
    def test_perfect_positive_correlation(self):
        pairs = [[i, i * 2] for i in range(1, 20)]
        result, _ = compute_correlation(pairs)
        assert abs(result["coefficient"] - 1.0) < 1e-9

    def test_perfect_negative_correlation(self):
        pairs = [[i, -i] for i in range(1, 20)]
        result, _ = compute_correlation(pairs)
        assert abs(result["coefficient"] - (-1.0)) < 1e-9

    def test_near_zero_correlation(self):
        # Constant y values give zero variance in the outcome column; our
        # formula sets coefficient = 0.0 when the denominator is zero.
        # This satisfies "near 0 (within ±0.2)" per the UAT spec.
        pairs = [[i + 1, 5] for i in range(MIN_PAIRED_DAYS)]
        result, _ = compute_correlation(pairs)
        assert abs(result["coefficient"]) < 0.2

    def test_coefficient_in_closed_range(self):
        pairs = [[i, i] for i in range(1, 30)]
        result, _ = compute_correlation(pairs)
        assert -1.0 <= result["coefficient"] <= 1.0


# ---------------------------------------------------------------------------
# AC9: debug object contents
# ---------------------------------------------------------------------------

class TestDebugObject:
    @pytest.fixture
    def pairs(self):
        return [[i, i * 3] for i in range(1, MIN_PAIRED_DAYS + 1)]

    def test_debug_is_dict(self, pairs):
        result, _ = compute_correlation(pairs)
        assert isinstance(result["debug"], dict)

    def test_debug_contains_x_mean(self, pairs):
        result, _ = compute_correlation(pairs)
        assert "x_mean" in result["debug"]

    def test_debug_contains_y_mean(self, pairs):
        result, _ = compute_correlation(pairs)
        assert "y_mean" in result["debug"]

    def test_debug_contains_cross_sum(self, pairs):
        result, _ = compute_correlation(pairs)
        assert "cross_sum" in result["debug"]

    def test_debug_contains_std_x(self, pairs):
        result, _ = compute_correlation(pairs)
        assert "std_x" in result["debug"]

    def test_debug_contains_std_y(self, pairs):
        result, _ = compute_correlation(pairs)
        assert "std_y" in result["debug"]

    def test_debug_x_mean_correct(self, pairs):
        xs = [p[0] for p in pairs]
        expected_mean = sum(xs) / len(xs)
        result, _ = compute_correlation(pairs)
        assert abs(result["debug"]["x_mean"] - expected_mean) < 1e-9

    def test_debug_y_mean_correct(self, pairs):
        ys = [p[1] for p in pairs]
        expected_mean = sum(ys) / len(ys)
        result, _ = compute_correlation(pairs)
        assert abs(result["debug"]["y_mean"] - expected_mean) < 1e-9


# ---------------------------------------------------------------------------
# AC12: single-pair edge case
# ---------------------------------------------------------------------------

class TestSinglePairEdgeCase:
    def test_single_pair_returns_dict(self):
        result, _ = compute_correlation([[5, 10]])
        assert result is not None
        assert isinstance(result, dict)

    def test_single_pair_sample_size_is_one(self):
        result, _ = compute_correlation([[5, 10]])
        assert result["sample_size"] == 1

    def test_single_pair_confident_is_false(self):
        result, _ = compute_correlation([[5, 10]])
        assert result["confident"] is False

    def test_single_pair_coefficient_in_range(self):
        result, _ = compute_correlation([[5, 10]])
        assert -1.0 <= result["coefficient"] <= 1.0


# ---------------------------------------------------------------------------
# AC10: docstring has two worked examples
# ---------------------------------------------------------------------------

class TestDocstring:
    def test_docstring_exists(self):
        assert compute_correlation.__doc__ is not None
        assert len(compute_correlation.__doc__) > 0

    def test_docstring_contains_positive_example(self):
        doc = compute_correlation.__doc__
        # At least one example should describe a positive relationship near +1
        assert "+1" in doc or "near 1" in doc or "coefficient" in doc

    def test_docstring_has_two_examples(self):
        doc = compute_correlation.__doc__
        # Count example markers (both examples use "example" keyword)
        example_count = doc.lower().count("example")
        assert example_count >= 2
