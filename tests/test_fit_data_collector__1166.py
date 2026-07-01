"""Tests for the fit-data collector with minimum-data gate (issue #1166).

AC coverage:
  (a) Normal collection with sufficient data — gate passes, paired tuples returned.
  (b) Gate block with insufficient data — InsufficientDataError raised.
  (c) Exact threshold boundary (n = MIN_FIT_POINTS) — gate passes.
"""

import pytest

from backend.services.fit_data_collector import (
    MIN_FIT_POINTS,
    InsufficientDataError,
    collect_fit_data,
)


def _make_history(n: int) -> list:
    """Build n synthetic history records with distinct load/performance values."""
    return [{"load": float(i + 1) * 10, "performance": float(i + 1) * 5} for i in range(n)]


# ── AC: MIN_FIT_POINTS is a positive integer ──────────────────────────────────

def test_min_fit_points_is_positive_int():
    assert isinstance(MIN_FIT_POINTS, int)
    assert MIN_FIT_POINTS > 0


# ── AC (b): gate blocks when data is below threshold ─────────────────────────

def test_insufficient_data_raises_when_empty():
    with pytest.raises(InsufficientDataError):
        collect_fit_data([])


def test_insufficient_data_raises_when_below_threshold():
    history = _make_history(MIN_FIT_POINTS - 1)
    with pytest.raises(InsufficientDataError):
        collect_fit_data(history)


def test_insufficient_data_error_is_named_exception():
    """InsufficientDataError must be a distinct, named exception class."""
    with pytest.raises(InsufficientDataError) as exc_info:
        collect_fit_data(_make_history(MIN_FIT_POINTS - 1))
    assert exc_info.type is InsufficientDataError


# ── AC (c): exact threshold boundary passes ───────────────────────────────────

def test_exact_threshold_passes():
    history = _make_history(MIN_FIT_POINTS)
    result = collect_fit_data(history)
    assert len(result) == MIN_FIT_POINTS


def test_exact_threshold_returns_correct_pairs():
    history = _make_history(MIN_FIT_POINTS)
    result = collect_fit_data(history)
    for i, pair in enumerate(result):
        load, perf = pair
        assert load == pytest.approx(float(i + 1) * 10)
        assert perf == pytest.approx(float(i + 1) * 5)


# ── AC (a): normal collection with sufficient data ────────────────────────────

def test_sufficient_data_returns_all_pairs():
    n = MIN_FIT_POINTS + 5
    history = _make_history(n)
    result = collect_fit_data(history)
    assert len(result) == n


def test_result_is_list_of_tuples():
    history = _make_history(MIN_FIT_POINTS)
    result = collect_fit_data(history)
    assert isinstance(result, list)
    for pair in result:
        assert isinstance(pair, tuple)
        assert len(pair) == 2


def test_tuple_values_are_numeric():
    history = _make_history(MIN_FIT_POINTS)
    result = collect_fit_data(history)
    for load, perf in result:
        assert isinstance(load, (int, float))
        assert isinstance(perf, (int, float))


def test_pairs_preserve_load_performance_mapping():
    history = [
        {"load": 100.0, "performance": 55.0},
        {"load": 200.0, "performance": 60.0},
        {"load": 300.0, "performance": 65.0},
        {"load": 400.0, "performance": 70.0},
        {"load": 500.0, "performance": 75.0},
    ]
    # Ensure we have at least MIN_FIT_POINTS entries by padding if needed
    while len(history) < MIN_FIT_POINTS:
        history.append({"load": float(len(history) + 1) * 10, "performance": 50.0})

    result = collect_fit_data(history[:MIN_FIT_POINTS])
    # First record must map correctly
    assert result[0][0] == pytest.approx(history[0]["load"])
    assert result[0][1] == pytest.approx(history[0]["performance"])


def test_result_is_iterable():
    history = _make_history(MIN_FIT_POINTS)
    result = collect_fit_data(history)
    pairs = list(result)
    assert len(pairs) == MIN_FIT_POINTS


def test_one_below_threshold_still_raises():
    """Boundary: MIN_FIT_POINTS - 1 must always raise, regardless of values."""
    history = _make_history(max(1, MIN_FIT_POINTS - 1))
    with pytest.raises(InsufficientDataError):
        collect_fit_data(history)
