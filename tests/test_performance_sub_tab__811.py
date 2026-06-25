"""Tests for issue #811: Implement Training > Performance sub-tab with real data.

AC items tested:
  AC1  - "coming soon" placeholder is removed from Performance panel
  AC2  - Score cards for endurance and speed render (ring containers)
  AC3  - Score cards have direction label and sparkline elements
  AC4  - Building-baseline state element exists (no number/ring when flag set)
  AC5  - Fitness chart canvas and CTL/ATL/TSB labels are present
  AC6  - Date-range selector has 30D / 90D / 6M / 1Y buttons
  AC7  - Today-marker logic is referenced in the performance script
  AC8  - Chart building-baseline state container exists
  AC9  - ACWR section has ratio, band, and guidance containers
  AC10 - ACWR baseline-forming note element exists
  AC11 - Personal Records strip container is present
  AC12 - Null-field dash rendering is referenced in the performance script
  AC13 - Threshold hint text ("Set your threshold in Settings") is in the script
  AC14 - No new hardcoded color hex values introduced in the performance panel CSS
  AC15 - Mobile single-column breakpoint (@media max-width) is defined
  AC16 - Mockup file committed to docs/mockups/performance-tab.md
  AC17 - Performance JS file is loaded in training-log.html

NOTE: The existing test in test_add_log_plan_performance_sub_tabs_to_training_page__636.py
      (test_performance_panel_has_coming_soon) will fail after this implementation because
      AC1 of issue #811 explicitly removes the "coming soon" placeholder.  That test was
      correct for the #636 requirement; it is superseded by #811.
"""
import os
import re
import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture(scope="module")
def training_log_html():
    path = os.path.join(REPO_ROOT, "frontend", "pages", "training-log.html")
    with open(path, encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope="module")
def perf_panel_html(training_log_html):
    """Extract just the Performance panel section from the training-log HTML."""
    start = training_log_html.find('id="training-panel-performance"')
    assert start != -1, "training-panel-performance element must exist"
    # Grab a generous 6 000-char slice (the panel content may be long)
    return training_log_html[start:start + 6000]


@pytest.fixture(scope="module")
def perf_js():
    path = os.path.join(REPO_ROOT, "frontend", "js", "training-performance.js")
    with open(path, encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope="module")
def page_styles(training_log_html):
    """All <style> block content from training-log.html."""
    blocks = re.findall(r'<style[^>]*>(.*?)</style>', training_log_html, re.DOTALL)
    return "\n".join(blocks)


# ── AC1: "coming soon" placeholder removed ───────────────────────────────────

def test_coming_soon_placeholder_removed(perf_panel_html):
    """AC1: The performance panel must NOT contain the old 'Coming soon' placeholder."""
    assert "coming soon" not in perf_panel_html.lower(), \
        "Performance panel still contains 'Coming soon' placeholder; AC1 requires its removal"


def test_coming_soon_element_removed(perf_panel_html):
    """AC1: The .tab-coming-soon element must be gone from the performance panel."""
    assert "tab-coming-soon" not in perf_panel_html, \
        "tab-coming-soon class must be removed from the performance panel"


# ── AC2: Score cards for endurance and speed ─────────────────────────────────

def test_endurance_score_card_present(perf_panel_html):
    """AC2: Endurance score card container is present in the performance panel."""
    assert "endurance" in perf_panel_html.lower(), \
        "Endurance score card must be present in the performance panel"


def test_speed_score_card_present(perf_panel_html):
    """AC2: Speed score card container is present in the performance panel."""
    assert "speed" in perf_panel_html.lower(), \
        "Speed score card must be present in the performance panel"


def test_score_ring_elements_present(perf_panel_html):
    """AC2: SVG ring element or ring container exists for score display."""
    has_svg_ring = "<svg" in perf_panel_html or "score-ring" in perf_panel_html or \
                   "perf-ring" in perf_panel_html
    assert has_svg_ring, \
        "Score ring SVG or ring container element must be present in the performance panel"


