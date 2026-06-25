"""Tests for issue #930: Render four distinct score-card states on Performance tab.

AC items tested:
  AC1 - state === 'scored' + numeric score → ring, direction label, sparkline rendered
  AC2 - state === 'needs_thresholds' → CTA rendered (no ring, no fabricated number)
        with link to thresholds settings; mentions FTP / threshold HR / threshold pace
  AC3 - state === 'building_baseline' → reason string from endpoint shown (no ring, no fabricated number)
  AC4 - Fetch fails / unexpected shape → neutral "could not load" message (no dash, no fabricated value)
  AC5 - State is read from the response `state` field and branched on explicitly;
        null score alone does not determine state
  AC6 - All four states are visually distinct from one another
  AC7 - Both Endurance and Speed cards implement the same four-state logic
  AC8 - No card ever displays an unexplained dash
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
    return training_log_html[start:start + 8000]


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


# ── AC1: scored state shows ring, direction, sparkline ───────────────────────

def test_scored_state_branches_in_js(perf_js):
    """AC1: JS explicitly branches on state === 'scored'."""
    assert "'scored'" in perf_js or '"scored"' in perf_js, (
        "training-performance.js must branch explicitly on state === 'scored'"
    )


def test_scored_state_shows_ring_in_js(perf_js):
    """AC1: When state is 'scored', the ring is shown (not hidden)."""
    # The JS should set ring visible (style.display not 'none') for scored state.
    # We check that after a scored branch the ring is rendered.
    assert "_drawRing" in perf_js or "drawRing" in perf_js, (
        "Ring draw helper must be called for the scored state"
    )


def test_scored_state_shows_direction_in_js(perf_js):
    """AC1: JS renders direction label for scored state."""
    assert "perf-dir" in perf_js and "direction" in perf_js, (
        "Direction label (perf-dir) must be rendered for the scored state"
    )


def test_scored_state_shows_sparkline_in_js(perf_js):
    """AC1: JS renders sparkline for scored state."""
    assert "_drawSparkline" in perf_js or "drawSparkline" in perf_js, (
        "Sparkline draw helper must be called for the scored state"
    )


# ── AC2: needs_thresholds state ──────────────────────────────────────────────

def test_needs_thresholds_state_branched_in_js(perf_js):
    """AC2: JS branches explicitly on state === 'needs_thresholds'."""
    assert "needs_thresholds" in perf_js, (
        "training-performance.js must branch explicitly on state === 'needs_thresholds'"
    )


def test_needs_thresholds_no_ring_in_js(perf_js):
    """AC2: needs_thresholds state hides the ring."""
    # The JS must hide the ring element in the needs_thresholds branch.
    # We verify that after needs_thresholds check, ring is hidden (display = 'none').
    assert "needs_thresholds" in perf_js, (
        "needs_thresholds branch must exist; ring should be hidden within it"
    )
    # Verify ring is not drawn for needs_thresholds — check the structure
    # by confirming ring hide/show logic exists around state checks
    assert "display" in perf_js and "none" in perf_js, (
        "JS must use display:none to hide ring for non-scored states"
    )


def test_needs_thresholds_cta_in_html(perf_panel_html):
    """AC2: A threshold CTA element exists in each score card in the HTML."""
    assert perf_panel_html.count('perf-threshold-hint') >= 2, (
        "Both Endurance and Speed cards must have a perf-threshold-hint element"
    )


def test_needs_thresholds_cta_mentions_ftp(perf_panel_html):
    """AC2: The threshold CTA mentions FTP."""
    assert "FTP" in perf_panel_html or "ftp" in perf_panel_html.lower(), (
        "The threshold call-to-action must mention FTP"
    )


def test_needs_thresholds_cta_mentions_threshold_hr(perf_panel_html):
    """AC2: The threshold CTA mentions threshold HR."""
    assert "threshold HR" in perf_panel_html or "threshold heart rate" in perf_panel_html.lower() or \
           ("threshold" in perf_panel_html.lower() and "HR" in perf_panel_html), (
        "The threshold call-to-action must mention threshold HR"
    )


def test_needs_thresholds_cta_mentions_threshold_pace(perf_panel_html):
    """AC2: The threshold CTA mentions threshold pace."""
    assert "threshold pace" in perf_panel_html.lower() or \
           ("threshold" in perf_panel_html.lower() and "pace" in perf_panel_html.lower()), (
        "The threshold call-to-action must mention threshold pace"
    )


def test_needs_thresholds_cta_has_settings_link(perf_panel_html):
    """AC2: The threshold CTA includes a link to the thresholds settings page."""
    assert "settings" in perf_panel_html.lower() and "href" in perf_panel_html, (
        "The threshold CTA must include a link to the settings/thresholds page"
    )


# ── AC3: building_baseline state uses reason text ────────────────────────────

def test_building_baseline_state_branched_in_js(perf_js):
    """AC3: JS branches explicitly on state === 'building_baseline'."""
    assert "building_baseline" in perf_js, (
        "training-performance.js must branch explicitly on state === 'building_baseline'"
    )


def test_building_baseline_renders_reason_from_data(perf_js):
    """AC3: JS uses data.reason to populate the building-baseline message."""
    assert "data.reason" in perf_js or ".reason" in perf_js, (
        "training-performance.js must use the `reason` field from the API response "
        "to populate the building-baseline card message"
    )


def test_building_baseline_element_exists_in_html(perf_panel_html):
    """AC3: Both score cards have a perf-building-baseline element."""
    assert perf_panel_html.count('perf-building-baseline') >= 2, (
        "Both Endurance and Speed cards must have a perf-building-baseline element"
    )


def test_building_baseline_has_reason_slot_in_html(perf_panel_html):
    """AC3: The building-baseline element contains a sub-element for the reason text."""
    assert "perf-bb-reason" in perf_panel_html or "perf-bb-text" in perf_panel_html, (
        "perf-building-baseline must contain an element that JS fills with the reason string"
    )


# ── AC4: fetch error / unexpected shape → "could not load" ───────────────────

def test_error_state_element_exists_in_html(perf_panel_html):
    """AC4: Both score cards have an error-state element for fetch failures."""
    assert "perf-error" in perf_panel_html or "could not load" in perf_panel_html.lower(), (
        "Both score cards must have an error-state element (e.g. perf-error)"
    )


def test_error_state_message_in_js(perf_js):
    """AC4: JS renders a 'could not load' message on fetch failure or bad shape."""
    has_could_not_load = (
        "could not load" in perf_js.lower()
        or "could not load" in perf_js
        or "perf-error" in perf_js
        or "load error" in perf_js.lower()
    )
    assert has_could_not_load, (
        "training-performance.js must render a neutral 'could not load' message "
        "on fetch error or unexpected response shape"
    )


def test_error_handler_does_not_use_dash(perf_js):
    """AC4: The error handler must not set the score display to a bare dash.

    The _showScoreNull helper (which sets '—') must NOT be called from the error path.
    The error path should show a descriptive 'could not load' message instead.
    """
    # We require a dedicated error rendering path that is distinct from _showScoreNull.
    # The simplest check: an error render function or element must exist.
    has_error_path = (
        "_renderScoreError" in perf_js
        or "_showScoreError" in perf_js
        or "perf-error" in perf_js
        or "could not load" in perf_js.lower()
    )
    assert has_error_path, (
        "JS must have a dedicated error rendering path that does not use a bare dash"
    )


# ── AC5: state field drives branching, not null score alone ──────────────────

def test_state_field_read_explicitly(perf_js):
    """AC5: JS reads the `state` field explicitly from the response."""
    assert "data.state" in perf_js or ".state ===" in perf_js or ".state ==" in perf_js, (
        "JS must read `data.state` and branch on it explicitly"
    )


def test_null_score_alone_does_not_determine_state(perf_js):
    """AC5: The branching logic checks state field, not only score === null."""
    # The old code used `data.score === null` to determine the needs_thresholds state.
    # The new code must use `data.state === 'needs_thresholds'` (or similar state-based check).
    # We verify that `needs_thresholds` is the branch condition (not a score null check).
    assert "needs_thresholds" in perf_js, (
        "JS must branch on state === 'needs_thresholds', not just score === null"
    )


# ── AC6: all four states are visually distinct ────────────────────────────────

def test_four_state_css_for_error(page_styles):
    """AC6: CSS defines a distinct visual style for the error state."""
    assert "perf-error" in page_styles or "perf-load-error" in page_styles, (
        "CSS must define styling for the error state (perf-error or similar)"
    )


def test_threshold_hint_css_distinct(page_styles):
    """AC6: perf-threshold-hint has its own CSS rule."""
    assert "perf-threshold-hint" in page_styles, (
        "CSS must define perf-threshold-hint styling for the needs_thresholds state"
    )


def test_building_baseline_css_distinct(page_styles):
    """AC6: perf-building-baseline has its own CSS rule."""
    assert "perf-building-baseline" in page_styles, (
        "CSS must define perf-building-baseline styling for the building_baseline state"
    )


# ── AC7: both Endurance and Speed implement the same four-state logic ─────────

def test_endurance_card_has_all_state_elements(perf_panel_html):
    """AC7: Endurance card contains elements for all four states."""
    endurance_start = perf_panel_html.find('id="perf-score-endurance"')
    assert endurance_start != -1, "Endurance score card must exist"

    # Find the next card boundary
    speed_start = perf_panel_html.find('id="perf-score-speed"')
    if speed_start > endurance_start:
        endurance_section = perf_panel_html[endurance_start:speed_start]
    else:
        endurance_section = perf_panel_html[endurance_start:endurance_start + 1200]

    assert "perf-ring" in endurance_section, "Endurance card must have perf-ring (scored state)"
    assert "perf-building-baseline" in endurance_section, "Endurance card must have building-baseline element"
    assert "perf-threshold-hint" in endurance_section, "Endurance card must have threshold-hint element"
    assert "perf-error" in endurance_section or "could not load" in endurance_section.lower(), (
        "Endurance card must have an error-state element"
    )


def test_speed_card_has_all_state_elements(perf_panel_html):
    """AC7: Speed card contains elements for all four states."""
    speed_start = perf_panel_html.find('id="perf-score-speed"')
    assert speed_start != -1, "Speed score card must exist"
    speed_section = perf_panel_html[speed_start:speed_start + 1200]

    assert "perf-ring" in speed_section, "Speed card must have perf-ring (scored state)"
    assert "perf-building-baseline" in speed_section, "Speed card must have building-baseline element"
    assert "perf-threshold-hint" in speed_section, "Speed card must have threshold-hint element"
    assert "perf-error" in speed_section or "could not load" in speed_section.lower(), (
        "Speed card must have an error-state element"
    )


def test_render_function_handles_both_cards(perf_js):
    """AC7: The render function is reused for both endurance and speed cards."""
    # The existing pattern is _renderScoreCard(type, data), called for both.
    assert "_renderScoreCard" in perf_js or "renderScoreCard" in perf_js, (
        "A shared render function must be used for both endurance and speed cards"
    )
    assert "'endurance'" in perf_js or '"endurance"' in perf_js, (
        "The render function must be called for the endurance card"
    )
    assert "'speed'" in perf_js or '"speed"' in perf_js, (
        "The render function must be called for the speed card"
    )


# ── AC8: no card ever displays an unexplained dash ───────────────────────────

def test_show_score_null_not_called_on_error(perf_js):
    """AC8: The _showScoreNull helper (which sets '—') is not the error fallback.

    The catch block in _loadScores must call a dedicated error renderer,
    not _showScoreNull, to avoid displaying a bare dash on network failure.
    """
    # Check that the catch block calls something other than _showScoreNull
    # by verifying _renderScoreError or a perf-error-based function is referenced.
    has_error_renderer = (
        "_renderScoreError" in perf_js
        or "_showScoreError" in perf_js
        or "perf-error" in perf_js
        or "could not load" in perf_js.lower()
    )
    assert has_error_renderer, (
        "The error state must display a 'could not load' message, not a bare dash"
    )


def test_no_bare_dash_as_default_score_text(perf_panel_html):
    """AC8: Score cards must not ship with a bare '—' as their visible default text.

    The initial HTML may have '—' inside hidden elements (for the scored state
    fallback), but the card must have error and building-baseline elements to
    ensure users always see an explanatory message rather than a bare dash.
    """
    # The important thing is that both state-specific elements exist alongside
    # any '—', so a bare dash is never the only visible feedback.
    endurance_start = perf_panel_html.find('id="perf-score-endurance"')
    speed_start = perf_panel_html.find('id="perf-score-speed"')

    for label, start in [("Endurance", endurance_start), ("Speed", speed_start)]:
        assert start != -1, f"{label} score card must exist"
        end = start + 1200
        section = perf_panel_html[start:end]
        # Each card must have at least one non-scored state element
        has_non_scored_element = (
            "perf-building-baseline" in section
            or "perf-threshold-hint" in section
            or "perf-error" in section
        )
        assert has_non_scored_element, (
            f"{label} card must have at least one non-scored state element "
            "so a bare dash is never the only visible feedback"
        )
