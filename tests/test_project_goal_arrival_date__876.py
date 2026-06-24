"""
Tests for issue #876: Add pure function to project goal arrival date.

Acceptance criteria verified:
- AC1: project_arrival is a pure function with no side effects/DB calls
- AC2: Returns {arrival_date, weekly_rate_kg, debug} on success
- AC3: Window derived from module-level constant ARRIVAL_WINDOW_DAYS (14-28 days)
- AC4: arrival_date = today + int((remaining_kg / abs(weekly_rate_kg)) * 7) days
- AC5: remaining_kg = most_recent_weight - goal_weight_kg
- AC6: None/missing inputs return {arrival_date: None, weekly_rate_kg: None, debug: {}, reason: "..."}
- AC7: Zero or diverging rate returns {arrival_date: None, weekly_rate_kg: <rate>, debug: {}, reason: "not trending toward goal"}
- AC8: Already at/past goal → {arrival_date: None, ..., reason: "already at or past goal"}
- AC9: Docstring has worked example in plain prose mentioning 13 kg, 0.4 kg/week, 32 weeks
- AC10: No carets, arrows, or pipe-union type notation in docstring
- AC11: A thin caller function (separate from project_arrival) exists for DB access
- AC12: Unit tests cover standard trend, flat, diverging, missing inputs, already-at-goal
"""
import datetime
import inspect

import pytest

from backend.services.goal_arrival import (
    ARRIVAL_WINDOW_DAYS,
    project_arrival,
)

TODAY = datetime.date(2026, 6, 21)


# ── helpers ───────────────────────────────────────────────────────────────────

def _trend(n_days, start_weight, weekly_change_kg):
    """Build a trend list with linear weight change, oldest entry first."""
    entries = []
    for i in range(n_days):
        d = TODAY - datetime.timedelta(days=n_days - 1 - i)
        w = start_weight + (weekly_change_kg / 7.0) * i
        entries.append({"date": d, "weight_kg": w})
    return entries


def _flat_trend(n_days=21, weight=80.0):
    return [
        {"date": TODAY - datetime.timedelta(days=n_days - 1 - i), "weight_kg": weight}
        for i in range(n_days)
    ]


# ── AC3: Module-level window constant ─────────────────────────────────────────

def test_ac3_window_constant_in_range():
    """ARRIVAL_WINDOW_DAYS must exist and be between 14 and 28 inclusive."""
    assert isinstance(ARRIVAL_WINDOW_DAYS, int), "ARRIVAL_WINDOW_DAYS must be an int"
    assert 14 <= ARRIVAL_WINDOW_DAYS <= 28, (
        f"ARRIVAL_WINDOW_DAYS={ARRIVAL_WINDOW_DAYS} must be between 14 and 28"
    )


def test_ac3_constant_not_hardcoded_inline():
    """ARRIVAL_WINDOW_DAYS must be a named constant at module level, not a literal inline."""
    src = inspect.getsource(project_arrival)
    # The module-level name must appear in the function body; the raw integer should not
    assert "ARRIVAL_WINDOW_DAYS" in src, (
        "project_arrival must reference ARRIVAL_WINDOW_DAYS, not a hardcoded integer"
    )


# ── AC1/AC2: Standard converging trend ───────────────────────────────────────

def test_ac2_returns_required_fields_on_success():
    """Success result must contain arrival_date, weekly_rate_kg, and debug."""
    trend = _trend(ARRIVAL_WINDOW_DAYS, start_weight=93.0, weekly_change_kg=-0.4)
    result = project_arrival(trend, goal_weight_kg=80.0, today=TODAY)
    assert "arrival_date" in result
    assert "weekly_rate_kg" in result
    assert "debug" in result


def test_ac2_arrival_date_is_future_date():
    """Standard converging trend produces a future arrival_date."""
    trend = _trend(ARRIVAL_WINDOW_DAYS, start_weight=93.0, weekly_change_kg=-0.4)
    result = project_arrival(trend, goal_weight_kg=80.0, today=TODAY)
    assert result["arrival_date"] is not None
    assert isinstance(result["arrival_date"], datetime.date)
    assert result["arrival_date"] > TODAY


