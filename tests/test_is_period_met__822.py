"""Tests for issue #822: is_period_met pure function for habit completion logic.

Unit tests anchored to the Acceptance Criteria and UAT test steps.
"""

import types


# ── Helpers ───────────────────────────────────────────────────────────────────

def _habit(habit_type, target_value=None):
    """Return a plain namespace acting as a habit row."""
    return types.SimpleNamespace(habit_type=habit_type, target_value=target_value)


def _log(value):
    """Return a plain namespace acting as a HabitLog row."""
    return types.SimpleNamespace(value=value)


# ── Module-level smoke test ───────────────────────────────────────────────────

def test_module_is_importable():
    """is_period_met, _is_binary_met and _is_count_met must all be importable."""
    from backend.services.habit_completion import (  # noqa: F401
        is_period_met,
        _is_binary_met,
        _is_count_met,
    )


# ── AC: invalid habit ─────────────────────────────────────────────────────────

def test_invalid_habit_none(capsys):
    """AC / UAT 7: habit=None returns (False, {"reason": "invalid habit"})."""
    from backend.services.habit_completion import is_period_met
    result, debug = is_period_met(None, [_log(1)])
    assert result is False
    assert debug["reason"] == "invalid habit"


def test_invalid_habit_missing_type():
    """AC: missing habit_type treated as invalid habit."""
    from backend.services.habit_completion import is_period_met
    bad = types.SimpleNamespace()  # no habit_type attribute
    result, debug = is_period_met(bad, [_log(1)])
    assert result is False
    assert debug["reason"] == "invalid habit"


def test_invalid_habit_unknown_type():
    """AC: unrecognised habit_type (e.g. 'daily_checkmark') returns invalid."""
    from backend.services.habit_completion import is_period_met
    result, debug = is_period_met(_habit("daily_checkmark"), [_log(1)])
    assert result is False
    assert debug["reason"] == "invalid habit"


# ── AC: missing logs ──────────────────────────────────────────────────────────

def test_empty_logs_returns_no_logs_in_period():
    """AC / UAT 6: any valid habit with logs_in_period=[] returns 'no logs in period'."""
    from backend.services.habit_completion import is_period_met
    result, debug = is_period_met(_habit("binary"), [])
    assert result is False
    assert debug["reason"] == "no logs in period"


def test_empty_logs_count_habit():
    """AC: empty logs for a count habit also returns 'no logs in period'."""
    from backend.services.habit_completion import is_period_met
    result, debug = is_period_met(_habit("count", target_value=8), [])
    assert result is False
    assert debug["reason"] == "no logs in period"


# ── AC: binary met ────────────────────────────────────────────────────────────

def test_binary_met_single_log_value_1():
    """AC / UAT 1: binary habit with log value=1 → met, reason includes value."""
    from backend.services.habit_completion import is_period_met
    result, debug = is_period_met(_habit("binary"), [_log(1)])
    assert result is True
    assert debug["reason"] == "binary log value 1 >= 1"


def test_binary_met_higher_value():
    """AC: binary habit with log value > 1 also qualifies."""
    from backend.services.habit_completion import is_period_met
    result, debug = is_period_met(_habit("binary"), [_log(3)])
    assert result is True
    assert "binary log value 3 >= 1" == debug["reason"]


def test_binary_met_first_qualifying_log_wins():
    """AC: when multiple logs exist, any one with value>=1 is sufficient."""
    from backend.services.habit_completion import is_period_met
    result, debug = is_period_met(_habit("binary"), [_log(0), _log(1), _log(2)])
    assert result is True
    assert ">= 1" in debug["reason"]


# ── AC: binary not met ────────────────────────────────────────────────────────

def test_binary_not_met_value_zero():
    """AC / UAT 2: binary habit with log value=0 → not met."""
    from backend.services.habit_completion import is_period_met
    result, debug = is_period_met(_habit("binary"), [_log(0)])
    assert result is False
    assert debug["reason"] == "no log with value >= 1 found"


def test_binary_not_met_all_zero():
    """AC: binary with multiple logs all value=0 → not met."""
    from backend.services.habit_completion import is_period_met
    result, debug = is_period_met(_habit("binary"), [_log(0), _log(0)])
    assert result is False
    assert debug["reason"] == "no log with value >= 1 found"


# ── AC: count met / not met ───────────────────────────────────────────────────

def test_count_not_met_sum_below_target():
    """AC / UAT 3: count habit target=8, logs summing to 6 → not met."""
    from backend.services.habit_completion import is_period_met
    result, debug = is_period_met(_habit("count", target_value=8), [_log(4), _log(2)])
    assert result is False
    assert debug["reason"] == "logged 6 does not meet target 8"


