"""Tests for issue #400: Reduce DOM-coupling in sync controls HTML.

Acceptance criteria verified (static analysis of settings.html):
(a) A JS variable tracks history-toggle open state — reads from the variable,
    not from classList.contains() each time.
(b) A JS variable tracks the "since date" value — updated on input change,
    used by preview/run-sync instead of reading el.value on every call.
(c) A JS variable tracks the preview-toggle checkbox state — updated on
    checkbox change, not read from DOM on each interaction.
(d) The history-toggle handler mutates state via the JS variable and syncs
    the DOM from it, rather than using the DOM as the source of truth.
"""
import pathlib
import re

SETTINGS_HTML = pathlib.Path(__file__).parents[1] / "frontend" / "pages" / "settings.html"


def _text():
    return SETTINGS_HTML.read_text()


# ── (a) History toggle: JS variable declared ─────────────────────────────────

def test_history_open_variable_declared():
    """_stravaHistoryOpen (or similar) must be declared as a var/let/const."""
    src = _text()
    found = re.search(
        r'\b(?:var|let|const)\s+_stravaHistoryOpen\b',
        src,
    )
    assert found, (
        "Expected a JS variable `_stravaHistoryOpen` declared near the other "
        "Strava state variables. Found none. Add: var _stravaHistoryOpen = false;"
    )


# ── (b) History toggle: handler uses variable, not classList.contains ─────────

def test_history_toggle_does_not_read_classlist_for_state():
    """Toggle handler must not use classList.contains('open') as state source."""
    src = _text()
    # The IIFE that wires the toggle is _initStravaHistoryToggle; check that
    # inside the click handler the open/closed decision comes from a variable,
    # not from classList.contains.
    toggle_fn = re.search(
        r'_initStravaHistoryToggle\(\)\s*\{(.+?)\}\s*\)\s*\(\)',
        src,
        re.DOTALL,
    )
    assert toggle_fn, "_initStravaHistoryToggle IIFE not found in settings.html"
    fn_body = toggle_fn.group(1)
    # Must NOT derive state by reading classList
    assert "classList.contains('open')" not in fn_body, (
        "_initStravaHistoryToggle still reads `classList.contains('open')` to "
        "determine state. Replace with `_stravaHistoryOpen` variable instead."
    )


def test_history_toggle_uses_history_open_variable():
    """Toggle handler must reference _stravaHistoryOpen to determine state."""
    src = _text()
    toggle_fn = re.search(
        r'_initStravaHistoryToggle\(\)\s*\{(.+?)\}\s*\)\s*\(\)',
        src,
        re.DOTALL,
    )
    assert toggle_fn, "_initStravaHistoryToggle IIFE not found in settings.html"
    fn_body = toggle_fn.group(1)
    assert '_stravaHistoryOpen' in fn_body, (
        "_initStravaHistoryToggle handler does not reference `_stravaHistoryOpen`. "
        "Use the variable to track open/closed state."
    )


# ── (c) Since-date value: JS variable declared ────────────────────────────────

def test_since_date_variable_declared():
    """_stravaSinceDateValue (or similar) must be declared as a var/let/const."""
    src = _text()
    found = re.search(
        r'\b(?:var|let|const)\s+_stravaSinceDateValue\b',
        src,
    )
    assert found, (
        "Expected a JS variable `_stravaSinceDateValue` to hold the date-picker "
        "value. Add: var _stravaSinceDateValue = null;"
    )


def test_since_date_input_change_updates_variable():
    """An event listener on the since-date input must update _stravaSinceDateValue."""
    src = _text()
    # Must wire up a 'change' or 'input' event on strava-since-date that sets
    # _stravaSinceDateValue.
    assert '_stravaSinceDateValue' in src, (
        "`_stravaSinceDateValue` not referenced anywhere in settings.html"
    )
    # Verify assignment pattern: _stravaSinceDateValue = ... inside a listener
    assignment = re.search(
        r'_stravaSinceDateValue\s*=',
        src,
    )
    assert assignment, (
        "`_stravaSinceDateValue` is never assigned. Wire a change/input listener "
        "on #strava-since-date to keep the variable in sync."
    )


def test_sinceDate_function_uses_variable():
    """_sinceDate() must return _stravaSinceDateValue (not always read el.value)."""
    src = _text()
    since_fn = re.search(
        r'function _sinceDate\(\)\s*\{([^}]+)\}',
        src,
        re.DOTALL,
    )
    assert since_fn, "_sinceDate() function not found in settings.html"
    fn_body = since_fn.group(1)
    assert '_stravaSinceDateValue' in fn_body, (
        "_sinceDate() does not use `_stravaSinceDateValue`. Update the function "
        "to return the variable (falling back to DOM only when the panel is first "
        "rendered and the variable is null)."
    )


# ── (d) Preview-toggle checkbox: JS variable declared ────────────────────────

def test_show_preview_variable_declared():
    """_stravaShowPreview (or similar) must be declared as a var/let/const."""
    src = _text()
    found = re.search(
        r'\b(?:var|let|const)\s+_stravaShowPreview\b',
        src,
    )
    assert found, (
        "Expected a JS variable `_stravaShowPreview` to track the preview-toggle "
        "checkbox. Add: var _stravaShowPreview = true;"
    )


def test_preview_toggle_change_updates_variable():
    """Checkbox change listener must assign _stravaShowPreview."""
    src = _text()
    assignment = re.search(
        r'_stravaShowPreview\s*=',
        src,
    )
    assert assignment, (
        "`_stravaShowPreview` is never assigned. Wire a change listener on "
        "#strava-preview-toggle to keep the variable in sync with the checkbox."
    )
