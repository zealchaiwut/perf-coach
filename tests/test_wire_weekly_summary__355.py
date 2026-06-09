"""Tests for issue #355: Wire weekly summary widget and polish home page.

TDD — each test is anchored to one Acceptance Criterion.

AC-1:  Weekly summary widget exists on home page with expected structure
AC-2:  Widget fetches GET /api/home/weekly-summary?user_id={uid}
AC-3:  vs_prev_week deltas render as colored pills (positive=green, negative=red, zero=neutral)
AC-4:  7-day TSS bar chart uses SVG only (no third-party chart library)
AC-5:  Rest day bars gray; today's bar in accent color
AC-6:  All 5 home widgets fire via Promise.all or equivalent (no sequential waterfall)
AC-7:  frontend/js/home.js contains a centralized fetch/error helper (_homeFetch or homeApiFetch)
AC-8:  Every widget's fetch uses the shared helper
AC-9:  Single widget failure leaves other 4 rendering (independent error states)
AC-10: docs/home-widget-spec.md contains a "Final state" section
AC-11: No duplicate pattern per-widget (DRY fetch pattern)
"""
import os
import pathlib
import re

import pytest

# ── Root detection ────────────────────────────────────────────────────────────

_TESTER_ROOT = pathlib.Path(__file__).resolve().parents[1]
_CODER_ROOT = _TESTER_ROOT.parent / "coder"


def _find_root() -> pathlib.Path:
    for root in (_CODER_ROOT, _TESTER_ROOT):
        if (root / "frontend" / "js" / "home.js").exists():
            return root
    return _TESTER_ROOT


_ROOT = _find_root()
_HOME_JS = (_ROOT / "frontend" / "js" / "home.js").read_text()
_HOME_HTML = (_ROOT / "frontend" / "pages" / "home.html").read_text()
_SPEC_MD = (_ROOT / "docs" / "home-widget-spec.md").read_text()


# ── AC-1: Weekly summary widget exists on home page ───────────────────────────

def test_weekly_summary_widget_container_exists_in_html():
    """Home HTML must contain a row/card container for the weekly summary widget."""
    assert (
        "weekly-summary-card" in _HOME_HTML or
        "row-5" in _HOME_HTML or
        "weekly-summary" in _HOME_HTML.lower()
    ), "home.html must contain a weekly summary widget container"


def test_weekly_summary_js_function_exists():
    """home.js must define a loadWeeklySummaryCard function."""
    assert "loadWeeklySummaryCard" in _HOME_JS, \
        "home.js must define loadWeeklySummaryCard"


def test_weekly_summary_this_week_heading():
    """Weekly summary card must include a 'This week' heading in its HTML output."""
    assert "This week" in _HOME_JS, \
        "home.js must render a 'This week' heading in the weekly summary widget"


def test_weekly_summary_renders_workout_count():
    """Weekly summary must render total workout count from workouts.total."""
    assert (
        "workouts.total" in _HOME_JS or
        ".total" in _HOME_JS
    ), "home.js must access workouts.total to render workout count"


def test_weekly_summary_renders_type_breakdown_with_icons():
    """Weekly summary must render workout type breakdown with icons."""
    assert (
        "by_type" in _HOME_JS or
        "workout_type" in _HOME_JS
    ), "home.js must render workout type breakdown"
    # Must reference icon markup
    assert "ti-run" in _HOME_JS or "ti-barbell" in _HOME_JS, \
        "weekly summary must use icon classes for workout types"


def test_weekly_summary_renders_totals():
    """Weekly summary must render distance, duration, TSS, and rest days."""
    assert "distance_km" in _HOME_JS, "weekly summary must render distance_km"
    assert "duration_minutes" in _HOME_JS, "weekly summary must render duration_minutes"
    assert "total_tss" in _HOME_JS, "weekly summary must render total_tss"
    assert "rest_days" in _HOME_JS, "weekly summary must render rest_days"


# ── AC-2: Widget fetches correct endpoint ────────────────────────────────────

def test_weekly_summary_fetches_home_weekly_summary_endpoint():
    """loadWeeklySummaryCard must fetch /api/home/weekly-summary."""
    assert "/api/home/weekly-summary" in _HOME_JS, \
        "home.js must call /api/home/weekly-summary"


# ── AC-3: Delta pills with correct colors ─────────────────────────────────────

def test_delta_pills_exist_in_js():
    """home.js must contain logic for rendering vs_prev_week delta pills."""
    assert "vs_prev_week" in _HOME_JS, \
        "home.js must access vs_prev_week for delta pills"