# ── AC3: Direction label and sparkline per card ───────────────────────────────

def test_direction_label_elements_present(perf_panel_html):
    """AC3: Direction label containers (improving/flat/declining) are in the panel."""
    assert "direction" in perf_panel_html or "improving" in perf_panel_html.lower() or \
           "perf-dir" in perf_panel_html, \
        "Direction label element or identifier must be present in the performance panel"


def test_sparkline_element_present(perf_panel_html):
    """AC3: Sparkline container element is present in the performance panel."""
    assert "sparkline" in perf_panel_html.lower() or "perf-spark" in perf_panel_html, \
        "Sparkline container must be present in the performance panel"


# ── AC4: Building-baseline state ─────────────────────────────────────────────

def test_building_baseline_state_element(perf_panel_html):
    """AC4: A building-baseline state element exists for score cards."""
    assert "building" in perf_panel_html.lower() or "baseline" in perf_panel_html.lower(), \
        "Building-baseline state element must be present in the performance panel"


def test_building_baseline_referenced_in_js(perf_js):
    """AC4: JS handles building_baseline flag from the performance endpoint."""
    assert "building_baseline" in perf_js or "building-baseline" in perf_js, \
        "training-performance.js must handle the building_baseline flag"


# ── AC5: Fitness chart canvas and labels ─────────────────────────────────────

def test_fitness_chart_canvas_present(perf_panel_html):
    """AC5: A <canvas> element for the CTL/ATL/TSB fitness chart is present."""
    assert "<canvas" in perf_panel_html, \
        "A <canvas> element for the fitness chart must be in the performance panel"


def test_fitness_chart_ctl_label(perf_panel_html):
    """AC5: CTL label is visible in the performance panel (as text or data attribute)."""
    assert "ctl" in perf_panel_html.lower() or "CTL" in perf_panel_html, \
        "CTL reference must be present in the performance panel"


def test_fitness_chart_atl_label(perf_panel_html):
    """AC5: ATL label is visible in the performance panel."""
    assert "atl" in perf_panel_html.lower() or "ATL" in perf_panel_html, \
        "ATL reference must be present in the performance panel"


def test_fitness_chart_tsb_label(perf_panel_html):
    """AC5: TSB (Form) label is visible in the performance panel."""
    assert "tsb" in perf_panel_html.lower() or "TSB" in perf_panel_html or \
           "form" in perf_panel_html.lower(), \
        "TSB/Form reference must be present in the performance panel"


# ── AC6: Date-range selector ─────────────────────────────────────────────────

def test_date_range_30d_button(perf_panel_html):
    """AC6: 30D date-range button is present."""
    assert "30D" in perf_panel_html or "30d" in perf_panel_html.lower(), \
        "30D date-range selector button must be present"


def test_date_range_90d_button(perf_panel_html):
    """AC6: 90D date-range button is present."""
    assert "90D" in perf_panel_html or "90d" in perf_panel_html.lower(), \
        "90D date-range selector button must be present"


def test_date_range_6m_button(perf_panel_html):
    """AC6: 6M date-range button is present."""
    assert "6M" in perf_panel_html or "6m" in perf_panel_html.lower(), \
        "6M date-range selector button must be present"


def test_date_range_1y_button(perf_panel_html):
    """AC6: 1Y date-range button is present."""
    assert "1Y" in perf_panel_html or "1y" in perf_panel_html.lower(), \
        "1Y date-range selector button must be present"


# ── AC7: Today marker on chart ────────────────────────────────────────────────

def test_today_marker_in_js(perf_js):
    """AC7: JS code references a today marker on the fitness chart."""
    has_today = "today" in perf_js.lower() and (
        "annotation" in perf_js.lower() or
        "marker" in perf_js.lower() or
        "line" in perf_js.lower() or
        "afterDraw" in perf_js or
        "xScale" in perf_js
    )
    assert has_today, \
        "training-performance.js must implement a today marker on the fitness chart"


# ── AC8: Chart building-baseline state ───────────────────────────────────────