def test_ac2_weekly_rate_is_negative_for_loss():
    """weekly_rate_kg is negative when losing weight toward a lower goal."""
    trend = _trend(ARRIVAL_WINDOW_DAYS, start_weight=93.0, weekly_change_kg=-0.4)
    result = project_arrival(trend, goal_weight_kg=80.0, today=TODAY)
    assert result["weekly_rate_kg"] < 0


def test_ac2_debug_is_nonempty_dict():
    """debug is a non-empty dict on success."""
    trend = _trend(ARRIVAL_WINDOW_DAYS, start_weight=93.0, weekly_change_kg=-0.4)
    result = project_arrival(trend, goal_weight_kg=80.0, today=TODAY)
    assert isinstance(result["debug"], dict)
    assert len(result["debug"]) > 0


def test_ac2_no_reason_on_success():
    """Successful result does not contain a non-empty reason field."""
    trend = _trend(ARRIVAL_WINDOW_DAYS, start_weight=93.0, weekly_change_kg=-0.4)
    result = project_arrival(trend, goal_weight_kg=80.0, today=TODAY)
    reason = result.get("reason")
    assert not reason, f"Successful result must not have a reason, got: {reason!r}"


# ── AC4: arrival_date formula ─────────────────────────────────────────────────

def test_ac4_arrival_date_formula():
    """arrival_date equals today plus int((remaining_kg / abs(weekly_rate_kg)) * 7) days."""
    trend = _trend(ARRIVAL_WINDOW_DAYS, start_weight=93.0, weekly_change_kg=-0.4)
    result = project_arrival(trend, goal_weight_kg=80.0, today=TODAY)
    most_recent_w = trend[-1]["weight_kg"]
    remaining = most_recent_w - 80.0
    rate = result["weekly_rate_kg"]
    expected_days = int((remaining / abs(rate)) * 7)
    expected_date = TODAY + datetime.timedelta(days=expected_days)
    assert result["arrival_date"] == expected_date, (
        f"Expected arrival_date={expected_date} from formula, got {result['arrival_date']}"
    )


# ── AC5: remaining_kg uses most recent entry ──────────────────────────────────

def test_ac5_debug_contains_remaining_kg():
    """debug must include remaining_kg = most_recent_weight - goal_weight_kg."""
    trend = _trend(ARRIVAL_WINDOW_DAYS, start_weight=93.0, weekly_change_kg=-0.4)
    result = project_arrival(trend, goal_weight_kg=80.0, today=TODAY)
    most_recent = trend[-1]["weight_kg"]
    expected_remaining = most_recent - 80.0
    assert "remaining_kg" in result["debug"], "debug must contain remaining_kg"
    assert abs(result["debug"]["remaining_kg"] - expected_remaining) < 0.001, (
        f"remaining_kg={result['debug']['remaining_kg']} != expected {expected_remaining}"
    )


# ── AC7: flat trend ───────────────────────────────────────────────────────────

def test_ac7_flat_trend_returns_null_arrival():
    """Completely flat trend returns arrival_date=None."""
    trend = _flat_trend(n_days=ARRIVAL_WINDOW_DAYS, weight=80.0)
    result = project_arrival(trend, goal_weight_kg=75.0, today=TODAY)
    assert result["arrival_date"] is None


def test_ac7_flat_trend_reason():
    """Flat trend reason must be 'not trending toward goal'."""
    trend = _flat_trend(n_days=ARRIVAL_WINDOW_DAYS, weight=80.0)
    result = project_arrival(trend, goal_weight_kg=75.0, today=TODAY)
    assert result["reason"] == "not trending toward goal"


def test_ac7_flat_trend_includes_computed_rate():
    """Flat trend result must include the computed weekly_rate_kg (zero)."""
    trend = _flat_trend(n_days=ARRIVAL_WINDOW_DAYS, weight=80.0)
    result = project_arrival(trend, goal_weight_kg=75.0, today=TODAY)
    assert result["weekly_rate_kg"] is not None
    assert abs(result["weekly_rate_kg"]) < 0.001


# ── AC7: diverging trend ──────────────────────────────────────────────────────

def test_ac7_diverging_trend_returns_null_arrival():
    """Trend rising when goal requires decrease returns arrival_date=None."""
    trend = _trend(ARRIVAL_WINDOW_DAYS, start_weight=80.0, weekly_change_kg=+0.3)
    result = project_arrival(trend, goal_weight_kg=75.0, today=TODAY)
    assert result["arrival_date"] is None


