"""Tests for issue #868: binary+weekly habit silently hardcodes weekly_target=7 with no UI feedback."""
import os
import re
import pytest


@pytest.fixture(scope="module")
def habits_js():
    js_path = os.path.join(os.path.dirname(__file__), "../frontend/js/habits.js")
    with open(js_path, encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope="module")
def habits_html():
    html_path = os.path.join(os.path.dirname(__file__), "../frontend/pages/habits.html")
    with open(html_path, encoding="utf-8") as f:
        return f.read()


def _extract_fn(js, fn_name):
    """Extract function body from JS source by name."""
    start = js.find(f"function {fn_name}(")
    assert start != -1, f"function {fn_name} not found in JS"
    end = js.find("\nfunction ", start + 1)
    return js[start:] if end == -1 else js[start:end]


def test_868__sfUpdateVisibility_disables_weekly_for_binary(habits_js):
    """AC: _sfUpdateVisibility disables the 'weekly' schedule option when habit_type is binary."""
    fn_body = _extract_fn(habits_js, "_sfUpdateVisibility")
    # Must branch on binary habit type
    assert (
        "habitType === 'binary'" in fn_body or "habitType == 'binary'" in fn_body
    ), "_sfUpdateVisibility must branch on habitType === 'binary'"
    # Must set disabled on the weekly option
    assert (
        "disabled" in fn_body
    ), "_sfUpdateVisibility must disable the weekly option for binary habit type"
    # The disabled attribute must be linked to the binary check
    assert (
        "weekly" in fn_body.lower()
    ), "_sfUpdateVisibility must reference 'weekly' when handling binary disable"


def test_868__sfUpdateVisibility_resets_schedule_to_daily_for_binary_weekly(habits_js):
    """AC: If binary is selected while schedule is 'weekly', _sfUpdateVisibility resets schedule to 'daily'."""
    fn_body = _extract_fn(habits_js, "_sfUpdateVisibility")
    # Must detect binary + weekly combination and reset to daily
    assert (
        "=== 'weekly'" in fn_body or "== 'weekly'" in fn_body
    ), "_sfUpdateVisibility must detect 'weekly' schedule within its own body"
    assert (
        "= 'daily'" in fn_body
    ), "_sfUpdateVisibility must reset schedule to 'daily' when binary is selected"


def test_868__sfFormToApiPayload_binary_weekly_no_silent_7(habits_js):
    """AC: _sfFormToApiPayload must not silently hardcode weekly_target=7 for binary+weekly."""
    fn_body = _extract_fn(habits_js, "_sfFormToApiPayload")
    assert (
        "weekly_target = 7" not in fn_body
    ), "_sfFormToApiPayload must not silently hardcode weekly_target=7"


def test_868__binary_daily_payload_unaffected(habits_js):
    """AC: binary+daily still produces tracking_type='daily_checkmark' (regression guard)."""
    fn_body = _extract_fn(habits_js, "_sfFormToApiPayload")
    assert "daily_checkmark" in fn_body, "binary+daily must still produce daily_checkmark"


def test_868__schedule_type_html_still_has_weekly_option(habits_html):
    """AC: The 'weekly' option stays in the HTML; it is disabled dynamically, not removed from DOM."""
    assert 'value="weekly"' in habits_html, "HTML must retain the weekly option in schedule dropdown"
    assert 'id="habit-form-schedule-type"' in habits_html
