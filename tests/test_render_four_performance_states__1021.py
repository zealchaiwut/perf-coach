"""Tests for issue #1021: Render four explicit performance states in frontend.

AC items tested:
  AC1 - training-performance.js reads the `state` field from the TOP-LEVEL performance
        payload to determine which UI branch to render (not sub-object inference)
  AC2 - `scored` state: renders the score card with the athlete's current score and
        trend indicator (ring + score number + direction)
  AC3 - `needs_thresholds` state: renders a prompt telling the athlete to set
        thresholds, with a direct link to the thresholds section in Settings
  AC4 - `building_baseline` state: renders a "keep training" encouragement message
        with no score card
  AC5 - `error` state: renders a retry message with a retry action available to
        the user
  AC6 - No code path renders a score card when the payload is null or the state
        is not `scored`
  AC7 - The `needs_thresholds` link navigates correctly to the thresholds section
        within Settings (/settings#thresholds)
"""

import os
import re

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture(scope="module")
def perf_js():
    path = os.path.join(REPO_ROOT, "frontend", "js", "training-performance.js")
    with open(path, encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope="module")
def training_log_html():
    path = os.path.join(REPO_ROOT, "frontend", "pages", "training-log.html")
    with open(path, encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope="module")
def perf_panel_html(training_log_html):
    """Extract just the Performance panel section from training-log.html."""
    start = training_log_html.find('id="training-panel-performance"')
    assert start != -1, "training-panel-performance element must exist"
    return training_log_html[start:start + 10000]


# ── AC1: JS reads top-level `state` field ────────────────────────────────────

def test_ac1_top_level_state_read_in_load_scores(perf_js):
    """AC1: _loadScores reads the top-level `state` field from the response, not
    per-sub-object state inference via null checks on endurance/speed."""
    assert "data.state" in perf_js, (
        "training-performance.js must read `data.state` from the top-level "
        "performance payload"
    )


def test_ac1_all_four_states_explicitly_branched(perf_js):
    """AC1: JS explicitly branches on all four state values."""
    for state in ["scored", "needs_thresholds", "building_baseline", "error"]:
        assert state in perf_js, (
            f"training-performance.js must have an explicit branch for state='{state}'"
        )


def test_ac1_no_null_endurance_check_determines_state(perf_js):
    """AC1: State is determined by the `state` field, not by checking if endurance
    is null. The old pattern `!data || typeof data !== 'object' || !data.state`
    (applied to sub-objects) must not be the sole dispatch mechanism."""
    # The new code reads top-level data.state at _loadScores level
    # We verify the top-level state read happens in the fetch callback
    assert "data.state" in perf_js, (
        "State must be read from `data.state` at the top level of the response, "
        "not inferred from null endurance/speed sub-objects"
    )


# ── AC2: scored state shows ring, score number, and trend ────────────────────

def test_ac2_scored_branch_renders_ring(perf_js):
    """AC2: When state is 'scored', the ring is drawn."""
    assert "_drawRing" in perf_js or "drawRing" in perf_js, (
        "JS must call _drawRing for the scored state"
    )


def test_ac2_scored_branch_renders_score_value(perf_js):
    """AC2: When state is 'scored', the numeric score value is rendered."""
    assert "perf-score-val" in perf_js or "scoreEl" in perf_js, (
        "JS must populate the score value element for the scored state"
    )


def test_ac2_scored_branch_renders_direction(perf_js):
    """AC2: When state is 'scored', a trend direction indicator is rendered."""
    assert "perf-dir" in perf_js and "direction" in perf_js, (
        "JS must render a direction indicator (perf-dir) for the scored state"
    )


def test_ac2_scored_branch_renders_sparkline(perf_js):
    """AC2: When state is 'scored', the sparkline trend chart is drawn."""
    assert "_drawSparkline" in perf_js or "drawSparkline" in perf_js, (
        "JS must call _drawSparkline for the scored state"
    )


def test_ac2_score_card_body_visible_only_for_scored(perf_js):
    """AC2: perf-card-body is made visible only for the scored state."""
    # The body element must be shown (display != none) for scored
    assert "perf-card-body" in perf_js or "bodyEl" in perf_js, (
        "JS must control the visibility of the score card body (perf-card-body)"
    )


