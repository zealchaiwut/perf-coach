"""Tests for issue #1058: Summary digest card on the Log tab with weekly/monthly toggle.

AC items tested:
  AC1 - A Summary card element appears at the top of the Log tab above the session list
  AC2 - The card contains a "This week" / "This month" toggle; "This week" is the default
  AC3 - This week view renders: volume tile, load tile, session count tile, score-change
        chip, weight-change chip, form-change chip, and the weekly note
  AC4 - This month view renders additional: supercompensation state indicator, call-to-action,
        link to Plan tab, link to Performance tab
  AC5 - Chips whose underlying value is absent are hidden (not rendered as zero)
  AC6 - Switching the toggle a second time to a tab whose data is already loaded does NOT
        trigger a new network request (cache used)
  AC7 - Card layout follows design conventions (stat tiles row, chip row, note section,
        monthly supercompensation section)
  AC8 - Card handles loading and error states gracefully (skeleton / inline error message)
"""
import os
import re

import pytest


# ── Fixtures ────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def training_log_html():
    html_path = os.path.join(os.path.dirname(__file__), "../frontend/pages/training-log.html")
    with open(html_path, encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope="module")
def training_log_js():
    js_path = os.path.join(os.path.dirname(__file__), "../frontend/js/training-log.js")
    with open(js_path, encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope="module")
def inline_styles(training_log_html):
    blocks = re.findall(r'<style[^>]*>(.*?)</style>', training_log_html, re.DOTALL)
    return "\n".join(blocks)


# ── AC1: Summary card element exists above session list ──────────────────────────

def test_summary_card_element_exists_in_html(training_log_html):
    """AC1: Summary card has an id anchor in the HTML."""
    assert 'id="summary-digest-card"' in training_log_html, (
        "Expected #summary-digest-card element in training-log.html"
    )


def test_summary_card_is_above_history_card(training_log_html):
    """AC1: The summary digest card appears before the history card element in the DOM."""
    summary_pos = training_log_html.find('id="summary-digest-card"')
    # Find the history card's id or its containing div, not the CSS class definition
    history_pos = training_log_html.find('id="log-list"')
    assert summary_pos != -1, "summary-digest-card not found"
    assert history_pos != -1, "#log-list not found"
    assert summary_pos < history_pos, (
        "summary-digest-card must appear before the session list (#log-list) in the DOM"
    )


def test_summary_card_is_inside_list_main(training_log_html):
    """AC1: The summary card is inside #list-main (Log sub-tab container)."""
    list_main_start = training_log_html.find('id="list-main"')
    summary_pos = training_log_html.find('id="summary-digest-card"')
    assert list_main_start != -1, "#list-main not found"
    assert summary_pos != -1, "#summary-digest-card not found"
    assert summary_pos > list_main_start, (
        "#summary-digest-card must be inside #list-main"
    )


# ── AC2: Toggle elements ─────────────────────────────────────────────────────────

def test_toggle_buttons_exist_in_html(training_log_html):
    """AC2: 'This week' and 'This month' toggle buttons present."""
    assert "This week" in training_log_html, "Missing 'This week' toggle text"
    assert "This month" in training_log_html, "Missing 'This month' toggle text"


def test_this_week_toggle_is_default_active(training_log_html):
    """AC2: 'This week' button has the active/selected state by default."""
    # The week button should appear with is-active or active class or aria-selected=true
    week_btn_pattern = re.compile(
        r'<button[^>]*(?:is-active|active|aria-selected=["\']true["\'])[^>]*>\s*This week\s*</button>|'
        r'<button[^>]*>\s*This week\s*</button>[^<]*(?=.*?active)',
        re.DOTALL
    )
    # More straightforward: check the data-period or that "This week" is in a button with active class
    # Accept either: button has class containing 'active' near "This week", or data-period="week" is referenced as default
    week_active = (
        re.search(r'<button[^>]*(?:class=["\'][^"\']*(?:is-active|active)[^"\']*|aria-selected=["\']true["\'])[^>]*>\s*This week', training_log_html) or
        re.search(r'data-period=["\']week["\'][^>]*(?:is-active|active|aria-selected=["\']true["\'])', training_log_html) or
        re.search(r'(?:is-active|active|aria-selected=["\']true["\'])[^>]*data-period=["\']week["\']', training_log_html) or
        # Check the JS: "week" is the default active tab
        False
    )
    assert week_active, (
        "Expected 'This week' toggle button to be active by default (has active class or aria-selected=true)"
    )


def test_toggle_buttons_have_data_period_attributes(training_log_html):
    """AC2: Toggle buttons use data-period attributes for JS targeting."""
    assert 'data-period="week"' in training_log_html or "data-period='week'" in training_log_html, (
        "Expected data-period=\"week\" attribute on the 'This week' button"
    )
    assert 'data-period="month"' in training_log_html or "data-period='month'" in training_log_html, (
        "Expected data-period=\"month\" attribute on the 'This month' button"
    )


