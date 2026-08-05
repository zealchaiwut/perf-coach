"""Tests for issue #598: Use user-preference HR band for Zone 2 detection in Run view.

Each test is anchored to a specific acceptance criterion from the issue body.

Acceptance criteria:
  AC1 — renderRunView calls GET /api/user-preferences once per page load and
         caches the result (no repeated requests on re-render).
  AC2 — Per-lap Zone 2 detection uses row.zone2_hr_min / row.zone2_hr_max with
         ZONE2_HR_MIN / ZONE2_HR_MAX as fallback.
  AC3 — The (HR X–Y …) note reflects the effective Zone 2 band.
  AC4 — Covered by implementation: reopening a run after changing settings
         (= new page load) picks up the new band.
  AC5 — When user has no saved Zone 2 preferences, view uses 130–155 defaults.
  AC6 — If GET /api/user-preferences fails, view falls back silently to constants.
"""
import pathlib

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_TL_JS = _ROOT / "frontend" / "js" / "training-log.js"
_RD_JS = _ROOT / "frontend" / "js" / "lib" / "run-detail-view.js"


def _src() -> str:
    assert _TL_JS.exists(), f"Expected file not found: {_TL_JS}"
    return _TL_JS.read_text()


def _run_view_src() -> str:
    """Run detail rendering lives in run-detail-view.js (v4); training-log delegates."""
    assert _RD_JS.exists(), f"Expected file not found: {_RD_JS}"
    return _RD_JS.read_text()


# ═══════════════════════════════════════════════════════════════════════════════
# AC1 — Preferences fetch is issued once at module level and cached
# ═══════════════════════════════════════════════════════════════════════════════

def test_ac1_prefs_fetch_is_module_level_promise():
    """The preferences fetch must be stored in a module-level promise variable so it
    runs exactly once per page load regardless of how many runs are opened."""
    src = _src()
    # Must have a module-level variable holding the fetch promise
    assert "_userPrefsFetch" in src or "_prefsFetch" in src or "_prefsFetchPromise" in src, (
        "training-log.js must declare a module-level variable that holds the "
        "GET /api/user-preferences promise (e.g. _userPrefsFetch)"
    )


def test_ac1_prefs_fetch_targets_correct_endpoint():
    """The cached fetch must call /api/user-preferences."""
    src = _src()
    assert "/api/user-preferences" in src, (
        "training-log.js must fetch /api/user-preferences for Zone 2 preferences"
    )