def test_ac7_diverging_trend_reason():
    """Diverging trend reason must be 'not trending toward goal'."""
    trend = _trend(ARRIVAL_WINDOW_DAYS, start_weight=80.0, weekly_change_kg=+0.3)
    result = project_arrival(trend, goal_weight_kg=75.0, today=TODAY)
    assert result["reason"] == "not trending toward goal"


def test_ac7_diverging_trend_includes_positive_rate():
    """Diverging trend result must include the computed weekly_rate_kg (positive for gain)."""
    trend = _trend(ARRIVAL_WINDOW_DAYS, start_weight=80.0, weekly_change_kg=+0.3)
    result = project_arrival(trend, goal_weight_kg=75.0, today=TODAY)
    assert result["weekly_rate_kg"] is not None
    assert result["weekly_rate_kg"] > 0


def test_ac7_diverging_includes_debug_dict():
    """Diverging trend result debug must be a dict (may be empty per AC)."""
    trend = _trend(ARRIVAL_WINDOW_DAYS, start_weight=80.0, weekly_change_kg=+0.3)
    result = project_arrival(trend, goal_weight_kg=75.0, today=TODAY)
    assert isinstance(result["debug"], dict)


# ── AC8: already at or past goal ─────────────────────────────────────────────

def test_ac8_already_at_goal_exact():
    """Most recent weight equal to goal returns arrival_date=None, reason='already at or past goal'."""
    trend = _trend(ARRIVAL_WINDOW_DAYS, start_weight=75.0 + 0.3 * (ARRIVAL_WINDOW_DAYS - 1) / 7.0, weekly_change_kg=-0.3)
    trend[-1]["weight_kg"] = 75.0  # force exact equality
    result = project_arrival(trend, goal_weight_kg=75.0, today=TODAY)
    assert result["arrival_date"] is None
    assert result["reason"] == "already at or past goal"


def test_ac8_past_goal_weight():
    """Most recent weight below goal (overshot loss target) returns 'already at or past goal'."""
    # Current weight 73, goal 75 — user is already below the loss target
    trend = _trend(ARRIVAL_WINDOW_DAYS, start_weight=73.5, weekly_change_kg=-0.1)
    result = project_arrival(trend, goal_weight_kg=75.0, today=TODAY)
    assert result["arrival_date"] is None
    assert result["reason"] == "already at or past goal"


# ── AC6: missing inputs ───────────────────────────────────────────────────────

def test_ac6_null_actual_trend():
    """None actual_trend returns arrival_date=None with a reason string, no exception."""
    result = project_arrival(None, goal_weight_kg=75.0, today=TODAY)
    assert result["arrival_date"] is None
    assert result["weekly_rate_kg"] is None
    assert isinstance(result["debug"], dict)
    assert result.get("reason") and len(result["reason"]) > 0


def test_ac6_empty_actual_trend():
    """Empty actual_trend returns arrival_date=None with a reason string, no exception."""
    result = project_arrival([], goal_weight_kg=75.0, today=TODAY)
    assert result["arrival_date"] is None
    assert result.get("reason") and len(result["reason"]) > 0


def test_ac6_null_goal_weight():
    """None goal_weight_kg returns arrival_date=None with a reason string, no exception."""
    trend = _trend(ARRIVAL_WINDOW_DAYS, start_weight=80.0, weekly_change_kg=-0.4)
    result = project_arrival(trend, goal_weight_kg=None, today=TODAY)
    assert result["arrival_date"] is None
    assert result["weekly_rate_kg"] is None
    assert result.get("reason") and len(result["reason"]) > 0


def test_ac6_null_today():
    """None today returns arrival_date=None with a reason string, no exception."""
    trend = _trend(ARRIVAL_WINDOW_DAYS, start_weight=80.0, weekly_change_kg=-0.4)
    result = project_arrival(trend, goal_weight_kg=75.0, today=None)
    assert result["arrival_date"] is None
    assert result["weekly_rate_kg"] is None
    assert result.get("reason") and len(result["reason"]) > 0


def test_ac6_all_null():
    """All-null inputs return arrival_date=None with reason, no exception."""
    result = project_arrival(None, goal_weight_kg=None, today=None)
    assert result["arrival_date"] is None
    assert result.get("reason") and len(result["reason"]) > 0


