"""Tests for issue #815: Use per-user timezone in performance tab date helpers.

AC items tested:
  AC1 - _boot() fetches /api/user-preferences and caches the timezone value
        in a module-level variable before rendering any chart data.
  AC2 - _today() passes the cached timezone value to toLocaleDateString()
        instead of the hardcoded 'Asia/Bangkok' string.
  AC3 - _dateMinusDays() passes the cached timezone value to toLocaleDateString()
        instead of the hardcoded 'Asia/Bangkok' string.
  AC4 - If GET /api/user-preferences fails or returns no timezone field,
        both helpers fall back to a sensible default without throwing an error.
  AC5 - A user whose stored timezone differs from Asia/Bangkok sees a
        start_date/end_date range and ACWR 35-day window that correctly
        reflects their local midnight (timezone variable is applied, not hardcoded).
"""
import os
import re

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


import pytest


@pytest.fixture(scope="module")
def perf_js():
    path = os.path.join(REPO_ROOT, "frontend", "js", "training-performance.js")
    with open(path, encoding="utf-8") as f:
        return f.read()


# ── AC1: _boot() fetches /api/user-preferences ───────────────────────────────

def test_boot_fetches_user_preferences(perf_js):
    """AC1: The boot/init function must fetch /api/user-preferences."""
    assert "/api/user-preferences" in perf_js, (
        "_boot() (or equivalent init) must fetch GET /api/user-preferences "
        "to retrieve the per-user timezone"
    )


def test_module_level_timezone_variable_exists(perf_js):
    """AC1: A module-level variable must cache the resolved timezone."""
    # The variable should be declared at module scope (var _tz or var _timezone etc.)
    has_tz_var = (
        "var _tz" in perf_js
        or "var _userTimezone" in perf_js
        or "var _timezone" in perf_js
        or "_tz " in perf_js
        or "_userTz" in perf_js
    )
    assert has_tz_var, (
        "A module-level variable must be declared to cache the user's timezone "
        "(e.g. var _tz, var _userTimezone, var _timezone)"
    )


def test_timezone_cached_from_preferences(perf_js):
    """AC1: The cached timezone variable must be assigned from the preferences response."""
    # The assignment should reference the timezone field from the API response
    has_assignment = (
        ".timezone" in perf_js
        or "['timezone']" in perf_js
        or '["timezone"]' in perf_js
    )
    assert has_assignment, (
        "The module-level timezone variable must be assigned from "
        "the preferences response (response.row.timezone or data.timezone)"
    )


# ── AC2: _today() uses cached timezone ───────────────────────────────────────

def test_today_does_not_hardcode_bangkok(perf_js):
    """AC2: _today() must NOT hardcode 'Asia/Bangkok' as the timeZone option."""
    # Extract the _today function body
    match = re.search(r'function _today\(\)\s*\{([^}]+)\}', perf_js)
    assert match, "_today() function must be present in training-performance.js"
    body = match.group(1)
    assert "'Asia/Bangkok'" not in body and '"Asia/Bangkok"' not in body, (
        "_today() must not hardcode 'Asia/Bangkok'; it must use the cached "
        "timezone variable instead"
    )


def test_today_uses_timezone_variable(perf_js):
    """AC2: _today() must reference the module-level timezone variable."""
    match = re.search(r'function _today\(\)\s*\{([^}]+)\}', perf_js)
    assert match, "_today() function must be present in training-performance.js"
    body = match.group(1)
    # Should reference a timezone variable (not the literal string)
    has_tz_ref = (
        "_tz" in body
        or "_userTimezone" in body
        or "_timezone" in body
        or "_userTz" in body
    )
    assert has_tz_ref, (
        "_today() must pass the module-level timezone variable to "
        "toLocaleDateString() instead of a hardcoded string"
    )


# ── AC3: _dateMinusDays() uses cached timezone ────────────────────────────────

def test_date_minus_days_does_not_hardcode_bangkok(perf_js):
    """AC3: _dateMinusDays() must NOT hardcode 'Asia/Bangkok' as the timeZone option."""
    match = re.search(r'function _dateMinusDays\(days\)\s*\{([^}]+)\}', perf_js)
    assert match, "_dateMinusDays() function must be present in training-performance.js"
    body = match.group(1)
    assert "'Asia/Bangkok'" not in body and '"Asia/Bangkok"' not in body, (
        "_dateMinusDays() must not hardcode 'Asia/Bangkok'; it must use the "
        "cached timezone variable instead"
    )


