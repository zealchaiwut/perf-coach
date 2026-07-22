"""Tests for issue #850: Week strip navigation fetches month range instead of displayed week range.

Verifies that _refreshHabitCal() expands its date range to cover the week strip's
current 7-day window when it extends beyond the month calendar's range.

AC1: When hcalWeekStart falls before the first day of hcalMonth (i.e., navigated back
     to a week partially in the prior month), _refreshHabitCal uses a `from` date that
     covers the week strip's Monday rather than only the month's first day.
AC2: When hcalWeekStart + 6 days extends past the last day of hcalMonth (i.e., the
     week strip crosses into the next month), _refreshHabitCal uses a `to` date that
     covers the week strip's Sunday rather than only the month's last day.
AC3: When the week strip lies entirely within hcalMonth, the fetch range remains the
     full month (no narrowing and no unnecessary extension).
AC4: The range expansion logic is applied inside _refreshHabitCal, NOT in the nav
     button handlers, so it is always enforced regardless of how hcalWeekStart changed.
"""

import pathlib
import re

ROOT = pathlib.Path(__file__).parent.parent


def _js() -> str:
    return (ROOT / "frontend" / "js" / "habits.js").read_text()


def test_refresh_habit_cal_reads_hcal_week_start():
    """AC1/AC2: _refreshHabitCal must reference hcalWeekStart to compute the range."""
    js = _js()
    # Locate _refreshHabitCal function body
    match = re.search(r'async function _refreshHabitCal\(\)\s*\{(.+?)^\}',
                      js, re.DOTALL | re.MULTILINE)
    assert match, "_refreshHabitCal function not found in habits.js"
    body = match.group(1)
    assert 'hcalWeekStart' in body, (
        "_refreshHabitCal must reference hcalWeekStart to compute the fetch range; "
        "currently it only uses hcalMonth which causes week-strip cross-month dates "
        "to render with missing log data (issue #850)"
    )


def test_refresh_habit_cal_expands_from_date():
    """AC1: _refreshHabitCal must widen 'from' to cover week strip start when earlier."""
    js = _js()
    match = re.search(r'async function _refreshHabitCal\(\)\s*\{(.+?)^\}',
                      js, re.DOTALL | re.MULTILINE)
    assert match, "_refreshHabitCal function not found"
    body = match.group(1)
    # Must compare from against weekFrom (or similar) and take the minimum
    has_min_from = (
        re.search(r'weekFrom\s*<\s*from', body) or
        re.search(r'from\s*>\s*weekFrom', body) or
        re.search(r'from\s*=\s*weekFrom', body) or
        re.search(r'_hcalISO\(hcalWeekStart\)', body)
    )
    assert has_min_from, (
        "_refreshHabitCal must widen the 'from' date to include the week strip start "
        "when it precedes the month's first day (AC1 of issue #850)"
    )


def test_refresh_habit_cal_expands_to_date():
    """AC2: _refreshHabitCal must widen 'to' to cover week strip end when later."""
    js = _js()
    match = re.search(r'async function _refreshHabitCal\(\)\s*\{(.+?)^\}',
                      js, re.DOTALL | re.MULTILINE)
    assert match, "_refreshHabitCal function not found"
    body = match.group(1)
    # Must compute week end (weekStart + 6 days) and compare to `to`
    has_week_end = (
        re.search(r'hcalWeekStart\.getDate\(\)\s*\+\s*6', body) or
        re.search(r'getDate\(\)\s*\+\s*6', body) or
        re.search(r'weekEnd', body)
    )
    assert has_week_end, (
        "_refreshHabitCal must compute the week strip end date (weekStart + 6 days) "
        "and extend 'to' when that date falls after the month's last day (AC2 of issue #850)"
    )


def test_range_expansion_inside_refresh_not_only_in_nav_handlers():
    """AC4: Range expansion lives in _refreshHabitCal, not only in nav button handlers."""
    js = _js()
    # Confirm prev/next nav handlers still exist and shift by 7 days
    assert 'getDate() - 7' in js or 'getDate()-7' in js, (
        "Week strip prev handler should shift hcalWeekStart back by 7 days"
    )
    assert 'getDate() + 7' in js or 'getDate()+7' in js, (
        "Week strip next handler should shift hcalWeekStart forward by 7 days"
    )

    # The expansion must be inside _refreshHabitCal, not duplicated only in the handlers
    refresh_match = re.search(r'async function _refreshHabitCal\(\)\s*\{(.+?)^\}',
                               js, re.DOTALL | re.MULTILINE)
    assert refresh_match, "_refreshHabitCal not found"
    refresh_body = refresh_match.group(1)
    assert 'hcalWeekStart' in refresh_body, (
        "Range expansion must live inside _refreshHabitCal so it applies whenever "
        "the function is called, regardless of how hcalWeekStart changed (AC4)"
    )