def test_ac6_no_exception_for_bad_inputs():
    """project_arrival must not raise for any null or empty input combination."""
    cases = [
        (None, 75.0, TODAY),
        ([], 75.0, TODAY),
        (_trend(ARRIVAL_WINDOW_DAYS, 80.0, -0.4), None, TODAY),
        (_trend(ARRIVAL_WINDOW_DAYS, 80.0, -0.4), 75.0, None),
        (None, None, None),
    ]
    for trend, goal, today in cases:
        try:
            project_arrival(trend, goal, today)
        except Exception as exc:
            pytest.fail(
                f"project_arrival raised {type(exc).__name__} for "
                f"inputs ({type(trend).__name__}, {goal!r}, {today!r}): {exc}"
            )


# ── AC12: fewer entries than window ──────────────────────────────────────────

def test_ac12_fewer_entries_no_exception():
    """Fewer entries than window constant must not raise."""
    short_trend = _trend(5, start_weight=80.0, weekly_change_kg=-0.4)
    try:
        project_arrival(short_trend, goal_weight_kg=75.0, today=TODAY)
    except Exception as exc:
        pytest.fail(f"project_arrival raised {type(exc).__name__} for short trend: {exc}")


def test_ac12_fewer_entries_documents_in_debug_or_returns_reason():
    """Fewer entries than window: uses available data and notes in debug, or returns a reason."""
    short_trend = _trend(5, start_weight=80.0, weekly_change_kg=-0.4)
    result = project_arrival(short_trend, goal_weight_kg=75.0, today=TODAY)
    assert "arrival_date" in result
    assert "debug" in result
    if result["arrival_date"] is None:
        assert result.get("reason") and len(result["reason"]) > 0
    else:
        # Must document that fewer days were used
        assert "window_days_used" in result["debug"], (
            "debug must document how many days were actually used in the window"
        )


# ── AC9/AC10: docstring requirements ──────────────────────────────────────────

def test_ac9_docstring_has_worked_example():
    """Docstring must contain a worked example with 13 kg, 0.4 kg/week, and ~32 weeks."""
    doc = project_arrival.__doc__ or ""
    assert "13" in doc, "docstring worked example must mention 13 kg remaining"
    assert "0.4" in doc, "docstring worked example must mention 0.4 kg per week"
    assert "32" in doc, "docstring worked example must mention approximately 32 weeks"


def test_ac10_no_carets_in_docstring():
    """Docstring must not contain carets (^)."""
    doc = project_arrival.__doc__ or ""
    assert "^" not in doc, "docstring must not use caret (^) for exponentiation or comparison"


def test_ac10_no_arrows_in_docstring():
    """Docstring must not contain arrow notation (-> or =>)."""
    doc = project_arrival.__doc__ or ""
    assert "->" not in doc, "docstring must not use '->' notation"
    assert "=>" not in doc, "docstring must not use '=>' notation"


def test_ac10_no_pipe_union_in_docstring():
    """Docstring must not contain pipe-union type notation (|)."""
    doc = project_arrival.__doc__ or ""
    assert "|" not in doc, "docstring must not use '|' for type unions"


# ── AC1: purity — no DB/session calls in function body ───────────────────────

def test_ac1_no_db_calls_in_function_body():
    """project_arrival body must not reference ORM session, query, or DB models."""
    src = inspect.getsource(project_arrival)
    forbidden = ["session", "query(", "Session(", "get_db", "WeightEntry", "WeightTarget"]
    for term in forbidden:
        assert term not in src, (
            f"project_arrival must not reference '{term}' — it must be a pure function"
        )


# ── AC11: thin caller exists ──────────────────────────────────────────────────

def test_ac11_thin_caller_exists_in_module():
    """goal_arrival module must export at least one thin caller besides project_arrival."""
    from backend.services import goal_arrival
    public_fns = [
        name
        for name, obj in inspect.getmembers(goal_arrival, inspect.isfunction)
        if not name.startswith("_") and name != "project_arrival"
    ]
    assert len(public_fns) >= 1, (
        "goal_arrival module must contain at least one thin caller function "
        f"in addition to project_arrival; found only: {public_fns}"
    )
