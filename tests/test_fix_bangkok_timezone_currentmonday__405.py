"""Tests for issue #405: Fix Bangkok timezone calculation in home-habits widget.

TDD: each test anchored to one Acceptance Criterion.
The fix rewrites currentMonday() to derive week-start from Asia/Bangkok date,
not from local browser timezone.
"""
import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).parent.parent
HOME_HABITS_JS = REPO_ROOT / "frontend" / "js" / "home-habits.js"


def _js():
    return HOME_HABITS_JS.read_text(encoding="utf-8")


# ── AC: currentMonday uses Bangkok timezone, not local date ──────────────────

def test_currentmonday_uses_asia_bangkok_timezone():
    """AC: currentMonday() derives week boundary from Asia/Bangkok timezone.

    Must call toLocaleDateString with { timeZone: 'Asia/Bangkok' } (or
    equivalent), matching the pattern in workout-form.js:5.
    """
    js = _js()
    assert "Asia/Bangkok" in js, (
        "currentMonday() must use Asia/Bangkok timezone; "
        "'Asia/Bangkok' string not found in home-habits.js"
    )


def test_currentmonday_uses_tolocaldatestring_en_ca():
    """AC: currentMonday() uses toLocaleDateString('en-CA', ...) to get Bangkok YYYY-MM-DD.

    The en-CA locale produces YYYY-MM-DD format — same pattern workout-form.js uses.
    """
    js = _js()
    assert "en-CA" in js, (
        "currentMonday() must use toLocaleDateString('en-CA', ...) to get "
        "Bangkok date in YYYY-MM-DD format"
    )


def test_currentmonday_does_not_use_raw_getday_for_boundary():
    """AC: currentMonday() must NOT rely solely on new Date().getDay() for week boundary.

    getDay() returns local-timezone weekday; using it alone gives wrong Monday
    for non-Bangkok users. The function may still call getDay() on a parsed
    Bangkok date object, but must not call it on a plain `new Date()` to derive
    the week boundary.
    """
    js = _js()
    # The old pattern was:
    #   var today = new Date();
    #   var day = today.getDay();
    # We check the raw local-tz call is gone from currentMonday.
    # Grab just the currentMonday function body.
    match = re.search(
        r"function currentMonday\(\)\s*\{(.*?)\}",
        js,
        re.DOTALL,
    )
    assert match, "currentMonday() function not found in home-habits.js"
    body = match.group(1)
    # Must not use pattern: new Date().getDay() or today.getDay() where today=new Date()
    # Simple heuristic: no standalone `new Date().getDay()` call
    assert "new Date().getDay()" not in body, (
        "currentMonday() must not call new Date().getDay() — "
        "that reads local timezone, not Bangkok"
    )


def test_currentmonday_computes_monday_from_bangkok_date_string():
    """AC: currentMonday() splits Bangkok YYYY-MM-DD and constructs a Monday Date.

    After getting Bangkok date via toLocaleDateString, the function must parse
    year/month/day from that string and use them to build the Monday Date object,
    so it's anchored to Bangkok date, not local date.
    """
    js = _js()
    # Find currentMonday's position and grab the surrounding text.
    # Using a greedy capture between currentMonday's opening brace and the next
    # top-level function declaration avoids false-ending on nested {}.
    start = js.find("function currentMonday()")
    assert start != -1, "currentMonday() function not found in home-habits.js"
    end = js.find("\n  function ", start + 1)
    body = js[start:end] if end != -1 else js[start:start + 400]
    # Must split or parse the YYYY-MM-DD string: look for split('-') or parseInt patterns
    has_split = "split('-')" in body or 'split("-")' in body
    has_parse = re.search(r"parseInt|Number\(|parts\[|ymd\[|\[0\]|\[1\]|\[2\]", body)
    assert has_split or has_parse, (
        "currentMonday() must parse the Bangkok YYYY-MM-DD string "
        "(e.g. split('-') or parseInt) to extract year/month/day"
    )


def test_currentmonday_returns_a_monday():
    """AC: currentMonday() function signature returns a value used as week_start.

    The return value must be used in isoDate() call for week_start.
    The JS must wire: isoDate(currentMonday()) for the week_start query param.
    """
    js = _js()
    assert "isoDate(currentMonday())" in js, (
        "home-habits.js must call isoDate(currentMonday()) for week_start"
    )


# ── Regression: existing widget functionality unchanged ───────────────────────

def test_home_habits_js_still_calls_api_habits():
    """Regression: /api/habits fetch still present after refactor."""
    js = _js()
    assert "/api/habits" in js, "home-habits.js must still call /api/habits"


def test_home_habits_js_still_calls_progress_endpoint():
    """Regression: /api/habits/{id}/progress?week_start= still present."""
    js = _js()
    assert "/progress" in js and "week_start" in js, (
        "home-habits.js must still call /api/habits/{id}/progress?week_start=..."
    )
