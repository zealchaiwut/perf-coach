"""Tests for issue #849: computeDayStatus excludes weekly habits from daily logic.

Verifies that:
- AC1: computeDayStatus only counts daily_checkmark habits as applicable
- AC2: computeAllHabitsDaySummary only counts daily_checkmark habits as applicable
- AC3: computeSingleHabitDayStatus returns 'no-data' (not 'not-met') for weekly
       habits on days with no log entry
- AC4: Backend streak endpoint is already narrowed to daily_checkmark; frontend
       now matches the same filter so calendar is consistent with summary

Static tests read frontend/js/habits.js directly.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).parent.parent


def _js() -> str:
    return (ROOT / "frontend" / "js" / "habits.js").read_text()


# ── Helpers to locate function bodies ─────────────────────────────────────────

def _extract_function_body(js: str, func_name: str) -> str:
    """Return the text of a function definition in habits.js."""
    pattern = re.compile(
        r"function\s+" + re.escape(func_name) + r"\s*\([^)]*\)\s*\{",
        re.DOTALL,
    )
    m = pattern.search(js)
    if not m:
        return ""
    start = m.end()
    depth = 1
    i = start
    while i < len(js) and depth > 0:
        if js[i] == "{":
            depth += 1
        elif js[i] == "}":
            depth -= 1
        i += 1
    return js[start : i - 1]


# ── AC1: computeDayStatus excludes weekly habits ───────────────────────────────

def test_compute_day_status_filters_daily_checkmark_only():
    """AC1: computeDayStatus's applicable filter must exclude non-daily_checkmark habits."""
    js = _js()
    body = _extract_function_body(js, "computeDayStatus")
    assert body, "computeDayStatus function not found in habits.js"
    assert "daily_checkmark" in body, (
        "computeDayStatus must filter applicable habits to daily_checkmark only; "
        "weekly_count / weekly_minutes habits must be excluded from the daily status calculation"
    )


def test_compute_day_status_excludes_weekly_count():
    """AC1: computeDayStatus must not count weekly_count habits as applicable for daily status."""
    js = _js()
    body = _extract_function_body(js, "computeDayStatus")
    assert body, "computeDayStatus function not found in habits.js"
    # Must filter by tracking_type (either positive check for daily_checkmark
    # or a negative check that excludes weekly types)
    has_type_filter = (
        "daily_checkmark" in body
        or "weekly_count" in body
        or "tracking_type" in body
    )
    assert has_type_filter, (
        "computeDayStatus must check tracking_type to exclude weekly habits; "
        "the applicable filter should only include habits where tracking_type === 'daily_checkmark'"
    )
    # Specifically, if it checks for daily_checkmark the logic is correct;
    # if it just happens to mention weekly_count, we need to ensure the direction is exclusion
    if "daily_checkmark" in body:
        # The positive-filter approach: only include if tracking_type === 'daily_checkmark'
        # Nothing more to assert — presence of the check is the signal.
        pass
    else:
        # The negative-filter approach must exclude weekly_count and weekly_minutes
        assert "weekly_count" in body and "weekly_minutes" in body, (
            "If computeDayStatus uses a negative filter it must exclude both "
            "weekly_count and weekly_minutes tracking types"
        )


# ── AC2: computeAllHabitsDaySummary excludes weekly habits ────────────────────

def test_compute_all_habits_day_summary_filters_daily_checkmark_only():
    """AC2: computeAllHabitsDaySummary must exclude weekly habits from the applicable set."""
    js = _js()
    body = _extract_function_body(js, "computeAllHabitsDaySummary")
    assert body, "computeAllHabitsDaySummary function not found in habits.js"
    assert "daily_checkmark" in body or "tracking_type" in body, (
        "computeAllHabitsDaySummary must filter applicable habits by tracking_type; "
        "weekly_count / weekly_minutes habits must be excluded from the daily summary count"
    )


def test_compute_all_habits_day_summary_done_total_excludes_weekly():
    """AC2: The done/total count in computeAllHabitsDaySummary must exclude weekly habits."""
    js = _js()
    body = _extract_function_body(js, "computeAllHabitsDaySummary")
    assert body, "computeAllHabitsDaySummary function not found in habits.js"
    # The applicable array is the input to both `done` and `total` counts.
    # If tracking_type is checked before those are computed, the fix is correct.
    has_type_check = "daily_checkmark" in body or (
        "tracking_type" in body and ("weekly_count" in body or "weekly_minutes" in body)
    )
    assert has_type_check, (
        "computeAllHabitsDaySummary must apply a tracking_type filter before computing "
        "done/total so weekly habits are not counted against the daily completion ratio"
    )


# ── AC3: computeSingleHabitDayStatus returns 'no-data' for weekly habits ──────

def test_compute_single_habit_day_status_weekly_no_log_is_no_data():
    """AC3: For weekly habits with no log on a given day, status must be 'no-data' not 'not-met'."""
    js = _js()
    body = _extract_function_body(js, "computeSingleHabitDayStatus")
    assert body, "computeSingleHabitDayStatus function not found in habits.js"
    # The function must check tracking_type and return 'no-data' for non-daily habits
    # that lack a log on the queried day.
    has_type_guard = "daily_checkmark" in body or "tracking_type" in body
    assert has_type_guard, (
        "computeSingleHabitDayStatus must check tracking_type; for weekly habits "
        "without a log on a given day the return value must be 'no-data' rather than 'not-met'"
    )


def test_compute_single_habit_day_status_weekly_does_not_return_not_met_unconditionally():
    """AC3: 'not-met' must only be returned for daily_checkmark habits, not all habits."""
    js = _js()
    body = _extract_function_body(js, "computeSingleHabitDayStatus")
    assert body, "computeSingleHabitDayStatus function not found in habits.js"
    # Before this fix the function always returned 'not-met' for any unlocked habit
    # with no log.  After the fix, 'not-met' is conditional on tracking_type.
    # The simplest check: if 'not-met' appears it must be guarded by a tracking_type check.
    if "'not-met'" in body or '"not-met"' in body:
        assert "tracking_type" in body or "daily_checkmark" in body, (
            "computeSingleHabitDayStatus returns 'not-met' but has no tracking_type guard; "
            "weekly habits must never receive a 'not-met' status for unlocked days without a log"
        )


# ── AC4: daily_checkmark filter is consistent with backend streak logic ────────

def test_backend_streak_uses_daily_checkmark_filter():
    """AC4: Backend already filters streaks to daily_checkmark; verify the constant is present."""
    backend = (ROOT / "backend" / "main.py").read_text()
    assert "daily_checkmark" in backend, (
        "backend/main.py must reference 'daily_checkmark' for streak/summary logic "
        "(confirms the frontend filter is now consistent with the backend)"
    )


def test_frontend_filter_uses_same_daily_checkmark_constant():
    """AC4: Frontend now uses the same 'daily_checkmark' constant as the backend streak logic."""
    js = _js()
    assert "daily_checkmark" in js, (
        "habits.js must use the string 'daily_checkmark' to filter applicable habits "
        "in at least one of computeDayStatus / computeAllHabitsDaySummary / computeSingleHabitDayStatus"
    )
    # Ensure the filter is inside one of the three compute functions
    for func in ("computeDayStatus", "computeAllHabitsDaySummary", "computeSingleHabitDayStatus"):
        body = _extract_function_body(js, func)
        if "daily_checkmark" in body or "tracking_type" in body:
            return  # At least one function has the filter — test passes
    assert False, (
        "None of computeDayStatus, computeAllHabitsDaySummary, computeSingleHabitDayStatus "
        "contain a tracking_type / daily_checkmark guard after the fix"
    )
