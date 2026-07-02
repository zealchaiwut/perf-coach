"""
Tests for issue #48: TSS vs next-day readiness overlay chart on Trends page
Server under test: http://127.0.0.1:9001
"""
import pathlib
import re

import httpx
import pytest

BASE = "http://127.0.0.1:9001"

HTML      = (pathlib.Path(__file__).parent.parent / "frontend" / "pages" / "trends.html").read_text()
JS        = (pathlib.Path(__file__).parent.parent / "frontend" / "js" / "trends.js").read_text()


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c


# ── AC-0: Regression guards (page still served) ───────────────────────────────

def test_ac0_trends_html_served(client):
    """GET /trends.html must return 200 — regression guard."""
    res = client.get("/trends.html")
    assert res.status_code == 200, (
        f"Expected 200, got {res.status_code}. "
        "The /trends.html route is missing from backend/main.py."
    )


def test_ac0_trends_route_served(client):
    """GET /trends must return 200 — regression guard."""
    res = client.get("/trends")
    assert res.status_code == 200, (
        f"Expected 200, got {res.status_code}. "
        "The /trends route is missing from backend/main.py."
    )


# ── AC-1: Chart title / subtitle ─────────────────────────────────────────────

def test_ac1_chart_title_in_html():
    """trends.html must display 'Training Load vs Next-Day Readiness' as a title or subtitle."""
    assert "Training Load vs Next-Day Readiness" in HTML, (
        "trends.html must include the chart title 'Training Load vs Next-Day Readiness' "
        "so the user immediately understands the time offset."
    )


def test_ac1_tss_slot_exists_in_html():
    """trends.html must contain a chart slot for the TSS overlay chart."""
    assert "slot-tss" in HTML, (
        "trends.html must define a chart slot with id 'slot-tss' for the TSS overlay chart."
    )


def test_ac1_subtitle_conveys_time_offset():
    """trends.html must include a subtitle or description that clarifies the readiness offset."""
    has_offset_hint = (
        "following" in HTML.lower() or
        "next" in HTML.lower() or
        "offset" in HTML.lower() or
        "+1" in HTML
    )
    assert has_offset_hint, (
        "trends.html must include a subtitle or note indicating that readiness is "
        "offset by one day (e.g., 'following day', 'next day', or '+1 day')."
    )


# ── AC-2: Dual-axis bar + line chart ─────────────────────────────────────────

def test_ac2_dual_axis_defined_in_js():
    """trends.js must define two y-axes: one for TSS (left) and one for readiness (right)."""
    assert "yTSS" in JS or "yAxisID" in JS, (
        "trends.js must define separate y-axes for TSS and readiness "
        "(look for yAxisID assignments or 'yTSS' scale key)."
    )
    assert "position: 'left'" in JS or "position:'left'" in JS, (
        "trends.js must place the TSS axis on the left."
    )
    assert "position: 'right'" in JS or "position:'right'" in JS, (
        "trends.js must place the readiness axis on the right."
    )


def test_ac2_tss_axis_labeled():
    """trends.js must label the TSS y-axis with 'TSS'."""
    assert "'TSS'" in JS or '"TSS"' in JS or "text: 'TSS'" in JS or 'text: "TSS"' in JS, (
        "trends.js must label the TSS (left) y-axis with 'TSS'."
    )


def test_ac2_readiness_axis_labeled():
    """trends.js must label the readiness y-axis with 'Readiness'."""
    assert "Readiness" in JS, (
        "trends.js must label the readiness (right) y-axis so the user knows what the scale represents."
    )


def test_ac2_bar_dataset_for_tss():
    """trends.js must configure a bar-type dataset for TSS."""
    assert "type: 'bar'" in JS or "type:'bar'" in JS, (
        "trends.js must include a bar-type dataset for daily TSS values."
    )


def test_ac2_line_dataset_for_readiness():
    """trends.js must configure a line-type dataset for next-day readiness."""
    assert "type: 'line'" in JS or "type:'line'" in JS, (
        "trends.js must include a line-type dataset for next-day readiness."
    )


def test_ac2_readiness_max_100():
    """Readiness axis must be capped at 100."""
    assert "max: 100" in JS or "max:100" in JS, (
        "trends.js readiness y-axis must set max: 100."
    )


# ── AC-3: +1 day offset for readiness ────────────────────────────────────────

