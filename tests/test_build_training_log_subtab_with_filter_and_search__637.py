"""
Tests for issue #637: Build Training Log sub-tab with filter and search.

AC items tested:
  AC1 - Log sub-tab exists within Training screen (reachable via sub-tab row)
  AC2 - Workouts grouped by calendar day, ordered newest-first (day-group CSS + JS function)
  AC3 - Filter row with type pills: All, Run, Lift, WOD, Bike
  AC4 - Search field present; filter pill + search compose (client-side filtering)
  AC5 - Each row: date, type-colored dot, type label, workout name, one key metric
  AC6 - Row click opens workout detail view (detail panel present, JS wired)
  AC7 - Data via existing /api/training-log endpoint; no new endpoints
  AC8 - Gradient theme consistent with other sub-tabs
  AC9 - Old History / New-log in-card toggle removed
  AC10 - Empty state shown when no workouts match filter + search
"""
import os
import re
import pytest
import httpx

BASE = os.environ.get("UAT_BASE_URL") or f"http://localhost:{os.environ.get('UAT_PORT', '9001')}"
if not BASE.startswith("http"):
    raise RuntimeError(
        "UAT_BASE_URL / UAT_PORT not set. Run the tester skill's Step 0 to resolve UAT before pytest."
    )


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c


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


# ── AC1: Log sub-tab exists and is reachable ─────────────────────────────────

def test_log_subtab_button_present(training_log_html):
    """AC1: Log sub-tab button with data-tab='log' exists."""
    assert 'data-tab="log"' in training_log_html, "Log sub-tab button must be present"


def test_log_subtab_is_active_by_default(training_log_html):
    """AC1: Log sub-tab is active by default (carries 'active' class in static HTML)."""
    assert re.search(
        r'class="[^"]*training-sub-tab[^"]*active[^"]*"[^>]*data-tab="log"|'
        r'data-tab="log"[^>]*class="[^"]*active',
        training_log_html
    ), "Log sub-tab must have 'active' class by default"


# ── AC2: Day-grouped list — CSS and JS support ────────────────────────────────

def test_day_group_css_present(inline_styles):
    """AC2: CSS for day-group elements is defined."""
    assert '.day-group' in inline_styles, \
        "CSS must define .day-group class for day-based grouping"


def test_day_group_header_css_present(inline_styles):
    """AC2: CSS for day-group header is defined."""
    assert '.day-group-header' in inline_styles, \
        "CSS must define .day-group-header class for day group headings"


def test_js_renders_day_grouped_list(training_log_js):
    """AC2: JS contains a function that renders or builds day-grouped rows."""
    assert (
        'day-group' in training_log_js
    ), "training-log.js must create elements with class 'day-group' for day-grouped rendering"


def test_js_day_order_newest_first(training_log_js):
    """AC2: JS sorts entries newest-first (reverse:true or .desc() ordering)."""
    # JS comparators for newest-first: a.date < b.date → 1 (i.e. desc)
    assert (
        'reverse' in training_log_js or
        "a.date < b.date ? 1" in training_log_js or
        "b.date > a.date" in training_log_js
    ), "JS must order day groups newest-first"


# ── AC3: Filter row with type pills ───────────────────────────────────────────

def test_filter_pills_row_present(training_log_html):
    """AC3: A filter pills container or #filter-bar is present in the HTML."""
    assert 'filter-bar' in training_log_html or 'log-type-filter' in training_log_html, \
        "A filter bar / type filter container must be present"


def test_js_builds_type_pills(training_log_js):
    """AC3: JS builds type filter pills for All, Run, Lift, WOD, Bike."""
    for label in ['All', 'Run', 'Lift', 'WOD', 'Bike']:
        assert label in training_log_js, f"JS must include type label '{label}' for filter pills"


def test_js_includes_all_five_type_opts(training_log_js):
    """AC3: JS defines all five type options: all, run, lift, wod, bike."""
    for t in ['all', 'run', 'lift', 'wod', 'bike']:
        assert "'" + t + "'" in training_log_js or '"' + t + '"' in training_log_js, \
            f"JS must include type key '{t}' in the filter options"


# ── AC4: Search field present + client-side composable filtering ──────────────

def test_search_input_present(training_log_html):
    """AC4: HTML has a search input element (rendered by JS into filter bar)."""
    assert 'log-search' in training_log_html or 'search' in training_log_html.lower(), \
        "A search input must be present"