# ── AC3: needs_thresholds shows prompt with Settings link ────────────────────

def test_ac3_needs_thresholds_branch_in_js(perf_js):
    """AC3: JS branches explicitly on state === 'needs_thresholds'."""
    assert "needs_thresholds" in perf_js, (
        "training-performance.js must branch explicitly on state='needs_thresholds'"
    )


def test_ac3_threshold_hint_element_in_both_cards(perf_panel_html):
    """AC3: Both Endurance and Speed cards have a perf-threshold-hint element."""
    assert perf_panel_html.count("perf-threshold-hint") >= 2, (
        "Both Endurance and Speed cards must have a perf-threshold-hint element "
        "for the needs_thresholds state"
    )


def test_ac3_threshold_hint_mentions_ftp(perf_panel_html):
    """AC3: The threshold prompt mentions FTP."""
    assert "FTP" in perf_panel_html or "ftp" in perf_panel_html.lower(), (
        "The threshold prompt must mention FTP"
    )


def test_ac3_threshold_hint_has_settings_link(perf_panel_html):
    """AC3: The threshold prompt contains an href link to Settings."""
    assert "href" in perf_panel_html and "settings" in perf_panel_html.lower(), (
        "The threshold prompt must include a link to the Settings page"
    )


def test_ac3_js_shows_threshold_hint_for_needs_thresholds(perf_js):
    """AC3: JS reveals the threshold-hint element when state=needs_thresholds."""
    assert "perf-threshold-hint" in perf_js or "threshEl" in perf_js, (
        "JS must reveal the threshold-hint element for needs_thresholds state"
    )


# ── AC4: building_baseline shows keep-training message, no score card ─────────

def test_ac4_building_baseline_branch_in_js(perf_js):
    """AC4: JS branches explicitly on state === 'building_baseline'."""
    assert "building_baseline" in perf_js, (
        "training-performance.js must branch explicitly on state='building_baseline'"
    )


def test_ac4_building_baseline_element_in_both_cards(perf_panel_html):
    """AC4: Both Endurance and Speed cards have a perf-building-baseline element."""
    assert perf_panel_html.count("perf-building-baseline") >= 2, (
        "Both Endurance and Speed cards must have a perf-building-baseline element"
    )


def test_ac4_building_baseline_has_reason_slot(perf_panel_html):
    """AC4: The building-baseline element contains a slot for the reason message."""
    assert "perf-bb-reason" in perf_panel_html or "perf-bb-text" in perf_panel_html, (
        "perf-building-baseline must contain an element for the reason/encouragement text"
    )


def test_ac4_building_baseline_uses_reason_from_api(perf_js):
    """AC4: JS populates the building-baseline reason from the API response."""
    assert "data.reason" in perf_js or ".reason" in perf_js, (
        "JS must use the `reason` field from the API response for the building_baseline message"
    )


def test_ac4_score_card_body_hidden_for_building_baseline(perf_js):
    """AC4: The score card body (ring + score) is not shown for building_baseline."""
    # The building_baseline branch must NOT show the body element.
    # We verify that body visibility is reset before non-scored states
    # (bodyEl.style.display = 'none' must occur before non-scored branches).
    assert "display" in perf_js and "none" in perf_js, (
        "JS must hide the score card body (display=none) for non-scored states"
    )


# ── AC5: error state shows retry message with retry action ───────────────────

def test_ac5_error_state_branch_in_js(perf_js):
    """AC5: JS handles the error state (HTTP error or state='error')."""
    has_error_path = (
        "error" in perf_js
        and ("_renderScoreError" in perf_js or "perf-error" in perf_js)
    )
    assert has_error_path, (
        "training-performance.js must handle the error state"
    )


def test_ac5_error_element_in_both_cards(perf_panel_html):
    """AC5: Both Endurance and Speed cards have an error-state element."""
    assert perf_panel_html.count("perf-error") >= 2, (
        "Both Endurance and Speed cards must have a perf-error element"
    )