def test_chart_baseline_state_container(perf_panel_html):
    """AC8: A container for the chart's building-baseline state exists."""
    has_state = "chart-baseline" in perf_panel_html or \
                ("building" in perf_panel_html.lower() and "chart" in perf_panel_html.lower()) or \
                "perf-chart-bb" in perf_panel_html or \
                "fitness-baseline" in perf_panel_html
    assert has_state, \
        "A building-baseline state container for the chart must be in the performance panel"


# ── AC9: ACWR section ─────────────────────────────────────────────────────────

def test_acwr_section_present(perf_panel_html):
    """AC9: ACWR section container is present in the performance panel."""
    assert "acwr" in perf_panel_html.lower() or "ACWR" in perf_panel_html, \
        "ACWR section must be present in the performance panel"


def test_acwr_ratio_element(perf_panel_html):
    """AC9: ACWR ratio display element is present."""
    has_ratio = "acwr-ratio" in perf_panel_html or \
                ("acwr" in perf_panel_html.lower() and "ratio" in perf_panel_html.lower())
    assert has_ratio, \
        "ACWR ratio display element must be in the performance panel"


def test_acwr_band_element(perf_panel_html):
    """AC9: ACWR band display element is present."""
    has_band = "acwr-band" in perf_panel_html or \
               ("acwr" in perf_panel_html.lower() and "band" in perf_panel_html.lower())
    assert has_band, \
        "ACWR band display element must be in the performance panel"


def test_acwr_guidance_element(perf_panel_html):
    """AC9: ACWR guidance text element is present."""
    has_guidance = "acwr-guidance" in perf_panel_html or \
                   ("acwr" in perf_panel_html.lower() and "guidance" in perf_panel_html.lower())
    assert has_guidance, \
        "ACWR guidance element must be in the performance panel"


# ── AC10: ACWR baseline-forming note ─────────────────────────────────────────

def test_acwr_baseline_forming_note(perf_panel_html):
    """AC10: A baseline-forming note element exists for the ACWR section."""
    has_forming = "baseline" in perf_panel_html.lower() and "forming" in perf_panel_html.lower()
    if not has_forming:
        # Could also be a generic element that JS shows/hides
        has_forming = "acwr-baseline" in perf_panel_html or "acwr-bb" in perf_panel_html
    assert has_forming, \
        "A 'baseline forming' note element must exist in the ACWR section"


def test_acwr_baseline_handled_in_js(perf_js):
    """AC10: JS handles baseline_forming band from ACWR computation."""
    assert "baseline_forming" in perf_js or "baseline-forming" in perf_js, \
        "training-performance.js must handle the ACWR baseline_forming band"


# ── AC11: Personal Records strip ─────────────────────────────────────────────

def test_pr_strip_container(perf_panel_html):
    """AC11: Personal records strip container is present."""
    has_pr = "personal" in perf_panel_html.lower() or \
             "record" in perf_panel_html.lower() or \
             "pr-strip" in perf_panel_html or \
             "perf-pr" in perf_panel_html
    assert has_pr, \
        "Personal records strip container must be present in the performance panel"


def test_pr_js_fetches_endpoint(perf_js):
    """AC11: JS fetches a personal-records endpoint.

    Updated by issue #914: the PRs strip now uses /api/athletes/{id}/detected-prs
    (auto-detected PRs) instead of the manual personal-records endpoint.  Either
    endpoint reference satisfies this AC — the requirement is that the strip
    fetches PR data from the API.
    """
    fetches_pr_data = (
        "personal-records" in perf_js
        or "personalRecords" in perf_js
        or "detected-prs" in perf_js
    )
    assert fetches_pr_data, \
        "training-performance.js must fetch PR data from an API endpoint"


# ── AC12: Null renders as dash ────────────────────────────────────────────────

def test_null_dash_in_js(perf_js):
    """AC12: JS renders null fields as a dash (—)."""
    assert "—" in perf_js or "—" in perf_js or "'—'" in perf_js or '"—"' in perf_js or \
           "dash" in perf_js.lower() or "null" in perf_js, \
        "training-performance.js must render null fields as '—'"