def test_ac3_add_one_day_function_exists():
    """trends.js must implement a +1 day offset so readiness aligns to the next day."""
    has_offset = (
        "addOneDay" in JS or
        "setDate" in JS or
        "nextDay" in JS or
        "+ 1" in JS or
        "+1" in JS
    )
    assert has_offset, (
        "trends.js must offset readiness by +1 day so a TSS bar on day N aligns with "
        "the readiness value on day N+1. Implement addOneDay() or equivalent."
    )


def test_ac3_offset_applied_when_building_datasets():
    """The +1 day offset must be applied when building the readiness dataset."""
    assert "addOneDay" in JS or "nextDay" in JS or (
        "setDate" in JS and "readiness" in JS.lower()
    ), (
        "trends.js must call the day-offset helper when populating the readiness dataset "
        "so TSS bar on day N aligns with readiness on day N+1."
    )


# ── AC-4: TSS summed per day ──────────────────────────────────────────────────

def test_ac4_tss_summed_per_day():
    """trends.js must sum multiple TSS entries for the same date into a single bar."""
    assert "buildTSSByDate" in JS or "byDate" in JS or "byDate[date]" in JS or (
        "byDate[" in JS and "+" in JS
    ), (
        "trends.js must aggregate multiple workouts on the same day into a single TSS bar "
        "(e.g., via buildTSSByDate that adds tss to byDate[date])."
    )


def test_ac5_empty_state_message_in_js():
    """trends.js must show the specific empty-state message when < 2 TSS+readiness pairs."""
    assert "Not enough data" in JS, (
        "trends.js must display 'Not enough data — log at least 2 days of workouts "
        "and next-day readiness to see this chart' when fewer than 2 valid pairs exist."
    )


def test_ac5_empty_state_full_text_in_js():
    """The exact empty-state message from the AC must appear in trends.js."""
    expected = "Not enough data — log at least 2 days of workouts and next-day readiness to see this chart"
    assert expected in JS, (
        f"trends.js must contain the exact empty-state message:\n  '{expected}'\n"
        "This message is specified in the acceptance criteria."
    )


def test_ac5_valid_pairs_threshold_is_2():
    """trends.js must check for at least 2 valid TSS+readiness pairs before rendering."""
    assert "< 2" in JS or "validPairs" in JS or "pairs" in JS.lower(), (
        "trends.js must guard the chart render behind a check for ≥ 2 valid TSS+readiness pairs."
    )


def test_ac5_empty_state_shown_in_tss_slot():
    """trends.js must call the empty-state renderer for the TSS slot when data is insufficient."""
    assert "showTSSEmpty" in JS or (
        "slot-tss" in JS and ("showEmpty" in JS or "empty" in JS.lower())
    ), (
        "trends.js must render an empty state inside the TSS chart slot when there are "
        "fewer than 2 valid TSS+readiness day-pairs."
    )


# ── AC-6: Date-range picker integration ──────────────────────────────────────

def test_ac6_tss_chart_loads_with_range_state():
    """trends.js must load the TSS chart whenever the range state changes."""
    assert "loadTSSChart" in JS or (
        "slot-tss" in JS and "loadChartData" in JS
    ), (
        "trends.js must reload the TSS overlay chart when the date-range picker changes."
    )


def test_ac6_tss_fetches_workouts_api():
    """trends.js must fetch TSS data — either from /api/workouts or /trends/summary (issue #52)."""
    # Issue #52 migrated TSS fetching to /trends/summary; either endpoint is acceptable.
    assert "/api/workouts" in JS or "/trends/summary" in JS, (
        "trends.js must fetch TSS data from /api/workouts or /trends/summary."
    )


def test_ac6_animation_duration_fast():
    """Chart animation must be fast (≤ 500 ms) so re-renders feel responsive."""
    durations = re.findall(r"duration:\s*(\d+)", JS)
    assert durations, (
        "trends.js must set animation: { duration: N } on the TSS overlay chart."
    )
    for d in durations:
        assert int(d) <= 500, (
            f"trends.js animation duration must be ≤ 500 ms to meet the range-change "
            f"re-render requirement; found {d} ms."
        )


def test_ac6_tss_chart_destroyed_on_reload():
    """trends.js must destroy the existing TSS chart instance before re-creating it."""
    assert "destroy" in JS or "tssOverlayChart = null" in JS, (
        "trends.js must destroy (or null-out) the existing tssOverlayChart before "
        "re-rendering so stale chart state doesn't accumulate across range changes."
    )