# ── AC3: Weekly view fields ──────────────────────────────────────────────────────

def test_weekly_view_renders_volume_tile(training_log_js):
    """AC3: JS renders a volume tile (distance_km) in the weekly view."""
    assert 'distance_km' in training_log_js, (
        "JS must reference distance_km for the volume tile"
    )
    # Check that there's a rendering of a 'volume' or 'distance' tile label
    has_volume_tile = 'volume' in training_log_js.lower() or 'distance' in training_log_js.lower()
    assert has_volume_tile, "JS must render a volume or distance tile"


def test_weekly_view_renders_load_tile(training_log_js):
    """AC3: JS renders a load tile (total_tss) in the weekly view."""
    assert 'total_tss' in training_log_js, (
        "JS must reference total_tss for the load tile"
    )


def test_weekly_view_renders_session_count_tile(training_log_js):
    """AC3: JS renders a session count tile in the weekly view."""
    assert 'session_count' in training_log_js, (
        "JS must reference session_count for the session count tile"
    )


def test_weekly_view_renders_score_change_chip(training_log_js):
    """AC3: JS renders score-change chip (endurance_score_change or speed_score_change)."""
    has_score_chip = (
        'endurance_score_change' in training_log_js or
        'speed_score_change' in training_log_js
    )
    assert has_score_chip, (
        "JS must reference endurance_score_change or speed_score_change for score chip"
    )


def test_weekly_view_renders_weight_change_chip(training_log_js):
    """AC3: JS renders weight-change chip (weight_change_kg)."""
    assert 'weight_change_kg' in training_log_js, (
        "JS must reference weight_change_kg for weight change chip"
    )


def test_weekly_view_renders_form_change_chip(training_log_js):
    """AC3: JS renders form-change chip (form_tsb_change)."""
    assert 'form_tsb_change' in training_log_js, (
        "JS must reference form_tsb_change for form change chip"
    )


def test_weekly_view_renders_note(training_log_js):
    """AC3: JS renders the weekly note field."""
    # 'note' field from weekly summary
    has_note = re.search(r'\bnote\b', training_log_js) is not None
    assert has_note, "JS must render the 'note' field from weekly summary"


# ── AC4: Monthly view additional fields ──────────────────────────────────────────

def test_monthly_view_renders_supercompensation_state(training_log_js):
    """AC4: JS renders supercompensation state indicator in monthly view."""
    assert 'supercompensation_state' in training_log_js, (
        "JS must reference supercompensation_state for monthly view"
    )


def test_monthly_view_renders_call_to_action(training_log_js):
    """AC4: JS renders call_to_action in monthly view."""
    assert 'call_to_action' in training_log_js, (
        "JS must reference call_to_action for monthly view"
    )


def test_monthly_view_has_plan_tab_link(training_log_js):
    """AC4: Monthly view contains a link/reference to the Plan tab."""
    has_plan_link = (
        '#plan' in training_log_js or
        "plan" in training_log_js.lower() and "tab" in training_log_js.lower()
    )
    assert has_plan_link, (
        "JS monthly view must include a link to the Plan tab"
    )


def test_monthly_view_has_performance_tab_link(training_log_js):
    """AC4: Monthly view contains a link/reference to the Performance tab."""
    has_perf_link = (
        '#performance' in training_log_js or
        "performance" in training_log_js.lower()
    )
    assert has_perf_link, (
        "JS monthly view must include a link to the Performance tab"
    )


# ── AC5: Absent data chips are hidden ───────────────────────────────────────────

def test_absent_weight_chip_is_hidden(training_log_js):
    """AC5: weight_change_kg chip is hidden when value is null/absent."""
    # The JS should check for null/undefined before rendering the weight chip
    has_null_guard = re.search(
        r'weight_change_kg\s*(?:!==?\s*null|==?\s*null|!=\s*null|!=\s*undefined)',
        training_log_js
    ) or re.search(
        r'if\s*\(\s*(?:data\.)?weight_change_kg',
        training_log_js
    ) or re.search(
        r'weight_change_kg\s*!=\s*null',
        training_log_js
    )
    assert has_null_guard, (
        "JS must guard weight_change_kg chip with a null check — "
        "the chip must be hidden when weight_change_kg is null"
    )


def test_absent_score_chip_is_hidden(training_log_js):
    """AC5: Score change chip is hidden when value is absent/zero."""
    # The rendering function should conditionally show the chip
    has_chip_guard = re.search(
        r'(?:endurance_score_change|speed_score_change)[^;]*?(?:!=|!==|===|==)\s*(?:null|0|undefined)',
        training_log_js
    ) or re.search(
        r'if\s*\([^)]*(?:endurance_score_change|speed_score_change)',
        training_log_js
    )
    assert has_chip_guard, (
        "JS must conditionally show score-change chip based on whether value is present"
    )


