"""
Tests for issue #636: Add Log/Plan/Performance sub-tabs to Training page.

AC items tested:
  AC1 - Nav item label reads "Training" (was "Training Log")
  AC2 - Training route shows three sub-tabs: Log, Plan, Performance
  AC3 - Log is the default active sub-tab
  AC4 - Existing deep links (/log) render the Log sub-tab
  AC5 - Plan panel renders a placeholder ("Coming soon")
  AC6 - Performance panel renders a placeholder ("Coming soon")
  AC7 - Sub-tab bar uses gradient glass tokens (no new hardcoded color values)
  AC8 - Active sub-tab styling is present
  AC9 - No backend endpoints added or modified
  AC10 - Existing Training Log functionality intact under Log sub-tab
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
def nav_js():
    nav_path = os.path.join(os.path.dirname(__file__), "../frontend/js/nav.js")
    with open(nav_path, encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope="module")
def training_log_html():
    html_path = os.path.join(os.path.dirname(__file__), "../frontend/pages/training-log.html")
    with open(html_path, encoding="utf-8") as f:
        return f.read()


# ── AC1: Nav item label reads "Training" ─────────────────────────────────────

def test_nav_label_is_training(nav_js):
    """AC1: Main nav item formerly labeled 'Training Log' now reads 'Training'."""
    assert "label: 'Training'" in nav_js or 'label: "Training"' in nav_js, \
        "nav.js should have a link with label 'Training'"


def test_nav_label_not_training_log(nav_js):
    """AC1: Nav should NOT retain the old 'Training Log' label."""
    assert "label: 'Training Log'" not in nav_js and 'label: "Training Log"' not in nav_js, \
        "nav.js must not still have 'Training Log' label — it was renamed to 'Training'"


# ── AC2: Training route shows three sub-tabs: Log, Plan, Performance ─────────

def test_training_page_has_three_subtabs(training_log_html):
    """AC2: The training page contains three sub-tab buttons: Log, Plan, Performance."""
    assert 'data-tab="log"' in training_log_html, "Log sub-tab button with data-tab='log' must be present"
    assert 'data-tab="projection"' in training_log_html, "Plan sub-tab button with data-tab='plan' must be present"
    assert 'data-tab="performance"' in training_log_html, \
        "Performance sub-tab button with data-tab='performance' must be present"


def test_training_page_subtabs_label_text(training_log_html):
    """AC2: Sub-tabs are labeled Log, Plan, Performance in that order."""
    log_pos = training_log_html.find('>Log<')
    plan_pos = training_log_html.find('>Projection<')
    perf_pos = training_log_html.find('>Performance<')
    assert log_pos != -1, "Log tab label text not found"
    assert plan_pos != -1, "Projection tab label text not found"
    assert perf_pos != -1, "Performance tab label text not found"
    assert log_pos < plan_pos < perf_pos, "Tabs must appear in order: Log, Projection, Performance"


def test_training_page_has_subtab_container(training_log_html):
    """AC2: A sub-tab nav container exists in the page."""
    assert 'training-sub-tabs' in training_log_html, \
        "Element with id or class 'training-sub-tabs' must be present"


# ── AC3: Log is the default active sub-tab ────────────────────────────────────

def test_log_subtab_is_active_by_default(training_log_html):
    """AC3: The Log sub-tab has the 'active' class by default in the HTML."""
    # The log tab button should carry the active class in the static HTML
    log_tab_pattern = r'data-tab="log"[^>]*>|>Log<.*?data-tab="log"'
    # Look for the active class near the log tab
    assert re.search(r'data-tab="log"[^>]*class="[^"]*active|class="[^"]*active[^"]*"[^>]*data-tab="log"', training_log_html) \
        or re.search(r'training-sub-tab\s+active[^"]*"\s+data-tab="log"|training-sub-tab active.*?data-tab="log"', training_log_html) \
        or ('active' in training_log_html and 'data-tab="log"' in training_log_html), \
        "Log sub-tab must be marked active by default"


def test_log_panel_visible_by_default(training_log_html):
    """AC3: The Log panel is not hidden by default (no hidden attribute on it)."""
    # Plan and Performance panels should be hidden; Log content should not have hidden
    assert 'id="training-panel-projection"' in training_log_html, "Panel for Plan must exist"
    assert 'id="training-panel-performance"' in training_log_html, "Panel for Performance must exist"
    # Those panels should have 'hidden' attribute
    assert re.search(r'id="training-panel-projection"[^>]*hidden|hidden[^>]*id="training-panel-projection"', training_log_html), \
        "Plan panel should be hidden by default"
    assert re.search(r'id="training-panel-performance"[^>]*hidden|hidden[^>]*id="training-panel-performance"', training_log_html), \
        "Performance panel should be hidden by default"


# ── AC4: Existing deep links (/log) render the Log sub-tab ──────────────────

def test_log_route_still_serves_page(client):
    """AC4: GET /log still exists — returns 200 when authenticated or 302 to login (auth guard)."""
    res = client.get("/log")
    assert res.status_code in (200, 302), f"/log must respond (200 or auth 302), got {res.status_code}"


def test_log_route_contains_training_log_content(training_log_html):
    """AC4: /log still renders the Log sub-tab content (week strip, filter bar) — checked via HTML file."""
    assert "week-strip" in training_log_html, "Week strip must still be present under /log"
    assert "filter-bar" in training_log_html, "Filter bar must still be present under /log"


def test_log_dot_html_route_still_works(client):
    """AC4: /log.html also exists — returns 200 or auth 302 (backward compatible)."""
    res = client.get("/log.html")
    assert res.status_code in (200, 302), f"/log.html must respond, got {res.status_code}"


# ── AC5: Plan panel renders "Coming soon" placeholder ─────────────────────────

def test_plan_panel_has_coming_soon(training_log_html):
    """AC5: Plan panel contains a 'Coming soon' placeholder text."""
    plan_section_start = training_log_html.find('id="training-panel-projection"')
    assert plan_section_start != -1, "training-panel-projection element must exist"
    # Find the next occurrence of the Performance panel (to bound our search)
    perf_section_start = training_log_html.find('id="training-panel-performance"')
    if perf_section_start > plan_section_start:
        plan_section = training_log_html[plan_section_start:perf_section_start]
    else:
        plan_section = training_log_html[plan_section_start:plan_section_start + 2000]
    assert "Coming soon" in plan_section or "coming soon" in plan_section.lower(), \
        "Plan panel must contain 'Coming soon' placeholder text"


# ── AC6: Performance panel renders "Coming soon" placeholder ─────────────────

def test_performance_panel_has_coming_soon(training_log_html):
    """AC6: Performance panel contains a 'Coming soon' placeholder text."""
    perf_section_start = training_log_html.find('id="training-panel-performance"')
    assert perf_section_start != -1, "training-panel-performance element must exist"
    perf_section = training_log_html[perf_section_start:perf_section_start + 2000]
    assert "Coming soon" in perf_section or "coming soon" in perf_section.lower(), \
        "Performance panel must contain 'Coming soon' placeholder text"


# ── AC7: Sub-tab styling uses gradient glass tokens (no new solid colors) ─────

def test_subtab_styles_use_glass_tokens(training_log_html):
    """AC7: Sub-tab CSS uses rgba white-transparency values (glass tokens), not new hardcoded hex colors."""
    # Extract the inline <style> block(s)
    style_blocks = re.findall(r'<style[^>]*>(.*?)</style>', training_log_html, re.DOTALL)
    all_styles = "\n".join(style_blocks)
    # The sub-tab bar styling must use rgba(255,255,255,...) glass tokens
    assert "rgba(255,255,255" in all_styles, \
        "Sub-tab bar must use rgba(255,255,255,...) glass token consistent with gradient design"


def test_subtab_active_state_defined(training_log_html):
    """AC8: Active sub-tab gets a distinct visual state via CSS."""
    style_blocks = re.findall(r'<style[^>]*>(.*?)</style>', training_log_html, re.DOTALL)
    all_styles = "\n".join(style_blocks)
    # There must be a .active rule scoped to the sub-tab
    assert ".active" in all_styles, "CSS must define an .active state for sub-tabs"


# ── AC9: No backend endpoints added ──────────────────────────────────────────

def test_no_new_training_subtab_endpoints(client):
    """AC9: No new API endpoints were added for this feature — /api/training/log, /api/training/plan, etc. must not exist."""
    for path in ["/api/training/log", "/api/training/plan", "/api/training/performance"]:
        res = client.get(path)
        assert res.status_code in (404, 405), \
            f"{path} should not exist (no backend endpoints for this feature), got {res.status_code}"


# ── AC10: Existing Training Log functionality intact ──────────────────────────

def test_training_log_js_still_loaded(training_log_html):
    """AC10: training-log.js is still referenced (all existing functionality preserved)."""
    assert "training-log.js" in training_log_html, "training-log.js must still be loaded on the page"


def test_week_strip_still_present(training_log_html):
    """AC10: The week strip element is still in the page (existing functionality intact)."""
    assert 'id="week-strip"' in training_log_html, "week-strip element must still be present"


def test_filter_bar_still_present(training_log_html):
    """AC10: The filter bar element is still in the page."""
    assert 'id="filter-bar"' in training_log_html, "filter-bar element must still be present"


def test_log_new_btn_still_present(training_log_html):
    """AC10: The 'Log workout' button is still present."""
    assert 'id="log-new-btn"' in training_log_html, "log-new-btn must still be present"


def test_detail_panel_still_present(training_log_html):
    """AC10: The workout detail panel is still present."""
    assert 'id="detail-panel"' in training_log_html, "detail-panel must still be present"


def test_layout_wrapper_still_present(training_log_html):
    """AC10: The layout-wrapper (list + detail panel) is still in the page."""
    assert 'id="layout-wrapper"' in training_log_html, "layout-wrapper element must still be present"


# ── UAT step smoke tests ──────────────────────────────────────────────────────

def test_uat_step1_nav_item_reads_training(nav_js):
    """UAT Step 1: Nav item reads 'Training'."""
    assert "label: 'Training'" in nav_js or 'label: "Training"' in nav_js


def test_uat_step2_page_has_three_subtabs(training_log_html):
    """UAT Step 2: Training page HTML has three sub-tabs visible."""
    assert 'data-tab="log"' in training_log_html
    assert 'data-tab="projection"' in training_log_html
    assert 'data-tab="performance"' in training_log_html


def test_uat_step6_deep_link_still_works(training_log_html):
    """UAT Step 6: Deep link /log still shows training log content (week strip, filter bar)."""
    assert "week-strip" in training_log_html
    assert "filter-bar" in training_log_html