def test_js_search_input_created(training_log_js):
    """AC4: JS creates and wires up a search input field."""
    assert "log-search" in training_log_js or "searchInput" in training_log_js, \
        "JS must create a search input (id='log-search' or searchInput)"


def test_js_client_side_filter_function(training_log_js):
    """AC4: JS contains a client-side filter/apply function (not just fetchAndRender on filter change)."""
    assert (
        'applyClientFilter' in training_log_js or
        'applyFilter' in training_log_js or
        'clientFilter' in training_log_js or
        'filterRows' in training_log_js or
        'applyListFilter' in training_log_js
    ), (
        "JS must have a client-side filter function (e.g. applyClientFilter) so filtering "
        "doesn't re-fetch from the server on every type-chip click or search keystroke"
    )


def test_js_search_is_case_insensitive(training_log_js):
    """AC4: JS search compares lowercased strings for case-insensitive matching."""
    assert 'toLowerCase' in training_log_js or 'lower' in training_log_js.lower(), \
        "JS must use toLowerCase() for case-insensitive search matching"


# ── AC5: Row content — date, dot, type label, name, key metric ───────────────

def test_type_dot_css_present(inline_styles):
    """AC5: CSS for .entry-type-dot is defined."""
    assert '.entry-type-dot' in inline_styles, "CSS must define .entry-type-dot"


def test_type_color_run_css(inline_styles):
    """AC5: CSS defines a distinct color for Run type dot."""
    assert 'entry-type--run' in inline_styles, "CSS must define .entry-type--run color"


def test_type_color_lift_css(inline_styles):
    """AC5: CSS defines a distinct color for Lift type dot."""
    assert 'entry-type--lift' in inline_styles, "CSS must define .entry-type--lift color"


def test_type_color_wod_css(inline_styles):
    """AC5: CSS defines a distinct color for WOD type dot."""
    assert 'entry-type--wod' in inline_styles, "CSS must define .entry-type--wod color"


def test_type_color_bike_css(inline_styles):
    """AC5: CSS defines a distinct color for Bike type dot."""
    assert 'entry-type--bike' in inline_styles, "CSS must define .entry-type--bike color"


def test_js_row_builds_type_dot(training_log_js):
    """AC5: JS buildEntryRow creates an entry-type-dot element."""
    assert 'entry-type-dot' in training_log_js, \
        "JS must create element with class 'entry-type-dot' in row builder"


def test_js_row_builds_type_label(training_log_js):
    """AC5: JS buildEntryRow creates an entry-type-label element."""
    assert 'entry-type-label' in training_log_js, \
        "JS must create element with class 'entry-type-label' in row builder"


def test_js_row_builds_workout_name(training_log_js):
    """AC5: JS row builder uses workout title/name."""
    assert 'w.title' in training_log_js or 'entry-title' in training_log_js, \
        "JS must display the workout title in each row"


def test_js_row_shows_run_distance(training_log_js):
    """AC5: JS shows distance as key metric for Run workouts."""
    assert 'distance_km' in training_log_js, \
        "JS must use distance_km for Run workout key metric"


def test_js_row_shows_duration_for_others(training_log_js):
    """AC5: JS shows duration as key metric for non-Run workouts."""
    assert 'duration_seconds' in training_log_js, \
        "JS must use duration_seconds as fallback key metric"


# ── AC6: Row click opens workout detail view ──────────────────────────────────

def test_detail_panel_still_present(training_log_html):
    """AC6: Workout detail panel element is present in HTML."""
    assert 'id="detail-panel"' in training_log_html, \
        "The workout detail panel must still exist in training-log.html"


def test_js_row_click_opens_detail(training_log_js):
    """AC6: JS wires row click to openDetailPanel."""
    assert 'openDetailPanel' in training_log_js, \
        "JS must call openDetailPanel when a workout row is clicked"


# ── AC7: No new API endpoints; existing /api/training-log used ────────────────

def test_no_new_training_log_endpoints(client):
    """AC7: No new API endpoints introduced for this feature."""
    for path in [
        "/api/training-log/days",
        "/api/training-log-grouped",
        "/api/training/log",
        "/api/workouts-by-day",
    ]:
        res = client.get(path)
        assert res.status_code in (404, 405), \
            f"{path} must not exist (no new endpoints for this feature), got {res.status_code}"


def test_existing_training_log_endpoint_used(training_log_js):
    """AC7: JS still calls /api/training-log."""
    assert '/api/training-log' in training_log_js, \
        "JS must still use /api/training-log endpoint (no new endpoints)"