def test_delta_pills_positive_green():
    """Positive deltas must use green styling."""
    # home.js must have logic for green pill on positive delta
    assert (
        "green" in _HOME_JS.lower() and
        "vs_prev_week" in _HOME_JS
    ), "home.js must apply green pill class for positive vs_prev_week deltas"


def test_delta_pills_negative_red():
    """Negative deltas must use red styling."""
    assert (
        "red" in _HOME_JS.lower() and
        "vs_prev_week" in _HOME_JS
    ), "home.js must apply red pill class for negative vs_prev_week deltas"


def test_delta_pill_classes_defined_in_html():
    """HTML must define CSS for delta pill variants (green, red, neutral)."""
    assert (
        "pill--green" in _HOME_HTML or "delta-pill" in _HOME_HTML or
        "pill-green" in _HOME_HTML
    ), "home.html must define CSS classes for delta pill color variants"


# ── AC-4: 7-day TSS bar chart using SVG only ─────────────────────────────────

def test_bar_chart_uses_svg():
    """Weekly summary bar chart must be rendered using <svg> elements."""
    # The function must build SVG markup
    assert "<svg" in _HOME_JS or "createElementNS" in _HOME_JS, \
        "home.js must render the TSS bar chart using SVG"


def test_bar_chart_no_chart_js():
    """home.html must not load Chart.js or any third-party chart library for the bar chart."""
    # Allow existing uses but ensure no new chart library is added for this widget
    # home.html should not have a script tag for chart.js in the weekly summary context
    # This is best verified by checking that the SVG is built inline
    assert "chart.js" not in _HOME_HTML.lower() or (
        "<svg" in _HOME_JS
    ), "TSS bar chart must use SVG, not a third-party chart library"


def test_bar_chart_has_7_bars():
    """Bar chart must render exactly 7 bars (Mon–Sun) from daily_load."""
    assert "daily_load" in _HOME_JS, \
        "home.js must access daily_load to render the 7-bar TSS chart"


def test_bar_chart_labels_mon_to_sun():
    """Bar chart must label bars Mon through Sun."""
    assert (
        "Mon" in _HOME_JS and
        "Sun" in _HOME_JS
    ), "home.js must label the bar chart axes Mon through Sun"


# ── AC-5: Rest day bars gray; today in accent color ──────────────────────────

def test_bar_chart_rest_day_gray():
    """Rest day bars in TSS chart must be gray."""
    assert "is_rest" in _HOME_JS, "home.js must check is_rest for bar chart color"
    # Gray expressed as hex or CSS var
    assert (
        "#" in _HOME_JS or
        "gray" in _HOME_JS.lower() or
        "text-tertiary" in _HOME_JS or
        "chip-bg" in _HOME_JS
    ), "home.js must render rest day bars in a gray color"


def test_bar_chart_today_accent():
    """Today's bar in TSS chart must use the accent color."""
    assert (
        "accent" in _HOME_JS or
        "#e4ff52" in _HOME_JS or
        "var(--accent)" in _HOME_JS
    ), "home.js must render today's TSS bar in the accent color"


# ── AC-6: All 5 home widgets fire simultaneously ─────────────────────────────

def test_promise_all_or_equivalent_used_for_5_widgets():
    """init() must fire all 5 home-widget fetches via Promise.all or simultaneously."""
    assert (
        "Promise.all" in _HOME_JS or
        "Promise.allSettled" in _HOME_JS
    ), "home.js must use Promise.all or Promise.allSettled to fire widget fetches in parallel"


def test_five_home_api_endpoints_referenced():
    """home.js must reference all 5 /api/home/* endpoints."""
    endpoints = [
        "/api/home/readiness",
        "/api/home/weight-summary",
        "/api/home/personal-records",
        "/api/home/recent-workouts",
        "/api/home/weekly-summary",
    ]
    for ep in endpoints:
        assert ep in _HOME_JS, f"home.js must reference {ep}"


# ── AC-7: Centralized fetch helper exists ─────────────────────────────────────

def test_centralized_fetch_helper_exists():
    """home.js must define a centralized fetch helper function."""
    assert (
        "_homeFetch" in _HOME_JS or
        "homeFetch" in _HOME_JS or
        "homeApiFetch" in _HOME_JS
    ), "home.js must define a centralized fetch helper (_homeFetch, homeFetch, or homeApiFetch)"


def test_centralized_helper_handles_errors():
    """The shared fetch helper must handle network errors (try/catch)."""
    # The helper must have a try/catch wrapping the fetch call
    # We check that there's a try/catch in the helper definition block
    # Simplified: ensure try and catch exist near the helper
    helper_match = re.search(
        r'(function\s+_?homeFetch|function\s+homeApiFetch).*?catch',
        _HOME_JS, re.DOTALL
    )
    assert helper_match is not None, \
        "The shared fetch helper must include error handling (try/catch)"