def test_ac1_prefs_fetch_not_inside_render_run_view():
    """The fetch must NOT be defined inside renderRunView — it must be a module-level
    (or singleton) promise so it is not repeated on every re-render."""
    src = _src()
    # Find the renderRunView function body and confirm fetch('/api/user-preferences')
    # is NOT called inside it (only the cached variable is referenced).
    rv_start = src.find("function renderRunView(")
    assert rv_start != -1, "renderRunView must exist in training-log.js"

    # Find the end of renderRunView by counting braces from its opening brace.
    brace_start = src.find("{", rv_start)
    depth = 0
    i = brace_start
    while i < len(src):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                break
        i += 1
    rv_body = src[rv_start:i + 1]

    # The body must NOT itself call fetch('/api/user-preferences')
    assert "fetch('/api/user-preferences')" not in rv_body and \
           'fetch("/api/user-preferences")' not in rv_body, (
        "renderRunView must NOT issue its own fetch('/api/user-preferences'); "
        "it must receive prefs from the cached module-level promise"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# AC2 — Per-lap Zone 2 detection uses user preference values with constant fallback
# ═══════════════════════════════════════════════════════════════════════════════

def test_ac2_zone2_detection_references_prefs_min():
    """Run detail view must use the user preference zone2_hr_min when available."""
    src = _run_view_src()
    assert "zone2_hr_min" in src, (
        "run-detail-view.js must reference zone2_hr_min from user preferences "
        "for per-lap Zone 2 detection"
    )


def test_ac2_zone2_detection_references_prefs_max():
    """Run detail view must use the user preference zone2_hr_max when available."""
    src = _run_view_src()
    assert "zone2_hr_max" in src, (
        "run-detail-view.js must reference zone2_hr_max from user preferences "
        "for per-lap Zone 2 detection"
    )


def test_ac2_zone2_detection_falls_back_to_constants():
    """The fallback to Zone2.ZONE2_HR_MIN / MAX must still be present."""
    src = _run_view_src()
    assert "ZONE2_HR_MIN" in src, (
        "run-detail-view.js must keep ZONE2_HR_MIN as the fallback constant"
    )
    assert "ZONE2_HR_MAX" in src, (
        "run-detail-view.js must keep ZONE2_HR_MAX as the fallback constant"
    )


def test_ac2_zone2_detection_uses_effective_values_in_split_loop():
    """The split-level zone2 flag must be computed from effective (prefs-aware)
    min/max values, not the bare constants."""
    src = _run_view_src()
    # Verify that the zone2 assignment uses a variable (not the bare constant).
    z2_idx = src.find("zone2:")
    assert z2_idx != -1, "run-detail-view.js must set zone2 for each split"

    # Extract the line containing zone2
    line_start = src.rfind("\n", 0, z2_idx) + 1
    line_end = src.find("\n", z2_idx)
    z2_line = src[line_start:line_end]

    # The line must NOT directly reference RUN_DETAIL_ZONE2_HR_MIN / MAX
    assert "RUN_DETAIL_ZONE2_HR_MIN" not in z2_line and "RUN_DETAIL_ZONE2_HR_MAX" not in z2_line, (
        "The zone2 assignment must use local effective variables (e.g. z2min/z2max), "
        "not the bare RUN_DETAIL_ZONE2_HR_MIN / RUN_DETAIL_ZONE2_HR_MAX constants"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# AC3 — HR range note reflects effective Zone 2 band
# ═══════════════════════════════════════════════════════════════════════════════

def test_ac3_hr_note_uses_effective_min_variable():
    """The Z2 note line must insert the effective min variable, not the bare constant."""
    src = _run_view_src()
    note_idx = src.find("rv-z2-note")
    assert note_idx != -1, "run-detail-view.js must include the rv-z2-note element"

    note_end = src.find("</div>", note_idx)
    note_chunk = src[note_idx:note_end + 6]

    assert "RUN_DETAIL_ZONE2_HR_MIN" not in note_chunk and "RUN_DETAIL_ZONE2_HR_MAX" not in note_chunk, (
        "The rv-z2-note must use effective zone variables (e.g. z2min/z2max), "
        "not the bare RUN_DETAIL_ZONE2_HR_MIN / RUN_DETAIL_ZONE2_HR_MAX constants"
    )


def test_ac3_hr_note_still_shows_hr_range():
    """The Z2 note must still render an 'HR X–Y' pattern (with effective values)."""
    src = _run_view_src()
    assert "rv-z2-note" in src, "rv-z2-note element must be present in run-detail-view.js"
    assert "range will come from settings" not in src, (
        "The placeholder text 'range will come from settings' must be removed; "
        "the note must now show the actual effective HR band"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# AC5 — Defaults apply when no saved Zone 2 preferences
# ═══════════════════════════════════════════════════════════════════════════════

def test_ac5_null_check_before_using_prefs_value():
    """The code must guard against null zone2_hr_min values (using null-check or ??).
    When the prefs row has null values, RUN_DETAIL_ZONE2_HR_MIN is used."""
    src = _run_view_src()
    has_null_check = (
        "zone2_hr_min != null" in src
        or "zone2_hr_min !== null" in src
        or "zone2_hr_min ??" in src
        or "?? RUN_DETAIL_ZONE2_HR_MIN" in src
        or "|| RUN_DETAIL_ZONE2_HR_MIN" in src
    )
    assert has_null_check, (
        "run-detail-view.js must guard zone2_hr_min for null before using it, "
        "falling back to RUN_DETAIL_ZONE2_HR_MIN when null/undefined"
    )


def test_ac5_null_check_for_max():
    """Same null guard must exist for zone2_hr_max."""
    src = _run_view_src()
    has_null_check = (
        "zone2_hr_max != null" in src
        or "zone2_hr_max !== null" in src
        or "zone2_hr_max ??" in src
        or "?? RUN_DETAIL_ZONE2_HR_MAX" in src
        or "|| RUN_DETAIL_ZONE2_HR_MAX" in src
    )
    assert has_null_check, (
        "run-detail-view.js must guard zone2_hr_max for null before using it, "
        "falling back to RUN_DETAIL_ZONE2_HR_MAX when null/undefined"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# AC6 — Fetch failure falls back silently to constants
# ═══════════════════════════════════════════════════════════════════════════════

def test_ac6_prefs_fetch_has_catch_handler():
    """The preferences fetch chain must have a .catch() that returns null (or a safe
    fallback), so a network error never throws or breaks the Run view."""
    src = _src()
    # Find the prefs fetch promise and verify it has a catch
    # We look for .catch in proximity to /api/user-preferences
    prefs_idx = src.find("/api/user-preferences")
    assert prefs_idx != -1
    # Search within the next 500 chars for a .catch(
    nearby = src[prefs_idx:prefs_idx + 500]
    assert ".catch(" in nearby, (
        "The /api/user-preferences fetch must have a .catch() handler to "
        "silently fall back to defaults on network error or non-2xx response"
    )


def test_ac6_prefs_used_via_null_safe_access():
    """When prefs is null (failed fetch), the run view must still render using defaults.
    The prefs object access must be null-safe (e.g. prefs && prefs.row)."""
    src = _run_view_src()
    has_safe_access = (
        "prefs && prefs.row" in src
        or "prefs?.row" in src
        or "(prefs || {})" in src
        or "prefs ? prefs.row" in src
    )
    assert has_safe_access, (
        "run-detail-view.js must null-safely access the prefs argument (e.g. prefs && prefs.row) "
        "so that a failed/null prefs fetch does not throw"
    )