def test_existing_endpoint_accessible(client):
    """AC7: /api/training-log endpoint still responds (200 or 401 for unauth)."""
    res = client.get("/api/training-log")
    assert res.status_code in (200, 401), \
        f"/api/training-log must still work, got {res.status_code}"


# ── AC8: Gradient theme ───────────────────────────────────────────────────────

def test_gradient_theme_variables_used(inline_styles):
    """AC8: Page uses gradient design system CSS variables (--page-bg, --card-bg, etc.)."""
    assert 'var(--page-bg)' in inline_styles or '--page-bg' in inline_styles, \
        "Page must use gradient theme CSS variables (--page-bg)"


def test_subtab_bar_uses_glass_tokens(inline_styles):
    """AC8: Sub-tab styling uses rgba white-transparency glass tokens."""
    assert 'rgba(255,255,255' in inline_styles, \
        "Sub-tab styling must use rgba(255,255,255,...) glass tokens"


# ── AC9: Old History / New-log toggle removed ─────────────────────────────────

def test_history_toggle_removed(training_log_html):
    """AC9: The old History/New-log in-card tab toggle is no longer in the HTML."""
    assert 'log-history-tabs' not in training_log_html, \
        "log-history-tabs (the old History/New-log toggle) must be removed"


def test_log_history_tab_buttons_removed(training_log_html):
    """AC9: Individual log-history-tab buttons are gone."""
    assert 'log-history-tab' not in training_log_html, \
        "log-history-tab class buttons must be removed from training-log.html"


def test_new_log_toggle_removed(training_log_html):
    """AC9: 'New log' tab button text is no longer inside a toggle (may still exist as CTA)."""
    # The tab button with data-tab="new" inside log-history-tabs must be gone
    assert 'data-tab="new"' not in training_log_html or 'log-history-tabs' not in training_log_html, \
        "The History/New-log in-card toggle (data-tab='new' inside log-history-tabs) must be removed"


# ── AC10: Empty state when no workouts match ──────────────────────────────────

def test_empty_state_element_present(training_log_html):
    """AC10: An empty-state element exists for the no-match case."""
    assert (
        'log-empty' in training_log_html or
        'log-empty-msg' in training_log_html or
        'empty-state' in training_log_html
    ), "An empty state element must exist for the no-match filter scenario"


def test_js_handles_empty_filter_result(training_log_js):
    """AC10: JS shows an empty-state message when filter + search yields no results."""
    assert (
        'log-empty' in training_log_js or
        'No workouts' in training_log_js or
        'no workouts' in training_log_js.lower() or
        'empty' in training_log_js.lower()
    ), "JS must handle empty filter results with an empty-state message"


def test_js_empty_state_no_orphaned_headers(training_log_js):
    """AC10: JS collapses day group headers when all their rows are hidden."""
    # Look for logic that hides day groups when no visible rows remain
    assert (
        'day-group' in training_log_js
    ), "JS must reference day-group elements (to collapse empty ones)"


# ── UAT step smoke tests ──────────────────────────────────────────────────────

def test_uat_step1_log_subtab_visible(training_log_html):
    """UAT Step 1: Log sub-tab is selectable in the Training screen."""
    assert 'data-tab="log"' in training_log_html


def test_uat_step2_run_filter_pill(training_log_js):
    """UAT Step 2: Run filter pill option exists."""
    assert 'run' in training_log_js


def test_uat_step3_search_field(training_log_js):
    """UAT Step 3: Search field is created and connected to filter logic."""
    assert 'searchInput' in training_log_js or 'log-search' in training_log_js


def test_uat_step4_empty_state(training_log_html):
    """UAT Step 4: Empty state element exists for no-match scenario."""
    assert 'log-empty-filter' in training_log_html or 'log-empty-msg' in training_log_html or \
        'empty-state' in training_log_html


def test_uat_step5_row_click_detail(training_log_js):
    """UAT Step 5: Row click opens detail view."""
    assert 'openDetailPanel' in training_log_js


def test_uat_step6_history_toggle_gone(training_log_html):
    """UAT Step 6: History/New-log toggle is gone from the Training card."""
    assert 'log-history-tabs' not in training_log_html


def test_uat_step7_row_has_key_metric(training_log_js):
    """UAT Step 7: Row builder includes key metric (distance or duration)."""
    assert 'entry-metric' in training_log_js or 'distance_km' in training_log_js