# ── AC-7: Tooltip ─────────────────────────────────────────────────────────────

def test_ac7_tss_tooltip_shows_date():
    """TSS chart tooltip must show the date."""
    assert "title" in JS and "dates[" in JS, (
        "trends.js TSS chart tooltip must include a title callback that returns the date "
        "for the hovered data point."
    )


def test_ac7_tss_tooltip_shows_tss_value():
    """TSS chart tooltip must display the TSS value for bar hover."""
    assert "TSS" in JS and "label" in JS, (
        "trends.js TSS chart tooltip must show 'TSS: <value>' for bar hover."
    )


def test_ac7_readiness_tooltip_shows_readiness():
    """TSS chart tooltip must display the next-day readiness for line hover."""
    assert "Next-day readiness" in JS or "next-day readiness" in JS.lower(), (
        "trends.js TSS chart tooltip must show 'Next-day readiness: <value>' for line hover."
    )


def test_ac7_interaction_mode_index():
    """TSS chart must use 'index' interaction mode so both datasets show on hover."""
    assert "mode: 'index'" in JS or "mode:'index'" in JS, (
        "trends.js TSS chart must set interaction mode: 'index' so hovering shows "
        "both the TSS bar value and the readiness line value simultaneously."
    )


# ── AC-8: Mobile / responsive layout ─────────────────────────────────────────

def test_ac8_responsive_true():
    """TSS chart must set responsive: true."""
    assert "responsive: true" in JS or "responsive:true" in JS, (
        "trends.js TSS chart config must set responsive: true for fluid sizing."
    )


def test_ac8_maintain_aspect_ratio_false():
    """TSS chart must set maintainAspectRatio: false."""
    assert "maintainAspectRatio: false" in JS or "maintainAspectRatio:false" in JS, (
        "trends.js TSS chart config must set maintainAspectRatio: false so the chart "
        "fills its container without causing horizontal scroll on mobile."
    )


def test_ac8_full_width_slot_class_in_html():
    """The TSS chart slot must span the full grid width (chart-slot--full)."""
    assert "chart-slot--full" in HTML, (
        "trends.html must apply the 'chart-slot--full' class to the TSS overlay chart slot "
        "so it spans the full grid width and is legible on all viewports."
    )


def test_ac8_full_width_css_defined():
    """trends.html must define CSS for .chart-slot--full to span all grid columns."""
    full_css = re.search(r'\.chart-slot--full\s*\{([^}]+)\}', HTML, re.DOTALL)
    assert full_css, (
        "trends.html must define CSS for .chart-slot--full."
    )
    block = full_css.group(1)
    assert "grid-column" in block or "1 / -1" in block, (
        ".chart-slot--full must use grid-column: 1 / -1 (or equivalent) to span all columns."
    )


def test_ac8_x_axis_tick_limit_for_narrow():
    """TSS chart x-axis must limit ticks so labels stay readable on small screens."""
    assert "maxTicksLimit" in JS, (
        "trends.js TSS chart must set maxTicksLimit on the x-axis to prevent label "
        "overlap on narrow (320–414 px) viewports."
    )


def test_ac8_max_rotation_zero():
    """TSS chart x-axis ticks must not rotate (maxRotation: 0)."""
    assert "maxRotation: 0" in JS or "maxRotation:0" in JS, (
        "trends.js must set maxRotation: 0 on the TSS chart x-axis so labels stay "
        "horizontal and don't overlap on small screens."
    )


# ── AC-9: Mock data integrity ─────────────────────────────────────────────────

def test_ac10_tss_slot_loading_state_in_html():
    """trends.html must show a loading skeleton for the TSS slot on initial load."""
    assert "slot-tss-body" in HTML, (
        "trends.html must include the 'slot-tss-body' element where the chart or empty state is rendered."
    )
    tss_body_region = HTML[HTML.find("slot-tss"):]
    has_loading = (
        "slot-loading" in tss_body_region or
        "skeleton" in tss_body_region
    )
    assert has_loading, (
        "trends.html must show a loading skeleton inside the TSS slot so the user "
        "sees feedback while chart data is being fetched."
    )


def test_ac10_tss_loading_shown_on_range_change():
    """trends.js must show loading state for TSS slot when range changes."""
    assert "slot-tss-body" in JS and "showLoading" in JS, (
        "trends.js must call showLoading on the TSS slot body when the date range changes, "
        "before the new data arrives."
    )