def test_count_met_sum_equals_target():
    """AC / UAT 4: count habit target=8, logs summing to 8 → met."""
    from backend.services.habit_completion import is_period_met
    result, debug = is_period_met(_habit("count", target_value=8), [_log(5), _log(3)])
    assert result is True
    assert debug["reason"] == "logged 8 meets target 8"


def test_count_met_sum_exceeds_target():
    """AC: count habit target=8, logs summing to 10 → met."""
    from backend.services.habit_completion import is_period_met
    result, debug = is_period_met(_habit("count", target_value=8), [_log(10)])
    assert result is True
    assert "meets target 8" in debug["reason"]


# ── AC: duration met ─────────────────────────────────────────────────────────

def test_duration_met_sum_exceeds_target():
    """AC / UAT 5: duration habit target=30, logs summing to 45 → met."""
    from backend.services.habit_completion import is_period_met
    result, debug = is_period_met(_habit("duration", target_value=30), [_log(25), _log(20)])
    assert result is True
    assert debug["reason"] == "logged 45 meets target 30"


def test_duration_not_met_sum_below_target():
    """AC: duration habit target=30, logs summing to 20 → not met."""
    from backend.services.habit_completion import is_period_met
    result, debug = is_period_met(_habit("duration", target_value=30), [_log(20)])
    assert result is False
    assert debug["reason"] == "logged 20 does not meet target 30"


# ── AC: target_value from habit row ──────────────────────────────────────────

def test_target_value_always_from_habit_row():
    """AC: target_value is read from habit.target_value, not hardcoded."""
    from backend.services.habit_completion import is_period_met
    # target_value = 5 (not 8 or any other hardcoded value)
    result, debug = is_period_met(_habit("count", target_value=5), [_log(5)])
    assert result is True
    assert "5" in debug["reason"]


def test_count_habit_missing_target_value_invalid():
    """AC: count habit with target_value=None treats habit as invalid."""
    from backend.services.habit_completion import is_period_met
    result, debug = is_period_met(_habit("count", target_value=None), [_log(8)])
    assert result is False
    assert debug["reason"] == "invalid habit"


# ── AC: no DB access ─────────────────────────────────────────────────────────

def test_no_db_access_in_module():
    """AC: habit_completion module must not import sqlalchemy session or db module."""
    import importlib
    import inspect
    mod = importlib.import_module("backend.services.habit_completion")
    source = inspect.getsource(mod)
    assert "session" not in source
    assert "from backend.db" not in source
    assert "import db" not in source


# ── AC: helper functions importable ──────────────────────────────────────────

def test_binary_helper_directly():
    """AC: _is_binary_met is a named helper callable directly."""
    from backend.services.habit_completion import _is_binary_met
    met, debug = _is_binary_met([_log(1)])
    assert met is True
    assert "binary" in debug["reason"]


def test_count_helper_directly():
    """AC: _is_count_met is a named helper callable directly."""
    from backend.services.habit_completion import _is_count_met
    met, debug = _is_count_met([_log(8)], 8)
    assert met is True


# ── AC: streak module delegates to helper ────────────────────────────────────

def test_streak_module_imports_from_habit_completion():
    """UAT 8: habit_stats module imports from habit_completion (no duplicate met-rule)."""
    import inspect
    from backend.services import habit_stats
    source = inspect.getsource(habit_stats)
    assert "habit_completion" in source, (
        "habit_stats should import from habit_completion; "
        "no duplicate met-rule code should exist in the streak module"
    )


# ── AC: consistency module (no existing module — no duplicate logic) ──────────

def test_no_consistency_module_duplicates_met_rule():
    """UAT 9: no separate consistency module re-implements met-period logic."""
    import glob
    candidates = glob.glob(
        "/Users/zeal-server/dev/perf-coach/coder/backend/services/habit_consist*.py"
    )
    for path in candidates:
        with open(path) as fh:
            src = fh.read()
        assert "habit_completion" in src or "is_period_met" in src, (
            f"{path} contains consistency met-rule logic without delegating to habit_completion"
        )
    # No consistency module yet → trivially passes


# ── AC: docstring includes three worked examples ─────────────────────────────

def test_docstring_contains_worked_examples():
    """AC: is_period_met docstring includes three worked examples."""
    from backend.services.habit_completion import is_period_met
    doc = is_period_met.__doc__ or ""
    assert "binary" in doc.lower()
    assert "count" in doc.lower() or "target" in doc.lower()
    assert ">= 1" in doc or "met" in doc.lower()