def test_date_minus_days_uses_timezone_variable(perf_js):
    """AC3: _dateMinusDays() must reference the module-level timezone variable."""
    match = re.search(r'function _dateMinusDays\(days\)\s*\{([^}]+)\}', perf_js)
    assert match, "_dateMinusDays() function must be present in training-performance.js"
    body = match.group(1)
    has_tz_ref = (
        "_tz" in body
        or "_userTimezone" in body
        or "_timezone" in body
        or "_userTz" in body
    )
    assert has_tz_ref, (
        "_dateMinusDays() must pass the module-level timezone variable to "
        "toLocaleDateString() instead of a hardcoded string"
    )


# ── AC4: Graceful fallback on failure ────────────────────────────────────────

def test_preferences_fetch_has_fallback(perf_js):
    """AC4: The preferences fetch must include error handling (catch/fallback)."""
    # Find the actual fetch( call for /api/user-preferences (not a comment occurrence).
    fetch_idx = perf_js.find("fetch('/api/user-preferences'")
    if fetch_idx == -1:
        fetch_idx = perf_js.find('fetch("/api/user-preferences"')
    assert fetch_idx != -1, "fetch('/api/user-preferences') call must be present"
    # Look for a .catch within 600 chars after the fetch call
    nearby = perf_js[fetch_idx:fetch_idx + 600]
    has_catch = ".catch" in nearby or "catch(" in nearby
    assert has_catch, (
        "The /api/user-preferences fetch must have a .catch handler to "
        "ensure the page does not break when the request fails"
    )


def test_timezone_fallback_value_defined(perf_js):
    """AC4: A fallback timezone value (e.g. 'UTC') must be used when preferences unavailable."""
    has_fallback = (
        "'UTC'" in perf_js
        or '"UTC"' in perf_js
        or "Intl.DateTimeFormat().resolvedOptions().timeZone" in perf_js
    )
    assert has_fallback, (
        "A fallback timezone value must be present (e.g. 'UTC' or "
        "Intl.DateTimeFormat().resolvedOptions().timeZone) for when "
        "the preferences fetch fails or returns no timezone"
    )


# ── AC5: Timezone applies to chart date range + ACWR window ──────────────────

def test_fitness_chart_uses_date_helpers(perf_js):
    """AC5: _loadFitnessChart uses _today() and _dateMinusDays() for start/end dates."""
    match = re.search(
        r'function _loadFitnessChart\(rangeKey\)\s*\{(.+?)^  \}',
        perf_js, re.DOTALL | re.MULTILINE
    )
    assert match, "_loadFitnessChart() function must be present"
    body = match.group(1)
    assert "_today()" in body, (
        "_loadFitnessChart() must call _today() for the end date "
        "so it respects the per-user timezone"
    )
    assert "_dateMinusDays(" in body, (
        "_loadFitnessChart() must call _dateMinusDays() for the start date "
        "so it respects the per-user timezone"
    )


def test_acwr_uses_date_helpers(perf_js):
    """AC5: _loadAcwr() uses _today() and _dateMinusDays() for its 35-day window."""
    match = re.search(
        r'function _loadAcwr\(\)\s*\{(.+?)^  \}',
        perf_js, re.DOTALL | re.MULTILINE
    )
    assert match, "_loadAcwr() function must be present"
    body = match.group(1)
    assert "_today()" in body, (
        "_loadAcwr() must call _today() for the end date "
        "so it respects the per-user timezone"
    )
    assert "_dateMinusDays(" in body, (
        "_loadAcwr() must call _dateMinusDays() for the start date "
        "so it respects the per-user timezone"
    )


def test_loadall_deferred_until_timezone_resolved(perf_js):
    """AC1/AC5: _loadAll() must not be called before the timezone is resolved.

    The preferences fetch must complete (or fail gracefully) before chart
    data is requested, so both helpers have the correct timezone available.
    _boot() must await the preferences fetch before calling _loadAll().
    """
    # _loadAll must be called INSIDE the preferences fetch callback/then,
    # not directly at the top of _boot().
    # Check that _loadAll is not called directly right after _athleteId assignment
    # without going through the preferences fetch.
    boot_match = re.search(r'function _boot\(\)\s*\{(.+?)^  \}', perf_js, re.DOTALL | re.MULTILINE)
    assert boot_match, "_boot() function must be present"
    boot_body = boot_match.group(1)

    # _loadAll must not be called as a bare statement at the top level of _boot
    # without the preferences fetch wrapping it.
    # The preferences fetch URL must appear before any _loadAll call in _boot.
    prefs_pos = boot_body.find("/api/user-preferences")
    load_all_pos = boot_body.find("_loadAll(")
    # If _loadAll is called in _boot, it must come after the preferences fetch
    # (i.e. be inside the then() callback, or prefs fetch must happen first).
    # A bare _loadAll() call before the prefs fetch would mean the wrong timezone.
    if load_all_pos != -1 and prefs_pos != -1:
        assert load_all_pos > prefs_pos, (
            "_loadAll() must be called after the /api/user-preferences fetch "
            "is initiated in _boot(), not before"
        )