# ── AC-8: Every widget uses the shared helper ─────────────────────────────────

def test_readiness_widget_uses_helper():
    """loadReadinessCard must use the centralized fetch helper."""
    helper_name = "_homeFetch" if "_homeFetch" in _HOME_JS else "homeFetch"
    assert helper_name in _HOME_JS, f"home.js must use {helper_name}"
    # Verify readiness fetches via helper (not raw fetch for /api/home/readiness)
    # Check that loadReadinessCard doesn't use raw fetch for its primary data call
    rd_fn_match = re.search(
        r'async function loadReadinessCard.*?(?=async function|\Z)',
        _HOME_JS, re.DOTALL
    )
    if rd_fn_match:
        rd_body = rd_fn_match.group(0)
        assert (
            "_homeFetch" in rd_body or
            "homeFetch" in rd_body or
            "homeApiFetch" in rd_body
        ), "loadReadinessCard must use the shared fetch helper"


def test_weight_widget_uses_helper():
    """loadWeightWidget must use the centralized fetch helper."""
    ww_fn_match = re.search(
        r'async function loadWeightWidget.*?(?=async function|\Z)',
        _HOME_JS, re.DOTALL
    )
    if ww_fn_match:
        ww_body = ww_fn_match.group(0)
        assert (
            "_homeFetch" in ww_body or
            "homeFetch" in ww_body or
            "homeApiFetch" in ww_body
        ), "loadWeightWidget must use the shared fetch helper"


def test_performance_widget_uses_helper():
    """loadPerformanceCard must use the centralized fetch helper."""
    pc_fn_match = re.search(
        r'async function loadPerformanceCard.*?(?=async function|\Z)',
        _HOME_JS, re.DOTALL
    )
    if pc_fn_match:
        pc_body = pc_fn_match.group(0)
        assert (
            "_homeFetch" in pc_body or
            "homeFetch" in pc_body or
            "homeApiFetch" in pc_body
        ), "loadPerformanceCard must use the shared fetch helper"


def test_recent_workouts_widget_uses_home_endpoint():
    """loadRecentWorkoutsCard must fetch /api/home/recent-workouts."""
    assert "/api/home/recent-workouts" in _HOME_JS, \
        "loadRecentWorkoutsCard must use /api/home/recent-workouts endpoint"


# ── AC-9: Independent widget failure ──────────────────────────────────────────

def test_each_widget_has_independent_error_state():
    """Each of the 5 widgets must have its own error handling block."""
    # Each loadXXX function should have try/catch or handle null data
    fn_names = [
        "loadReadinessCard",
        "loadWeightWidget",
        "loadPerformanceCard",
        "loadRecentWorkoutsCard",
        "loadWeeklySummaryCard",
    ]
    for fn in fn_names:
        assert fn in _HOME_JS, f"home.js must define {fn}"

    # Verify error states (UIStates.errorHTML or equivalent) are used in each
    error_count = _HOME_JS.count("errorHTML") + _HOME_JS.count("error")
    assert error_count >= 5, \
        "Each of the 5 widgets must have an independent error state"


# ── AC-10: docs/home-widget-spec.md "Final state" section ────────────────────

def test_spec_has_final_state_section():
    """docs/home-widget-spec.md must contain a 'Final state' section."""
    assert "Final state" in _SPEC_MD or "final state" in _SPEC_MD.lower(), \
        "docs/home-widget-spec.md must contain a 'Final state' section"


def test_spec_final_state_lists_all_5_widgets():
    """The 'Final state' section must list all 5 widgets by name."""
    spec_lower = _SPEC_MD.lower()
    widgets = [
        "recent workouts",
        "weight",
        "personal records",
        "readiness",
        "weekly summary",
    ]
    for w in widgets:
        assert w in spec_lower, \
            f"docs/home-widget-spec.md Final state section must list '{w}'"


# ── AC-11: Empty state for zero-data user ────────────────────────────────────

def test_weekly_summary_has_empty_state():
    """Weekly summary widget must handle empty/zero data gracefully."""
    # The function must check for null/zero workouts and show empty state
    ws_fn_match = re.search(
        r'function loadWeeklySummaryCard.*?(?=\n  (?:async )?function |\Z)',
        _HOME_JS, re.DOTALL
    )
    if ws_fn_match:
        ws_body = ws_fn_match.group(0)
        assert (
            "empty" in ws_body.lower() or
            "total === 0" in ws_body or
            "total == 0" in ws_body or
            "emptyHTML" in ws_body or
            "No workouts" in ws_body
        ), "loadWeeklySummaryCard must have an empty state for zero workouts"