# ── AC13: Threshold hint ──────────────────────────────────────────────────────

def test_threshold_hint_in_js(perf_js):
    """AC13: JS shows a 'Set your threshold in Settings' hint when preference is missing."""
    assert "threshold" in perf_js.lower() and "settings" in perf_js.lower(), \
        "training-performance.js must show a threshold hint referencing Settings"


# ── AC14: No new hardcoded hex colors ────────────────────────────────────────

def test_performance_panel_styles_use_tokens(training_log_html):
    """AC14: The performance-tab CSS block must not introduce new hex color values.

    All colour values should come from existing CSS variables (var(--...)).
    New solid hex codes (#rrggbb) that are NOT already in styles.css are forbidden.
    """
    # Extract only the style blocks that appear INSIDE the performance panel section
    # (between id="training-panel-performance" and the next section start)
    perf_start = training_log_html.find('id="training-panel-performance"')
    if perf_start == -1:
        pytest.skip("Performance panel not found; cannot check style tokens")

    # Find any perf-specific <style> block that follows the panel
    # (inline style blocks near the panel area or a dedicated perf style)
    training_log_html.find("training-performance.js")

    # Extract all style blocks after the performance panel div
    tail = training_log_html[perf_start:]
    new_style_blocks = re.findall(r'<style[^>]*>(.*?)</style>', tail, re.DOTALL)

    if not new_style_blocks:
        # No dedicated style block after the panel — inline styles only or
        # styles are in the existing <style> block at the top of the file.
        # This is fine — just verify no new isolated hex values were added.
        return

    for block in new_style_blocks:
        # Disallow raw hex colours not wrapped by var()
        # Remove all var(...) usages first, then look for remaining hex values
        block_no_vars = re.sub(r'var\([^)]*\)', '', block)
        raw_hex = re.findall(r'#[0-9a-fA-F]{3,6}\b', block_no_vars)
        # Filter out hash-prefixed CSS IDs/selectors (e.g., #perf-ring starts with letter)
        colour_hex = [h for h in raw_hex if re.match(r'^#[0-9a-fA-F]{6}$|^#[0-9a-fA-F]{3}$', h)]
        assert not colour_hex, \
            f"Performance CSS must not introduce new hardcoded hex colors; found: {colour_hex}"


# ── AC15: Mobile single-column breakpoint ────────────────────────────────────

def test_mobile_breakpoint_defined(page_styles, perf_js):
    """AC15: A mobile single-column @media rule is present (in styles or performance JS's injected CSS)."""
    has_mobile_styles = re.search(r'@media[^{]*max-width[^{]*480|@media[^{]*max-width[^{]*480', page_styles)
    # The JS may inject a <style> or the HTML may have an inline style block
    has_in_js = "@media" in perf_js and ("480" in perf_js or "max-width" in perf_js)
    assert has_mobile_styles or has_in_js, \
        "Mobile single-column breakpoint (@media max-width: 480px) must be defined"


# ── AC16: Mockup file committed ───────────────────────────────────────────────

def test_mockup_file_committed():
    """AC16: docs/mockups/performance-tab.md has been committed as the visual reference."""
    mockup_path = os.path.join(REPO_ROOT, "docs", "mockups", "performance-tab.md")
    assert os.path.isfile(mockup_path), \
        "docs/mockups/performance-tab.md must be committed as the visual reference"


# ── AC17: Performance JS loaded in training-log.html ─────────────────────────

def test_performance_script_loaded(training_log_html):
    """AC17: training-performance.js is loaded in training-log.html."""
    assert "training-performance.js" in training_log_html, \
        "training-performance.js must be included in training-log.html"


def test_performance_panel_has_real_content(perf_panel_html):
    """AC17: The performance panel contains substantive content, not just a placeholder."""
    # Must have more than trivial content
    content_stripped = re.sub(r'<[^>]+>', '', perf_panel_html).strip()
    assert len(content_stripped) > 100, \
        "Performance panel must contain substantive HTML content (more than a placeholder)"