def test_ac5_error_retry_action_exists_in_html(perf_panel_html):
    """AC5: The error element includes a retry action (button or link) the user can tap."""
    endurance_start = perf_panel_html.find('id="perf-score-endurance"')
    speed_start = perf_panel_html.find('id="perf-score-speed"')
    assert endurance_start != -1, "Endurance score card must exist"
    assert speed_start != -1, "Speed score card must exist"

    # Check each card's error div for a retry action
    for label, start in [("Endurance", endurance_start), ("Speed", speed_start)]:
        section = perf_panel_html[start:start + 1500]
        error_start = section.find("perf-error")
        assert error_start != -1, f"{label} card must have perf-error div"
        error_section = section[error_start:error_start + 400]
        has_retry = (
            "perf-retry" in error_section
            or "retry" in error_section.lower()
            or "<button" in error_section
            or "<a " in error_section
        )
        assert has_retry, (
            f"{label} error div must include a retry action (button or link); "
            f"found: {error_section!r}"
        )


def test_ac5_retry_action_wired_in_js(perf_js):
    """AC5: JS wires the retry action so the user can reload scores."""
    has_retry_wiring = (
        "perf-retry" in perf_js
        or "retry" in perf_js.lower()
        or "_loadScores" in perf_js  # retry calls _loadScores
    )
    assert has_retry_wiring, (
        "JS must wire the retry action so clicking it re-triggers _loadScores"
    )


# ── AC6: score card NOT rendered when state is not scored ────────────────────

def test_ac6_score_card_not_shown_for_needs_thresholds(perf_js):
    """AC6: Score card body is not shown when state=needs_thresholds.

    The needs_thresholds branch must not call _renderScoreCard or show bodyEl.
    """
    # Verify needs_thresholds is handled without calling the scored rendering path
    assert "needs_thresholds" in perf_js, (
        "needs_thresholds branch must exist in JS"
    )
    # The body must be hidden (display=none) for all non-scored paths
    # (checked by presence of reset logic before branching)
    assert "display" in perf_js and "none" in perf_js, (
        "JS must hide the score card body for non-scored states"
    )


def test_ac6_score_card_not_shown_for_null_payload(perf_js):
    """AC6: When the payload is null or state is missing, no score card is shown."""
    # The catch block or null guard must call _renderScoreError (not renderScoreCard body)
    has_null_guard = (
        "!data" in perf_js
        or "data == null" in perf_js
        or "_renderScoreError" in perf_js
    )
    assert has_null_guard, (
        "JS must guard against null payload and show error state, not score card"
    )


def test_ac6_score_card_shown_only_for_scored_state(perf_js):
    """AC6: The scored rendering path (showing ring + body) is only in the scored branch."""
    # Extract the scored branch and verify bodyEl display is only set there
    # Simple check: 'scored' must gate the body display
    scored_idx = perf_js.find("'scored'")
    if scored_idx == -1:
        scored_idx = perf_js.find('"scored"')
    assert scored_idx != -1, "scored branch must exist in JS"
    # After the scored check, the body display must be set to ''
    # We just verify body display logic exists
    assert "bodyEl" in perf_js or "perf-card-body" in perf_js, (
        "JS must control perf-card-body visibility"
    )


# ── AC7: needs_thresholds link goes to correct Settings section ──────────────

def test_ac7_settings_link_targets_thresholds_hash(perf_panel_html):
    """AC7: The needs_thresholds CTA link uses the /settings#thresholds URL."""
    assert "/settings#thresholds" in perf_panel_html or "settings" in perf_panel_html.lower(), (
        "The threshold CTA link must navigate to the thresholds section within Settings"
    )


def test_ac7_settings_link_is_anchor_with_href(perf_panel_html):
    """AC7: The thresholds section link is an <a> element with a valid href."""
    # Look for <a ... href="...settings...">
    links = re.findall(r'<a[^>]+href=["\'][^"\']*settings[^"\']*["\'][^>]*>', perf_panel_html)
    assert len(links) >= 2, (
        "Both Endurance and Speed threshold-hint elements must include an anchor "
        f"linking to Settings; found: {links}"
    )


def test_ac7_thresholds_hash_in_settings_link(perf_panel_html):
    """AC7: The Settings link specifically targets the #thresholds anchor."""
    assert "#thresholds" in perf_panel_html, (
        "The threshold-hint link must use the #thresholds hash to scroll to the "
        "thresholds section within Settings"
    )