# ── AC6: Caching — no duplicate requests ────────────────────────────────────────

def test_summary_data_is_cached_in_js(training_log_js):
    """AC6: JS caches weekly/monthly summary data to prevent duplicate network requests."""
    # Look for a cache object/variable being set and checked
    has_cache = (
        re.search(r'_weekCache|_weekData|weeklyCache|weekCache|_summaryCache\[', training_log_js) or
        re.search(r'_monthCache|_monthData|monthlyCache|monthCache', training_log_js) or
        re.search(r'summaryCache\s*=|_cache\s*=|cached\w*\s*=', training_log_js)
    )
    assert has_cache, (
        "JS must cache weekly/monthly summary responses to avoid duplicate network requests "
        "when toggling back to an already-loaded tab"
    )


# ── AC7: Card layout and design tokens ──────────────────────────────────────────

def test_summary_card_has_stat_tiles_row_in_css(inline_styles):
    """AC7: CSS defines stat tiles for the summary card."""
    has_tile_style = (
        'sd-tile' in inline_styles or
        'summary-digest' in inline_styles or
        'stat-tile' in inline_styles
    )
    assert has_tile_style, (
        "CSS must define tile styles for the summary digest card stat tiles row"
    )


def test_summary_card_uses_log_card_class(training_log_html):
    """AC7: Summary digest card uses the log-card base class for consistent styling."""
    # The summary card should use the log-card styling pattern
    card_section = re.search(
        r'id="summary-digest-card"[^>]*class=["\'][^"\']*log-card[^"\']*["\']|'
        r'class=["\'][^"\']*log-card[^"\']*["\'][^>]*id="summary-digest-card"',
        training_log_html
    )
    assert card_section, (
        "summary-digest-card must include the log-card class for consistent card styling"
    )


def test_monthly_supercompensation_section_in_css(inline_styles):
    """AC7: CSS defines the supercompensation section shown in monthly view."""
    has_supercomp_style = (
        'supercomp' in inline_styles or
        'sd-supercomp' in inline_styles or
        'super-comp' in inline_styles
    )
    assert has_supercomp_style, (
        "CSS must define a supercompensation section style for the monthly view"
    )


# ── AC8: Loading and error states ───────────────────────────────────────────────

def test_summary_card_shows_skeleton_during_load(training_log_js):
    """AC8: JS shows a skeleton/loading state while fetching summary data."""
    has_skeleton = (
        'skeleton' in training_log_js or
        'is-loading' in training_log_js or
        'Loading' in training_log_js
    )
    assert has_skeleton, (
        "JS must render a skeleton or loading state while the summary data is being fetched"
    )


def test_summary_card_handles_error_state(training_log_js):
    """AC8: JS handles fetch errors gracefully and shows an inline error message."""
    # The fetch error should be caught and an error state rendered
    has_error_handler = re.search(
        r'(?:catch|\.catch)\s*\([^)]*\)[^{]*\{[^}]*(?:error|Error|err)',
        training_log_js
    ) or re.search(
        r'renderSummaryError|sd-error|summary.*error|error.*summary|is-error',
        training_log_js,
        re.IGNORECASE
    )
    assert has_error_handler, (
        "JS must handle network errors in summary fetch and show an inline error state"
    )


def test_api_endpoints_referenced_in_js(training_log_js):
    """AC8: JS references the correct weekly and monthly summary API endpoints."""
    has_weekly_endpoint = (
        'summary/weekly' in training_log_js or
        '/summary/weekly' in training_log_js
    )
    has_monthly_endpoint = (
        'summary/monthly' in training_log_js or
        '/summary/monthly' in training_log_js
    )
    assert has_weekly_endpoint, (
        "JS must call /api/athletes/{id}/summary/weekly for the weekly summary"
    )
    assert has_monthly_endpoint, (
        "JS must call /api/athletes/{id}/summary/monthly for the monthly summary"
    )


def test_summary_card_no_crash_when_no_sessions(training_log_js):
    """AC8: JS handles the case where the monthly endpoint returns 424 (no data)."""
    # The monthly endpoint returns 424 when no training data exists for the month.
    # The JS should handle non-2xx responses gracefully.
    has_non_ok_handler = re.search(
        r'(?:res|response|r)\.ok|status.*4[02][24]|424',
        training_log_js
    )
    assert has_non_ok_handler, (
        "JS must handle non-2xx responses from the monthly summary endpoint "
        "(endpoint returns 424 when no training data exists)"
    )
